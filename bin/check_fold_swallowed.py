#!/usr/bin/env python3
"""Flags YAML folded (>) block scalars where a comment line immediately
precedes what looks like a real directive, with no blank-line separator.

Why this exists: in a folded (`>`) scalar, a single newline between two
non-blank lines collapses to a space. A comment paragraph followed
directly by a real config directive -- with no blank line between them --
silently merges into one line starting with `#`, and the directive is
swallowed into the comment. It never becomes real config content, and
nothing about the YAML itself is invalid, so this passes ordinary YAML
parsing and even a generic yamllint pass. See dvystrcil/homelab#820 for
the incident this was built from: this exact pattern silently reverted
a Kubernetes ConfigMap's `trustedReverseProxy` setting to its unset
default, and the pod kept crash-looping through a "fix" that never took
effect.

Purely positional/structural, not content-pattern-based: it does NOT
flag every comment line that happens to mention a config-looking string
(a `# example: port=8080` explanation is fine) -- only a comment line
directly followed (no blank line) by a line that, taken on its own,
looks like a complete standalone directive (`key=value` or `key: value`,
nothing else on the line). This also means it correctly leaves alone
prose comments that wrap across multiple raw source lines without a
leading `#` on continuation lines (a legitimate, common convention --
e.g. upstream trilium's own config.ini template does this) since a
wrapped prose fragment doesn't match the bare-directive shape.

Only `>` (folded) scalars are in scope. `|` (literal) scalars preserve
every newline exactly as written and can't exhibit this bug.
"""
import argparse
import re
import sys

FOLDED_KEY = re.compile(r"^(?P<indent>[ ]*)\S[^:\n]*:\s*>[-+0-9]{0,2}\s*(#.*)?$")

# The swallowed line, taken entirely on its own (stripped), must look like
# a complete standalone assignment -- identifier, separator, optional bare
# value, nothing else. This is what distinguishes a real directive from a
# prose continuation fragment ("backend api.getInstanceName()", "the
# server will listen") which has interior spaces/punctuation.
DIRECTIVE_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*\s*[:=]\s*\S*$")


def find_folded_blocks(lines):
    """Yield (key_line_no, block_indent, block_lines) for each `>` scalar."""
    i = 0
    n = len(lines)
    while i < n:
        m = FOLDED_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        key_indent = len(m.group("indent"))
        j = i + 1
        while j < n and lines[j].strip() == "":
            j += 1
        if j >= n or len(lines[j]) - len(lines[j].lstrip(" ")) <= key_indent:
            i += 1
            continue
        block_indent = len(lines[j]) - len(lines[j].lstrip(" "))
        block_start = j
        while j < n:
            if lines[j].strip() == "":
                j += 1
                continue
            cur_indent = len(lines[j]) - len(lines[j].lstrip(" "))
            if cur_indent < block_indent:
                break
            j += 1
        yield (i + 1, block_indent, lines[block_start:j])
        i = j


def check_text(path, text):
    lines = text.splitlines()
    findings = []
    for key_line_no, _indent, block in find_folded_blocks(lines):
        for k in range(len(block) - 1):
            cur = block[k].strip()
            nxt = block[k + 1].strip()
            if (
                cur.startswith("#")
                and nxt != ""
                and not nxt.startswith("#")
                and DIRECTIVE_SHAPE.match(nxt)
            ):
                findings.append(
                    {
                        "file": path,
                        "key_line": key_line_no,
                        "comment": cur[:80],
                        "swallowed": nxt[:80],
                    }
                )
    return findings


def check_file(path):
    with open(path, encoding="utf-8") as f:
        return check_text(path, f.read())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="YAML files to check")
    args = parser.parse_args(argv)

    all_findings = []
    for path in args.files:
        all_findings += check_file(path)

    for f in all_findings:
        print(
            f"{f['file']}:{f['key_line']}: folded (>) scalar -- a comment line "
            "directly precedes what looks like a real directive, with no "
            "blank-line separator between them"
        )
        print(f"    comment:   {f['comment']}")
        print(f"    swallowed: {f['swallowed']}")
        print(
            "    fix: insert a blank line between the comment and the "
            "directive (folded scalars join adjacent non-blank lines)"
        )

    if all_findings:
        print(f"\nFAIL: {len(all_findings)} fold-swallowed directive(s) found")
        return 1
    print("OK: no fold-swallowed directives found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
