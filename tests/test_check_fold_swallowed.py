import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import check_fold_swallowed as checker  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    return os.path.join(FIXTURES, name)


class TestFoldSwallowedDetection(unittest.TestCase):
    def test_flags_the_actual_incident_shape(self):
        findings = checker.check_file(fixture("bad_swallowed_directive.yaml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["swallowed"], "trustedReverseProxy=uniquelocal")

    def test_clean_when_blank_line_separates_comment_from_directive(self):
        findings = checker.check_file(fixture("good_blank_line_separated.yaml"))
        self.assertEqual(findings, [])

    def test_no_false_positive_on_prose_mentioning_equals_sign(self):
        # Comments that reference example settings, URLs with query
        # params, or setting names inline must not trip the check --
        # only a genuinely swallowed standalone directive should.
        findings = checker.check_file(
            fixture("prose_mentions_equals_but_separated.yaml")
        )
        self.assertEqual(findings, [])

    def test_literal_scalar_never_flagged(self):
        # `|` preserves newlines exactly; the bug class is specific to
        # `>` folding and cannot occur in a literal block.
        findings = checker.check_file(fixture("literal_scalar_unaffected.yaml"))
        self.assertEqual(findings, [])

    def test_comment_only_block_is_clean(self):
        findings = checker.check_file(fixture("comment_only_no_directive.yaml"))
        self.assertEqual(findings, [])

    def test_no_false_positive_on_wrapped_prose_continuation(self):
        # Trilium's own upstream config.ini convention: a comment
        # paragraph's continuation lines have no leading `#`, relying on
        # folding to join them into one valid comment line. This is a
        # legitimate, intentional pattern and must not be flagged.
        findings = checker.check_file(
            fixture("wrapped_prose_continuation_not_flagged.yaml")
        )
        self.assertEqual(findings, [])

    def test_exit_code_nonzero_when_findings_exist(self):
        rc = checker.main([fixture("bad_swallowed_directive.yaml")])
        self.assertEqual(rc, 1)

    def test_exit_code_zero_when_clean(self):
        rc = checker.main([fixture("good_blank_line_separated.yaml")])
        self.assertEqual(rc, 0)

    def test_multiple_files_aggregate_findings(self):
        rc = checker.main(
            [
                fixture("bad_swallowed_directive.yaml"),
                fixture("good_blank_line_separated.yaml"),
            ]
        )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
