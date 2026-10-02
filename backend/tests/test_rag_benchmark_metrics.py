import math
import unittest

from benchmarks.rag.metrics import RetrievalObservation, score_query, summarize_strategy
from benchmarks.rag.schema import BenchmarkQuery


class BenchmarkMetricTests(unittest.TestCase):
    """These tests catch ranking gains being reported with an incorrect denominator or rank."""

    def test_score_uses_first_relevant_rank_and_graded_ndcg(self):
        query = BenchmarkQuery(
            query_id="q01",
            query="退款规则",
            category="semantic",
            gold_relevance={"a": 3, "b": 2},
            notes="fixture",
        )

        score = score_query(query, ["x", "b", "a"], k=3)

        self.assertEqual(score.recall_at_k, 1.0)
        self.assertEqual(score.mrr_at_k, 0.5)
        expected_ndcg = (3 / math.log2(3) + 7 / math.log2(4)) / (7 + 3 / math.log2(3))
        self.assertAlmostEqual(score.ndcg_at_k, expected_ndcg)
        self.assertFalse(score.no_answer_false_positive)

    def test_no_answer_result_is_counted_as_false_positive(self):
        query = BenchmarkQuery("q46", "不存在规则", "no_answer", {}, "fixture")

        score = score_query(query, ["a"], k=5)

        self.assertTrue(score.no_answer_false_positive)
        self.assertEqual(score.recall_at_k, 0.0)

    def test_summary_separates_unavailable_runs_from_quality_scores(self):
        answer = BenchmarkQuery("q01", "退款", "semantic", {"a": 3}, "fixture")
        no_answer = BenchmarkQuery("q46", "不存在", "no_answer", {}, "fixture")
        summary = summarize_strategy(
            [
                RetrievalObservation(answer, ["a"], 10.0, "completed"),
                RetrievalObservation(no_answer, ["x"], 20.0, "completed"),
                RetrievalObservation(answer, [], 30.0, "not_executed"),
            ],
            top_ks=(1, 5),
        )

        self.assertEqual(summary.query_count, 3)
        self.assertAlmostEqual(summary.availability, 2 / 3)
        self.assertEqual(summary.p95_latency_ms, 30.0)
        self.assertEqual(summary.metrics_by_k[1]["recall"], 1.0)
        self.assertEqual(summary.metrics_by_k[1]["no_answer_false_positive_rate"], 1.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
