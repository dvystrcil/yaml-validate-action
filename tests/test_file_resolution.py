"""The action lints root-level YAML, not only files in subdirectories.

    python3 -m unittest tests.test_file_resolution -v

`for pattern in ${{ inputs.path }}` was unquoted, so bash expanded the
default `**/*.yaml` against the working directory before `find` saw it.
Without globstar that matches `*/*.yaml` -- files one directory down --
and `find -name "$(basename ...)"` then searched for those basenames
only. A root-level values.yaml was never linted unless a subdirectory
happened to hold a file of the same name.

dvystrcil/prometheus#66: values.yaml held three `resources:` keys in one
mapping (PyYAML keeps the last, the chart ignores the path). yamllint's
key-duplicates rule flags exactly that, and this action ran on every
prometheus PR from 2026-08-07, green, because values.yaml sits at the root.

These tests run the action's own `run:` scripts, extracted from
action.yml, so they test what ships rather than a copy of it.
"""
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())

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


def step_script(step_id_or_name):
    """The run: script of one action step, with ${{ }} inputs substituted."""
    for step in ACTION["runs"]["steps"]:
        if step_id_or_name in (step.get("id"), step.get("name")):
            script = step["run"]
            break
    else:
        raise AssertionError(f"no step {step_id_or_name!r} in action.yml")
    subs = {
        "${{ inputs.path }}": ACTION["inputs"]["path"]["default"],
        "${{ inputs.yamllint-config }}": "",
        "${{ github.action_path }}": str(ROOT),
    }
    for expr, value in subs.items():
        script = script.replace(expr, value)
    assert "${{" not in script, f"unsubstituted expression in {step_id_or_name}"
    return script


def run_steps(workdir, *steps):
    """Run the given action steps in order, as the runner would."""
    env = dict(os.environ, GITHUB_OUTPUT=os.path.join(workdir, "gh-output"))
    for step in steps:
        r = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o",
                            "pipefail", "-c", step_script(step)],
                           cwd=workdir, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            return r
    return r


def write(workdir, rel, text):
    path = pathlib.Path(workdir, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestFileResolution(unittest.TestCase):
    def test_root_and_nested_files_are_both_listed(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "values.yaml", CLEAN)
            write(d, "networking/route.yaml", CLEAN)
            write(d, "deep/er/x.yml", CLEAN)
            r = run_steps(d, "files")
            self.assertEqual(r.returncode, 0, r.stderr)
            listed = pathlib.Path("/tmp/yaml-validate-files.txt").read_text().split()
            self.assertIn("./values.yaml", listed)
            self.assertIn("./networking/route.yaml", listed)
            self.assertIn("./deep/er/x.yml", listed)

    def test_root_only_repo_is_not_empty(self):
        # A Helm-values repo can be nothing but values.yaml at the root.
        with tempfile.TemporaryDirectory() as d:
            write(d, "values.yaml", CLEAN)
            r = run_steps(d, "files")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Found 1 YAML file(s)", r.stdout)


class TestLintsRootLevelFile(unittest.TestCase):
    def test_duplicate_keys_in_root_values_yaml_fail_the_action(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "values.yaml", DUPLICATE_RESOURCES)
            write(d, "networking/route.yaml", CLEAN)
            r = run_steps(d, "files", "yamllint")
            self.assertNotEqual(r.returncode, 0,
                                "duplicate keys in root values.yaml passed the lint")
            self.assertIn("key-duplicates", r.stdout + r.stderr)

    def test_clean_root_values_yaml_passes(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "values.yaml", CLEAN)
            write(d, "networking/route.yaml", CLEAN)
            r = run_steps(d, "files", "yamllint")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("YAMLLINT-COMPLETE", r.stdout)


if __name__ == "__main__":
    unittest.main()
