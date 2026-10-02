import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.services.settings_service import RuntimeModelConfig
from app.skills.base import SkillContext


def valid_evaluation_judgement(index=0, **overrides):
    payload = {
        "index": index,
        "business_relevance": 4,
        "executability": 4,
        "verifiability": 4,
        "scenario_completeness": 4,
        "boundary_awareness": 4,
        "coverage_reasonableness": 4,
        "reason": "覆盖核心场景",
        "issue_tags": [],
        "golden_alignment": "",
    }
    payload.update(overrides)
    return payload


class EvaluationJudgeSchemaTests(unittest.TestCase):
    def test_missing_dimension_is_rejected_instead_of_defaulted(self):
        from app.ai.schemas import EvaluationCaseJudgement

        payload = valid_evaluation_judgement()
        payload.pop("boundary_awareness")

        with self.assertRaises(ValidationError):
            EvaluationCaseJudgement.model_validate(payload)

    def test_unknown_dimension_is_rejected(self):
        from app.ai.schemas import EvaluationCaseJudgement

        with self.assertRaises(ValidationError):
            EvaluationCaseJudgement.model_validate(valid_evaluation_judgement(unknown_dimension=5))

    def test_non_integer_and_out_of_range_scores_are_rejected(self):
        from app.ai.schemas import EvaluationCaseJudgement

        for value in (3.5, 0, 6, "4"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                EvaluationCaseJudgement.model_validate(
                    valid_evaluation_judgement(business_relevance=value)
                )

    def test_empty_judgement_batch_is_rejected(self):
        from app.ai.schemas import EvaluationCaseJudgementBatch

        with self.assertRaises(ValidationError):
            EvaluationCaseJudgementBatch.model_validate({"judgements": []})


class EvaluationCaseJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluation_mode_returns_six_integer_dimensions_in_mock_mode(self):
        from app.skills.case_judge.handler import EVALUATION_DIMENSIONS, EVALUATION_PROMPT_VERSION, run

        result = await run(
            {
                "evaluation_mode": True,
                "requirement": "登录失败时提示具体原因",
                "checkpoints": [{"text": "错误密码提示", "keywords": ["密码错误"]}],
                "cases": [
                    {
                        "title": "错误密码登录",
                        "steps": ["输入错误密码后点击登录按钮"],
                        "expected_result": "页面显示密码错误提示",
                    }
                ],
            },
            SkillContext(model_config=RuntimeModelConfig(llm_mock_mode=True), use_mock=True),
        )

        judgement = result["judgements"][0]
        self.assertEqual(set(judgement["dimensions"]), set(EVALUATION_DIMENSIONS))
        self.assertTrue(
            all(isinstance(value, int) and 1 <= value <= 5 for value in judgement["dimensions"].values())
        )
        self.assertEqual(result["prompt_version"], EVALUATION_PROMPT_VERSION)

    async def test_legacy_mode_keeps_existing_three_dimension_output(self):
        from app.skills.case_judge.handler import run

        result = await run(
            {"feature_item": {"feature": "登录"}, "cases": [{"title": "正常登录"}]},
            SkillContext(model_config=RuntimeModelConfig(llm_mock_mode=True), use_mock=True),
        )

        judgement = result["judgements"][0]
        self.assertIn("overall", judgement)
        self.assertIn("relevance", judgement)
        self.assertNotIn("dimensions", judgement)

    async def test_skill_registry_accepts_the_evaluation_mode_output_contract(self):
        from app.skills.registry import get_registry

        result = await get_registry().run(
            "case_judge",
            {
                "evaluation_mode": True,
                "requirement": "登录失败时提示原因",
                "checkpoints": [],
                "cases": [{"title": "错误密码", "steps": ["输入错误密码并登录"], "expected_result": "提示密码错误"}],
            },
            SkillContext(model_config=RuntimeModelConfig(llm_mock_mode=True), use_mock=True),
        )

        self.assertEqual(result["prompt_version"], "p1-2b-judge-v1")
        self.assertIn("dimensions", result["judgements"][0])

    async def test_evaluation_mode_rejects_partial_judge_batch(self):
        from app.skills.case_judge.handler import EvaluationJudgeContractError, run

        cases = [{"title": "用例一"}, {"title": "用例二"}]
        with patch(
            "app.skills.case_judge.handler.judge_evaluation_cases",
            new=AsyncMock(return_value=[valid_evaluation_judgement(0)]),
        ):
            with self.assertRaises(EvaluationJudgeContractError):
                await run(
                    {"evaluation_mode": True, "cases": cases},
                    SkillContext(model_config=RuntimeModelConfig(), use_mock=False),
                )

    async def test_evaluation_mode_rejects_duplicate_and_out_of_range_indexes(self):
        from app.skills.case_judge.handler import EvaluationJudgeContractError, run

        invalid_batches = (
            [valid_evaluation_judgement(0), valid_evaluation_judgement(0)],
            [valid_evaluation_judgement(0), valid_evaluation_judgement(2)],
        )
        for batch in invalid_batches:
            with self.subTest(batch=batch), patch(
                "app.skills.case_judge.handler.judge_evaluation_cases",
                new=AsyncMock(return_value=batch),
            ):
                with self.assertRaises(EvaluationJudgeContractError):
                    await run(
                        {"evaluation_mode": True, "cases": [{"title": "一"}, {"title": "二"}]},
                        SkillContext(model_config=RuntimeModelConfig(), use_mock=False),
                    )

    async def test_contract_error_identifies_the_missing_dimension_for_directed_retry(self):
        from app.skills.case_judge.handler import EvaluationJudgeContractError, run

        partial = valid_evaluation_judgement(0)
        partial.pop("boundary_awareness")
        with patch(
            "app.skills.case_judge.handler.judge_evaluation_cases",
            new=AsyncMock(return_value=[partial]),
        ):
            with self.assertRaises(EvaluationJudgeContractError) as caught:
                await run(
                    {"evaluation_mode": True, "cases": [{"title": "一"}]},
                    SkillContext(model_config=RuntimeModelConfig(), use_mock=False),
                )

        self.assertIn("boundary_awareness", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
