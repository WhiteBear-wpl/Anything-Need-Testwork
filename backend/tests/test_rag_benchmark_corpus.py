import unittest
from collections import Counter
from pathlib import Path

from benchmarks.rag.corpus import build_corpus
from benchmarks.rag.schema import load_dataset


BENCHMARK_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "rag"
KNOWLEDGE_DIR = BENCHMARK_DIR / "knowledge"
DATASET_PATH = BENCHMARK_DIR / "dataset.json"


class BenchmarkCorpusTests(unittest.TestCase):
    """These tests catch a benchmark that silently diverges from production chunking or labels."""

    def test_corpus_is_built_from_all_traceable_documents(self):
        chunks = build_corpus(KNOWLEDGE_DIR)

        self.assertEqual(
            {chunk.document for chunk in chunks},
            {
                "requirement-import",
                "knowledge-base",
                "generation-flow",
                "review-and-storage",
                "error-and-security",
                "test-quality",
            },
        )
        self.assertTrue(chunks)
        self.assertTrue(all("#" not in chunk.heading for chunk in chunks))
        self.assertTrue(all("#" in chunk.chunk_id for chunk in chunks))

    def test_dataset_has_required_query_mix_and_valid_gold_chunks(self):
        chunks = build_corpus(KNOWLEDGE_DIR)
        dataset = load_dataset(DATASET_PATH, {chunk.chunk_id for chunk in chunks})

        self.assertEqual(len(dataset.queries), 50)
        self.assertEqual(
            Counter(query.category for query in dataset.queries),
            {"semantic": 16, "exact": 12, "composite": 12, "distractor": 5, "no_answer": 5},
        )
        self.assertTrue(all(query.notes for query in dataset.queries))
        self.assertTrue(all(query.gold_relevance for query in dataset.queries if query.category != "no_answer"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
