import unittest

from app.workflows.generation.graph import build_generation_graph
from app.workflows.generation.nodes import (
    final_task_status,
    route_after_generation,
    route_after_validation,
    route_next_feature,
)
from app.workflows.generation.runner import generation_recursion_limit


class GenerationGraphRoutingTests(unittest.TestCase):
    def test_graph_contains_expected_nodes(self):
        nodes = set(build_generation_graph().get_graph().nodes)
        self.assertTrue(
            {
                "load_task",
                "retrieve_knowledge",
                "generate_core_cases",
                "generate_specialist_cases",
                "validate_cases",
                "record_feature_failure",
                "detect_duplicates",
                "run_judge",
                "build_report",
                "finalize_task",
            }.issubset(nodes)
        )

    def test_recoverable_structured_error_routes_to_retry_node(self):
        state = {
            "generation_error": "invalid json",
            "failure_decision": {"recoverable": True},
        }
        self.assertEqual(route_after_generation(state), "retry")

    def test_final_structured_error_routes_to_feature_failure_without_stopping_task(self):
        state = {
            "generation_error": "invalid json",
            "failure_decision": {"recoverable": False},
        }
        self.assertEqual(route_after_generation(state), "feature_failed")

    def test_empty_valid_cases_retries_once_then_becomes_feature_failure(self):
        self.assertEqual(route_after_validation({"current_cases": [], "retry_count": 0}), "retry")
        self.assertEqual(route_after_validation({"current_cases": [], "retry_count": 1}), "feature_failed")

    def test_final_task_with_failure_candidate_completes_with_warnings(self):
        self.assertEqual(final_task_status(True), "completed_with_warnings")
        self.assertEqual(final_task_status(False), "completed")

    def test_feature_loop_routes_to_quality_after_last_item(self):
        self.assertEqual(route_next_feature({"feature_index": 1, "feature_ids": [1, 2]}), "next")
        self.assertEqual(route_next_feature({"feature_index": 2, "feature_ids": [1, 2]}), "quality")

    def test_recursion_budget_scales_with_confirmed_features(self):
        self.assertEqual(generation_recursion_limit(0), 25)
        self.assertEqual(generation_recursion_limit(3), 32)
        self.assertEqual(generation_recursion_limit(100), 808)
        self.assertEqual(generation_recursion_limit(1000), 4096)


if __name__ == "__main__":
    unittest.main()
