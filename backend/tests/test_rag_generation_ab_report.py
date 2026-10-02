import unittest

from benchmarks.rag_generation_ab.report import (
    render_ab_report,
    render_interview_report,
    validate_pair,
)


class ABReportTests(unittest.TestCase):
    def test_accepts_matched_pair_with_treatment_references(self):
        baseline = {"sample_fingerprint": "same", "config": {"strategy": "full", "use_knowledge": False}, "metrics": {"recall": 50.0, "usable_rate": 70.0}}
        treatment = {"sample_fingerprint": "same", "config": {"strategy": "full", "use_knowledge": True}, "metrics": {"recall": 80.0, "usable_rate": 80.0}, "knowledge_refs": {"1": [{"title": "补充规则"}]}}
        self.assertEqual(validate_pair(baseline, treatment), [])
        report = render_ab_report(baseline, treatment)
        self.assertIn("单次探索性", report)
        self.assertIn("+30.0", report)

    def test_rejects_changed_strategy_or_missing_treatment_evidence(self):
        baseline = {"sample_fingerprint": "same", "config": {"strategy": "full", "use_knowledge": False}, "metrics": {}}
        treatment = {"sample_fingerprint": "same", "config": {"strategy": "quick", "use_knowledge": True}, "metrics": {}, "knowledge_refs": {}}
        errors = validate_pair(baseline, treatment)
        self.assertTrue(any("strategy" in error for error in errors))
        self.assertTrue(any("knowledge_refs" in error for error in errors))

    def test_interview_report_explains_tradeoffs_and_limitations(self):
        baseline = {
            "sample_fingerprint": "same",
            "config": {"strategy": "full", "use_knowledge": False},
            "metrics": {"recall": 83.3, "usable_rate": 63.4, "hallucination_count": 5, "total_tokens": 70682, "total_duration_sec": 1694.8},
            "knowledge_refs": {},
        }
        treatment = {
            "sample_fingerprint": "same",
            "config": {"strategy": "full", "use_knowledge": True},
            "metrics": {"recall": 100.0, "usable_rate": 50.0, "hallucination_count": 16, "total_tokens": 92205, "total_duration_sec": 2005.1},
            "knowledge_refs": {"4": {"17": [{"match": "both", "score": 0.606}]}},
        }

        report = render_interview_report(baseline, treatment)

        self.assertIn("+16.7", report)
        self.assertIn("-13.4", report)
        self.assertIn("不能表述为", report)
        self.assertIn("面试回答", report)


if __name__ == "__main__":
    unittest.main()
