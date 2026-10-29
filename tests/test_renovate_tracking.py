"""Every version pin in action.yml is one Renovate actually tracks.

    python3 -m unittest tests.test_renovate_tracking -v

action.yml pins yamllint (`YAMLLINT_VERSION=` inside a `run:` script) so the
same commit gets the same verdict on every runner. A shell variable is
invisible to Renovate's built-in managers, so the pin is tracked by a
`# renovate: datasource=... depName=...` line directly above it, read by
the regex custom manager in renovate.json. Same pattern as
dvystrcil/arc-runner-docker (homelab#1812 AC3).

The failure mode is silence, not an error: if the annotation drifts or the
regex stops matching, Renovate simply never opens another PR and the pin
sits forever. So this runs renovate.json's OWN regex against action.yml and
requires it to capture every pin, with the value actually assigned.
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACTION = (ROOT / "action.yml").read_text()
RENOVATE = json.loads((ROOT / "renovate.json").read_text())

PIN = re.compile(r"^\s*(?P<name>[A-Z0-9_]+_VERSION)=(?P<value>\S+)\s*$", re.M)


def js_to_py(pattern):
    """Renovate regexes use JS named groups; Python spells them (?P<name>)."""
    return re.sub(r"\(\?<(?=[A-Za-z])", "(?P<", pattern)


def managers_for(filename):
    out = []
    for m in RENOVATE.get("customManagers", []):
        for fp in m.get("managerFilePatterns", []):
            if re.search(fp.strip("/"), filename):
                out.append(m)
                break
    return out


def tracked(text):
    """(name of the pinned variable, groups) for every match of the managers on action.yml."""
    hits = []
    for m in managers_for("action.yml"):
        for ms in m["matchStrings"]:
            for match in re.finditer(js_to_py(ms), text):
                g = match.groupdict()
                g.setdefault("datasource", m.get("datasourceTemplate"))
                g.setdefault("depName", m.get("depNameTemplate"))
                # Which variable the captured value belongs to: the line it sits on.
                pos = match.start("currentValue")
                line = text[text.rfind("\n", 0, pos) + 1:text.find("\n", pos) % (len(text) + 1)]
                pin = PIN.match(line)
                self_check = pin and pin.group("value") == g["currentValue"]
                hits.append((pin.group("name") if self_check else "<not a *_VERSION= line>", g))
    return hits


class TestRenovateTracksPins(unittest.TestCase):
    def test_action_yml_has_a_custom_manager(self):
        self.assertTrue(managers_for("action.yml"),
                        "no customManagers entry in renovate.json covers action.yml")

    def test_yamllint_pin_is_tracked_with_its_real_value(self):
        assigned = dict(PIN.findall(ACTION))
        self.assertIn("YAMLLINT_VERSION", assigned)
        hits = {name: g for name, g in tracked(ACTION)}
        self.assertIn("YAMLLINT_VERSION", hits, "renovate.json's regex does not match the yamllint pin")
        g = hits["YAMLLINT_VERSION"]
        self.assertEqual(g["datasource"], "pypi")
        self.assertEqual(g["depName"], "yamllint")
        self.assertEqual(g["currentValue"], assigned["YAMLLINT_VERSION"])

    def test_every_version_pin_is_tracked(self):
        # Enumerate ALL pins, not just annotated ones: a new *_VERSION= added
        # without the annotation is exactly the pin nobody would ever bump.
        assigned = {name for name, _ in PIN.findall(ACTION)}
        self.assertTrue(assigned, "found no *_VERSION= pins; the PIN pattern no longer fits action.yml")
        self.assertEqual(assigned, {name for name, _ in tracked(ACTION)})

    def test_regex_rejects_an_unannotated_pin(self):
        # Guards against a regex so loose this test could never fail.
        bare = "      run: |\n        YAMLLINT_VERSION=1.0.0\n"
        self.assertEqual(tracked(bare), [])


if __name__ == "__main__":
    unittest.main()
