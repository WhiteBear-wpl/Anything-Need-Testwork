import unittest

from benchmarks.rag_generation_ab.dataset import load_samples


class ABDataSetTests(unittest.TestCase):
    def test_has_two_samples_with_supplemental_nonduplicative_knowledge(self):
        samples = load_samples()

        self.assertEqual(len(samples), 2)
        self.assertTrue(all(sample.checkpoints for sample in samples))
        for sample in samples:
            knowledge = sample.knowledge_path.read_text(encoding="utf-8")
            self.assertNotIn(sample.requirement, knowledge)
            self.assertIn("source_note:", knowledge)


if __name__ == "__main__":
    unittest.main()
