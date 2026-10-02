import asyncio
import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.evaluation import EvalResult, EvalRun, EvalSample
from app.models.project import Project
from app.models.user import User


class EvaluationExperimentServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.db = sessionmaker(bind=self.engine)()
        Base.metadata.create_all(self.engine)
        user = User(username="experiment-owner", password_hash="hash")
        self.db.add(user)
        self.db.flush()
        self.project = Project(user_id=user.id, name="experiments", is_eval=True)
        self.db.add(self.project)
        self.db.flush()
        self.sample = EvalSample(project_id=self.project.id, title="登录", content="需求", checkpoints='[{"text":"失败"}]')
        self.run = EvalRun(project_id=self.project.id, label="baseline", status="completed")
        self.db.add_all([self.sample, self.run])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_freezing_samples_creates_a_stable_fingerprint(self):
        from app.services.evaluation_experiment_service import freeze_run_samples

        _, first = freeze_run_samples(self.run, [self.sample])
        self.sample.content = "修改后的需求"
        _, second = freeze_run_samples(self.run, [self.sample])

        self.assertNotEqual(first, second)

    def test_experiment_snapshot_masks_credentials_and_freezes_prompt_version(self):
        from app.services.evaluation_experiment_service import build_experiment_snapshot
        from app.services.settings_service import RuntimeModelConfig
        from app.skills.registry import get_registry

        snapshot = build_experiment_snapshot(
            get_registry(),
            RuntimeModelConfig(
                llm_api_key="secret",
                llm_base_url="https://initial.example/v1",
                llm_model="current",
            ),
            {"strategy": "full", "use_knowledge": False, "generation_model": "candidate", "evaluation_model": "candidate-eval", "specialists": [
                {"skill_name": "security", "enabled": True, "prompt_version": "v2"},
            ]},
        )
        self.assertEqual(snapshot["models"]["generation"]["model"], "candidate")
        self.assertEqual(snapshot["models"]["evaluation"]["model"], "candidate-eval")
        self.assertEqual(snapshot["skill_policy"]["specialists"]["security"]["prompt_version"], "v2")
        self.assertEqual(snapshot["evaluation_integrity_version"], 1)
        self.assertEqual(snapshot["ruleset_version"], "p1-2b-rules-v1")
        self.assertEqual(snapshot["judge_prompt_version"], "p1-2b-judge-v1")
        self.assertNotIn("secret", str(snapshot))

    def test_experiment_snapshot_rejects_base_url_credentials(self):
        from app.services.evaluation_experiment_service import build_experiment_snapshot
        from app.services.settings_service import RuntimeModelConfig
        from app.skills.registry import get_registry

        with self.assertRaisesRegex(ValueError, "URL credentials"):
            build_experiment_snapshot(
                get_registry(),
                RuntimeModelConfig(
                    llm_mock_mode=True,
                    llm_base_url="https://user:password@example.test/v1",
                ),
                {"strategy": "full"},
            )

    def test_runtime_config_uses_frozen_models_and_live_secrets_only(self):
        from app.services.evaluation_experiment_service import (
            build_experiment_snapshot,
            runtime_config_from_snapshot,
        )
        from app.services.settings_service import RuntimeModelConfig
        from app.skills.registry import get_registry

        snapshot = build_experiment_snapshot(
            get_registry(),
            RuntimeModelConfig(
                llm_api_key="old-secret",
                llm_base_url="https://frozen.example/v1",
                llm_model="frozen-model",
            ),
            {
                "strategy": "full",
                "generation_model": "candidate-generation",
                "evaluation_model": "candidate-evaluation",
            },
        )
        resolved = runtime_config_from_snapshot(
            snapshot,
            RuntimeModelConfig(
                llm_api_key="rotated-secret",
                llm_base_url="https://changed.example/v1",
                llm_model="changed-model",
            ),
        )

        self.assertEqual(resolved.llm_api_key, "rotated-secret")
        self.assertEqual(resolved.llm_base_url, "https://frozen.example/v1")
        self.assertEqual(resolved.llm_model, "candidate-generation")
        self.assertEqual(resolved.eval_llm_api_key, "rotated-secret")
        self.assertEqual(resolved.eval_llm_base_url, "https://frozen.example/v1")
        self.assertEqual(resolved.eval_llm_model, "candidate-evaluation")

    def test_incomplete_historical_snapshot_is_rejected_without_live_fallback(self):
        from app.services.evaluation_experiment_service import runtime_config_from_snapshot
        from app.services.settings_service import RuntimeModelConfig

        with self.assertRaisesRegex(ValueError, "incomplete immutable config snapshot"):
            runtime_config_from_snapshot(
                {"strategy": "full"},
                RuntimeModelConfig(llm_api_key="secret", llm_model="live-model"),
            )

    def test_unavailable_frozen_ruleset_or_judge_prompt_version_is_rejected(self):
        from app.services.evaluation_experiment_service import (
            build_experiment_snapshot,
            runtime_config_from_snapshot,
        )
        from app.services.settings_service import RuntimeModelConfig
        from app.skills.registry import get_registry

        runtime = RuntimeModelConfig(llm_mock_mode=True)
        snapshot = build_experiment_snapshot(
            get_registry(), runtime, {"strategy": "full"}
        )
        snapshot["judge_prompt_version"] = "removed-judge-prompt"
        with self.assertRaisesRegex(ValueError, "frozen Judge Prompt version is unavailable"):
            runtime_config_from_snapshot(snapshot, runtime)

        snapshot["judge_prompt_version"] = "p1-2b-judge-v1"
        snapshot["ruleset_version"] = "removed-ruleset"
        with self.assertRaisesRegex(ValueError, "frozen Ruleset version is unavailable"):
            runtime_config_from_snapshot(snapshot, runtime)

    def test_incomplete_run_snapshot_is_persisted_as_failed(self):
        from app.services.evaluation_service import run_evaluation

        self.run.status = "pending"
        self.run.config_snapshot = "{}"
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "incomplete immutable config snapshot"):
            asyncio.run(run_evaluation(self.db, self.run.id))

        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "failed")
        self.assertIn("incomplete immutable config snapshot", self.run.error_message)

    def test_missing_frozen_sample_is_rejected_without_live_sample_fallback(self):
        from app.services.evaluation_experiment_service import build_experiment_snapshot
        from app.services.evaluation_service import run_evaluation
        from app.services.settings_service import RuntimeModelConfig
        from app.skills.registry import get_registry

        snapshot = build_experiment_snapshot(
            get_registry(), RuntimeModelConfig(llm_mock_mode=True), {"strategy": "full"}
        )
        self.run.status = "pending"
        self.run.config_snapshot = json.dumps(snapshot)
        self.db.add(EvalResult(run_id=self.run.id, sample_id=self.sample.id))
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "immutable sample snapshot"):
            asyncio.run(run_evaluation(self.db, self.run.id))

        self.db.refresh(self.run)
        self.assertEqual(self.run.status, "failed")

    def test_only_same_sample_set_runs_are_comparable_and_baseline_is_unique(self):
        from app.services.evaluation_experiment_service import compare_runs, set_run_baseline

        same = EvalRun(project_id=self.project.id, label="candidate", status="completed", sample_set_fingerprint="same")
        other = EvalRun(project_id=self.project.id, label="other", status="completed", sample_set_fingerprint="other")
        self.run.sample_set_fingerprint = "same"
        self.db.add_all([same, other])
        self.db.commit()

        comparison = compare_runs([self.run, other])
        self.assertFalse(comparison["comparable"])
        set_run_baseline(self.db, self.run)
        set_run_baseline(self.db, same)
        self.assertEqual(
            self.db.query(EvalRun).filter(EvalRun.sample_set_fingerprint == "same", EvalRun.is_baseline == True).count(),
            1,
        )


if __name__ == "__main__":
    unittest.main()
