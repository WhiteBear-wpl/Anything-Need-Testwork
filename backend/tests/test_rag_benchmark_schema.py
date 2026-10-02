import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.rag.schema import load_dataset


class BenchmarkDatasetSchemaTests(unittest.TestCase):
    """These tests catch malformed gold labels being scored as valid evidence."""

    def _write_dataset(self, payload: dict) -> Path:
        workspace_temp = Path(__file__).resolve().parents[2] / ".aitc-temp"
        workspace_temp.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=workspace_temp)
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "dataset.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_rejects_gold_chunk_not_present_in_corpus(self):
        path = self._write_dataset(
            {
                "version": 1,
                "queries": [
                    {
                        "query_id": "q01",
                        "query": "退款规则",
                        "category": "semantic",
                        "gold_relevance": {"missing#01": 3},
                        "notes": "test fixture",
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "unknown gold chunk"):
            load_dataset(path, available_chunk_ids={"refund#01"})

    def test_rejects_no_answer_query_with_gold_evidence(self):
        path = self._write_dataset(
            {
                "version": 1,
                "queries": [
                    {
                        "query_id": "q01",
                        "query": "不存在的规则",
                        "category": "no_answer",
                        "gold_relevance": {"refund#01": 3},
                        "notes": "test fixture",
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "no_answer"):
            load_dataset(path, available_chunk_ids={"refund#01"})

    def test_accepts_graded_relevance_for_known_chunks(self):
        path = self._write_dataset(
            {
                "version": 1,
                "queries": [
                    {
                        "query_id": "q01",
                        "query": "退款规则",
                        "category": "semantic",
                        "gold_relevance": {"refund#01": 3, "refund#02": 2},
                        "notes": "test fixture",
                    }
                ],
            }
        )

        dataset = load_dataset(path, available_chunk_ids={"refund#01", "refund#02"})

        self.assertEqual(dataset.version, 1)
        self.assertEqual(dataset.queries[0].gold_relevance, {"refund#01": 3, "refund#02": 2})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
