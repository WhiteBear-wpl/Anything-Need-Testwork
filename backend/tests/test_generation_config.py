import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.generation import GenerationTask
from app.services.generation_service import (
    build_strategy_config,
    build_strategy_config_payload,
    parse_strategy_config,
)
from app.services.settings_service import RuntimeModelConfig


class GenerationConfigSnapshotTests(unittest.TestCase):
    def test_snapshot_contains_reproducibility_fields_without_api_keys(self):
        data = SimpleNamespace(
            strategy="quick",
            specialist_skills=["security"],
            use_knowledge=True,
        )
        model_config = RuntimeModelConfig(
            llm_api_key="generation-secret",
            llm_base_url="https://api.openai.com/v1",
            llm_model="generation-model",
            eval_llm_api_key="evaluation-secret",
            eval_llm_base_url="https://api.openai.com/v1",
            eval_llm_model="evaluation-model",
            embedding_api_key="embedding-secret",
            embedding_model="embedding-model",
        )

        raw = build_strategy_config_payload(data, model_config)
        snapshot = json.loads(raw)

        self.assertEqual(snapshot["workflow_version"], "langgraph-v1")
        self.assertEqual(snapshot["strategy"], "quick")
        self.assertEqual(snapshot["specialist_skills"], ["security"])
        self.assertTrue(snapshot["use_knowledge"])
        self.assertIn("case_writer", snapshot["skill_versions"])
        self.assertIn("case_writer", snapshot["prompt_fingerprints"])
        self.assertEqual(snapshot["generation_parameters"]["temperature"], 0.3)
        self.assertEqual(snapshot["models"]["generation"]["model"], "generation-model")
        self.assertEqual(snapshot["retrieval"]["mode"], "vector_bm25_rrf_optional_rerank")
        self.assertEqual(snapshot["retrieval"]["embedding_adapter"], "langchain_openai")
        self.assertEqual(snapshot["retrieval"]["vector_store"], "langchain_chroma")
        self.assertEqual(snapshot["retrieval"]["collection_version"], "lc_v1")
        self.assertNotIn("generation-secret", raw)
        self.assertNotIn("evaluation-secret", raw)
        self.assertNotIn("embedding-secret", raw)

    def test_strict_write_rejects_unknown_but_historical_read_filters_it(self):
        with self.assertRaisesRegex(ValueError, "future_specialist"):
            build_strategy_config(
                strategy="full",
                specialist_skills=["future_specialist"],
                strict_specialists=True,
            )

        task = GenerationTask(
            strategy="full",
            strategy_config=(
                '{"strategy":"full","specialist_skills":'
                '["future_specialist","security"]}'
            ),
        )
        self.assertEqual(parse_strategy_config(task)["specialist_skills"], ["security"])

    def test_eval_generation_nodes_use_frozen_models_rag_and_specialists(self):
        from app.services.evaluation_experiment_service import build_experiment_snapshot
        from app.skills.registry import get_registry
        from app.workflows.generation.nodes import _runtime_model_config

        snapshot = build_experiment_snapshot(
            get_registry(),
            RuntimeModelConfig(
                llm_api_key="initial-secret",
                llm_base_url="https://frozen.example/v1",
                llm_model="frozen-model",
            ),
            {
                "strategy": "full",
                "use_knowledge": True,
                "specialists": [
                    {"skill_name": "security", "enabled": True, "prompt_version": "v2"}
                ],
            },
        )
        task = GenerationTask(
            project_id=1,
            strategy="full",
            strategy_config=json.dumps(snapshot),
            is_eval=True,
        )
        changed_live = RuntimeModelConfig(
            llm_api_key="rotated-secret",
            llm_base_url="https://changed.example/v1",
            llm_model="changed-model",
        )
        with patch(
            "app.workflows.generation.nodes.get_project_runtime_config",
            return_value=changed_live,
        ):
            resolved = _runtime_model_config(None, task)

        self.assertEqual(resolved.llm_api_key, "rotated-secret")
        self.assertEqual(resolved.llm_base_url, "https://frozen.example/v1")
        self.assertEqual(resolved.llm_model, "frozen-model")
        parsed = json.loads(task.strategy_config)
        self.assertTrue(parsed["use_knowledge"])
        self.assertEqual(parsed["specialist_skills"], ["security"])

    def test_eval_snapshot_rejects_changed_skill_version_or_prompt_fingerprint(self):
        from app.services.evaluation_experiment_service import (
            build_experiment_snapshot,
            runtime_config_from_snapshot,
        )
        from app.skills.registry import get_registry

        runtime = RuntimeModelConfig(llm_mock_mode=True)
        snapshot = build_experiment_snapshot(
            get_registry(), runtime, {"strategy": "full"}
        )
        snapshot["skill_versions"]["case_writer"] = "removed-version"
        with self.assertRaisesRegex(ValueError, "frozen Skill version is unavailable"):
            runtime_config_from_snapshot(snapshot, runtime)

        snapshot = build_experiment_snapshot(
            get_registry(), runtime, {"strategy": "full"}
        )
        snapshot["prompt_fingerprints"]["case_writer"] = "removed-prompt"
        with self.assertRaisesRegex(ValueError, "frozen Skill prompt is unavailable"):
            runtime_config_from_snapshot(snapshot, runtime)

    def test_generation_node_config_preserves_frozen_retrieval_parameters(self):
        from app.services.evaluation_experiment_service import build_experiment_snapshot
        from app.skills.registry import get_registry
        from app.workflows.generation.nodes import _strategy_config

        snapshot = build_experiment_snapshot(
            get_registry(), RuntimeModelConfig(llm_mock_mode=True), {"strategy": "full"}
        )
        snapshot["retrieval"].update(
            {"top_k": 7, "recall_top_k": 13, "similarity_threshold": 0.42, "rrf_k": 17}
        )
        task = GenerationTask(
            strategy="full",
            strategy_config=json.dumps(snapshot),
            is_eval=True,
        )

        self.assertEqual(
            _strategy_config(task)["retrieval"],
            {"top_k": 7, "recall_top_k": 13, "similarity_threshold": 0.42, "rrf_k": 17},
        )


class RetrieverSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_retriever_forwards_frozen_retrieval_parameters(self):
        from app.ai.retrievers import AITCHybridRetriever

        with patch("app.ai.retrievers.retrieve", new_callable=AsyncMock) as retrieve:
            retrieve.return_value = []
            retriever = AITCHybridRetriever(
                db=object(),
                project_id=9,
                top_k=7,
                recall_top_k=13,
                threshold=0.42,
                rrf_k=17,
            )
            await retriever.ainvoke("登录")

        self.assertEqual(retrieve.await_args.kwargs["top_k"], 7)
        self.assertEqual(retrieve.await_args.kwargs["recall_top_k"], 13)
        self.assertEqual(retrieve.await_args.kwargs["threshold"], 0.42)
        self.assertEqual(retrieve.await_args.kwargs["rrf_k"], 17)


if __name__ == "__main__":
    unittest.main()
