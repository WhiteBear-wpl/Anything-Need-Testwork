import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.rag.corpus import CorpusChunk
from benchmarks.rag.runner import run_benchmark
from benchmarks.rag.schema import BenchmarkDataset, BenchmarkQuery
from app.services.settings_service import RuntimeModelConfig


async def fake_vector(_query, _top_n):
    return [("a#01", 0.9)]


class BenchmarkRunnerTests(unittest.TestCase):
    def test_runner_writes_three_round_raw_artifact(self):
        root = Path(__file__).resolve().parents[2] / ".aitc-temp"
        with tempfile.TemporaryDirectory(dir=root) as directory:
            dataset = BenchmarkDataset(1, (BenchmarkQuery("q01", "退款", "semantic", {"a#01": 3}, "fixture"),))
            artifact = asyncio.run(run_benchmark(dataset, [CorpusChunk("a#01", "doc", "h", "退款规则")], RuntimeModelConfig(), Path(directory), vector_search=fake_vector))
            self.assertTrue(artifact["dataset_sha256"])
            self.assertEqual(len(artifact["queries"]), 12)
            self.assertTrue((Path(directory) / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
