"""The action lints every tracked YAML file the pattern names, the same way
on every runner.

    python3 -m unittest tests.test_file_resolution -v

dvystrcil/prometheus#66: values.yaml held three `resources:` keys in one
mapping (PyYAML keeps the last; the chart read none). yamllint's
key-duplicates rule flags exactly that, and this action ran on every
prometheus PR from 2026-08-07, green, because it never opened values.yaml.

The file list came from `for pattern in ${{ inputs.path }}`, unquoted, so
bash expanded `**/*.yaml` against the checkout before `find` saw it. The
result depended on the repo's layout, not on the input: with no YAML in a
subdirectory the glob stayed literal and everything was linted; with any,
it matched one directory down only and root files dropped out (28 of 32
in prometheus). Three more inputs were not pinned either: whichever
yamllint was on PATH, a shared /tmp list file, and no check that the list
was complete.

These tests run the action's own `run:` scripts and `env:` blocks,
extracted from action.yml, so they test what ships rather than a copy.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())
DEFAULT_PATH = ACTION["inputs"]["path"]["default"]

# The #66 shape: resources blocks indented under commented-out parents,
# so all three land in one mapping as duplicate keys.
DUPLICATE_RESOURCES = textwrap.dedent("""\
    additionalPrometheusRulesMap:
      homelab-custom-rules:
        groups: []
        # prometheusSpec:
        resources:
          requests:
            memory: 2Gi
        # alertmanagerSpec:
        resources:
          requests:
            memory: 64Mi
    """)
CLEAN = "key: value\n"

# One venv for the whole run, as the action shares one per tool cache.
TOOL_CACHE = tempfile.mkdtemp(prefix="yaml-validate-toolcache-")


def tearDownModule():
    shutil.rmtree(TOOL_CACHE, ignore_errors=True)


def _step(name):
    for step in ACTION["runs"]["steps"]:
        if name in (step.get("id"), step.get("name")):
            return step
    raise AssertionError(f"no step {name!r} in action.yml")


def _substitute(text, inputs):
    subs = {f"${{{{ inputs.{k} }}}}": v for k, v in inputs.items()}
    subs["${{ github.action_path }}"] = str(ROOT)
    for expr, value in subs.items():
        text = text.replace(expr, value)
    assert "${{" not in text, f"unsubstituted expression: {text!r}"
    return text


class Repo:
    """A throwaway git checkout plus the runner environment around it."""

    def __init__(self, testcase, files, untracked=(), git=True):
        self.dir = tempfile.mkdtemp(prefix="yaml-validate-repo-")
        self.temp = tempfile.mkdtemp(prefix="yaml-validate-runner-temp-")
        testcase.addCleanup(shutil.rmtree, self.dir, True)
        testcase.addCleanup(shutil.rmtree, self.temp, True)
        for rel, text in {**files, **{u: CLEAN for u in untracked}}.items():
            p = pathlib.Path(self.dir, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if git:
            self.git("init", "-q")
            if files:
                self.git("add", "--", *files)
        self.env = dict(os.environ, RUNNER_TEMP=self.temp,
                        RUNNER_TOOL_CACHE=TOOL_CACHE,
                        GITHUB_OUTPUT=os.path.join(self.temp, "gh-output"))

    def git(self, *args):
        subprocess.run(["git", "-C", self.dir, *args], check=True,
                       capture_output=True)

    def run(self, *steps, path=DEFAULT_PATH, extra_env=None):
        """Run action steps in order, as the runner would; stop at the first failure."""
        inputs = {"path": path, "yamllint-config": ""}
        r = None
        for name in steps:
            step = _step(name)
            env = dict(self.env, **(extra_env or {}))
            for k, v in (step.get("env") or {}).items():
                env[k] = _substitute(str(v), inputs)
            r = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail",
                 "-c", _substitute(step["run"], inputs)],
                cwd=self.dir, env=env, capture_output=True, text=True)
            if r.returncode != 0:
                return r
        return r

    def listed(self):
        # NUL-separated, as git ls-files -z writes it and xargs -0 reads it.
        raw = pathlib.Path(self.temp, "yaml-validate-files.txt").read_text()
        return [f for f in raw.split("\0") if f]


class TestFileResolution(unittest.TestCase):
    def test_root_and_nested_files_are_both_listed(self):
        repo = Repo(self, {"values.yaml": CLEAN, "networking/route.yaml": CLEAN,
                           "deep/er/x.yml": CLEAN})
        r = repo.run("files")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(repo.listed()),
                         ["deep/er/x.yml", "networking/route.yaml", "values.yaml"])

    def test_listed_set_is_every_tracked_yaml_file(self):
        # The coverage property itself: nothing tracked is skipped,
        # whatever the layout -- dot-directories and spaces included.
        files = {"values.yaml": CLEAN, ".github/workflows/ci.yml": CLEAN,
                 "a/b/c/d.yaml": CLEAN, "with space.yaml": CLEAN,
                 "notes.md": "# not yaml\n"}
        repo = Repo(self, files)
        r = repo.run("files")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tracked = subprocess.run(["git", "-C", repo.dir, "ls-files", "*.yaml", "*.yml"],
                                 capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(sorted(repo.listed()), sorted(tracked))
        self.assertIn("Linting 4 of 4 tracked YAML file(s)", r.stdout)

    def test_untracked_files_are_not_listed(self):
        # Generated or scratch files in the workspace are not the repo.
        repo = Repo(self, {"values.yaml": CLEAN}, untracked=["rendered.yaml"])
        r = repo.run("files")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(repo.listed(), ["values.yaml"])

    def test_directory_part_of_a_pattern_is_honored(self):
        repo = Repo(self, {"values.yaml": CLEAN, "charts/a/x.yaml": CLEAN,
                           "other/x.yaml": CLEAN})
        r = repo.run("files", path="charts/**/*.yaml")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(repo.listed(), ["charts/a/x.yaml"])
        self.assertIn("Linting 1 of 3 tracked YAML file(s)", r.stdout)

    def test_same_list_whatever_the_shell_glob_options(self):
        # The runner's bash honors BASH_ENV; a list that changes with
        # globstar/nullglob is the original bug in another form.
        files = {"values.yaml": CLEAN, "sub/x.yaml": CLEAN}
        plain = Repo(self, files)
        plain.run("files")
        rc = os.path.join(plain.temp, "rc")
        pathlib.Path(rc).write_text("shopt -s globstar nullglob dotglob\n")
        tuned = Repo(self, files)
        r = tuned.run("files", extra_env={"BASH_ENV": rc})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(tuned.listed()), sorted(plain.listed()))

    def test_no_match_fails_instead_of_linting_nothing(self):
        repo = Repo(self, {"values.yaml": CLEAN})
        r = repo.run("files", path="nope/**/*.yaml")
        self.assertNotEqual(r.returncode, 0, "zero files linted passed")

    def test_outside_a_git_checkout_fails(self):
        repo = Repo(self, {"values.yaml": CLEAN}, git=False)
        r = repo.run("files")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("git checkout", r.stdout + r.stderr)

    def test_list_lives_in_runner_temp_not_shared_tmp(self):
        repo = Repo(self, {"values.yaml": CLEAN})
        repo.run("files")
        self.assertTrue(pathlib.Path(repo.temp, "yaml-validate-files.txt").exists())
        self.assertNotIn("/tmp/yaml-validate-files.txt",
                         "".join(s.get("run", "") for s in ACTION["runs"]["steps"]))


class TestLint(unittest.TestCase):
    def test_duplicate_keys_in_root_values_yaml_fail_the_action(self):
        repo = Repo(self, {"values.yaml": DUPLICATE_RESOURCES,
                           "networking/route.yaml": CLEAN})
        r = repo.run("files", "yamllint")
        self.assertNotEqual(r.returncode, 0,
                            "duplicate keys in root values.yaml passed the lint")
        self.assertIn("key-duplicates", r.stdout + r.stderr)

    def test_clean_repo_passes(self):
        repo = Repo(self, {"values.yaml": CLEAN, "networking/route.yaml": CLEAN,
                           "with space.yaml": CLEAN})
        r = repo.run("files", "yamllint", "Fold-swallow check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("FOLD-CHECK-COMPLETE", r.stdout)

    def test_yamllint_on_path_is_not_used(self):
        # A runner-provided yamllint (any version, or a stub) must not
        # decide the result: the pinned one does.
        repo = Repo(self, {"values.yaml": DUPLICATE_RESOURCES})
        fake = tempfile.mkdtemp(prefix="yaml-validate-fakebin-")
        self.addCleanup(shutil.rmtree, fake, True)
        stub = pathlib.Path(fake, "yamllint")
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        r = repo.run("files", "yamllint",
                     extra_env={"PATH": fake + os.pathsep + os.environ["PATH"]})
        self.assertNotEqual(r.returncode, 0, "a yamllint stub on PATH decided the result")
        self.assertIn("key-duplicates", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
