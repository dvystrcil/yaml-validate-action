# yaml-validate-action

Two PR-time YAML checks in one composite action:

1. **`yamllint`** — standard syntax/style linting, tuned for Kubernetes
   manifests (see [`.yamllint-default.yaml`](.yamllint-default.yaml)).
2. **Fold-swallow check** — a homelab-specific check for folded (`>`)
   block-scalar content silently swallowed into a preceding comment.

## Why this exists

`dvystrcil/trilium-notes#7` "fixed" a live crash-loop by setting
`trustedReverseProxy=uniquelocal` in a `ConfigMap`'s `config.ini`. The
PR merged, checks were green, and the pod kept crash-looping at the
same rate. The directive had been placed directly under a multi-line
comment with no blank line separating them — and that ConfigMap's
`config.ini` uses a folded (`>`) YAML scalar, where a single newline
between non-blank lines collapses to a space. The comment and the
directive merged into one line starting with `#`, and the directive
was silently swallowed into the comment. It never became real config.

Nothing about that YAML was invalid. Ordinary parsing accepts it.
`yamllint` accepts it. The only way to notice is to actually read the
rendered `config.ini` content and see the directive missing — which is
exactly what a human reviewing a one-line diff has no reason to do.
See `dvystrcil/homelab#820` for the full incident.

## The fold-swallow check

Purely structural, not content-pattern-based: it flags a comment line
(`#...`) immediately followed (no blank line) by a line that, taken
entirely on its own, looks like a complete standalone directive
(`key=value` or `key: value`, nothing else on the line). It does **not**
flag every comment that happens to mention something config-shaped —
`# example: set port=8080 in your shell` is left alone, since the real
danger is a directive-shaped line with nothing around it, not a comment
mentioning one in passing.

It also correctly leaves alone a legitimate, common convention: a
comment paragraph that wraps across multiple raw source lines without
a leading `#` on continuation lines (relying on folding to join them
into one valid comment line — upstream trilium's own `config.ini`
template does exactly this). A wrapped prose fragment doesn't match
the bare-directive shape, so it's never flagged.

Only `>` (folded) scalars are in scope. `|` (literal) scalars preserve
every newline exactly as written and can't exhibit this bug at all.

**What it can't catch**: any swallowed value that doesn't look like a
bare `key=value`/`key: value` line on its own — e.g. a swallowed value
that's itself multi-word, or a folded scalar holding something other
than INI/config-style directives. It trades some recall for a very low
false-positive rate; a looser content match was tested and immediately
false-positived on ordinary comments mentioning URLs with query params
or example settings.

## Usage

```yaml
name: validate
on: [pull_request]
jobs:
  yaml:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: dvystrcil/yaml-validate-action@v1
```

Inputs:

| Input | Default | Description |
|---|---|---|
| `path` | `**/*.yaml **/*.yml` | Glob pattern(s) of files to check |
| `yamllint-config` | *(bundled default)* | Path to your own `.yamllint` to override the relaxed default |
| `skip-yamllint` | `false` | Run only the fold-swallow check |
| `skip-fold-check` | `false` | Run only yamllint |

## What this deliberately does NOT do

- **Doesn't parse or validate against any Kubernetes/Helm schema** — it
  has no idea what a `ConfigMap` or `Deployment` is. It operates on raw
  YAML structure only. Pair with `kustomize-validate-action` (or
  `helm-validate-action`) for schema-level checks.
- **Doesn't catch every possible fold-collapse surprise** — only the
  specific "comment swallows a bare directive" shape. A folded scalar
  holding prose that accidentally reads differently once joined (but
  isn't a directive) won't be flagged; that class of mistake needs a
  human to actually read the rendered output.
- **No cluster access** — pure static analysis on the checked-out files.

## Provenance

Built 2026-08-01, from `dvystrcil/homelab#820` (trilium-notes#7/#8) —
a fix that appeared to work (green checks, merged) but silently didn't,
because the bug class lives entirely in YAML's folding semantics, not
in anything a schema or generic linter checks.

## License

[MIT](LICENSE)
