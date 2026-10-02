import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage

from app.ai.chains import (
    generate_cases,
    judge_cases,
    judge_checkpoint_coverage,
    parse_requirement_items,
)
from app.services.llm import start_token_tracking, total_tokens
from app.services.settings_service import RuntimeModelConfig


class LangChainStructuredOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = RuntimeModelConfig(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="test-model",
        )

    @patch("app.ai.chains.create_chat_model")
    async def test_generate_cases_returns_existing_skill_contract(self, create_model):
        model = AsyncMock()
        model.http_async_client = AsyncMock()
        model.ainvoke.return_value = AIMessage(
            content='[{"title":"正确登录","priority":"P0","case_type":"functional",'
            '"is_smoke":true,"precondition":"已有账号","steps":["输入账号密码","点击登录"],'
            '"expected_result":"进入首页"}]',
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )
        create_model.return_value = model
        counter = start_token_tracking()

        result = await generate_cases("system", "user", "case_writer", self.config)

        self.assertEqual(result[0]["skill_name"], "case_writer")
        self.assertEqual(result[0]["steps"], ["输入账号密码", "点击登录"])
        self.assertTrue(result[0]["is_smoke"])
        self.assertEqual(total_tokens(counter), 30)
        model.http_async_client.aclose.assert_awaited_once()

    @patch("app.ai.chains.create_chat_model")
    async def test_requirement_parser_accepts_root_array(self, create_model):
        model = AsyncMock()
        model.ainvoke.return_value = AIMessage(
            content='[{"module":"登录","feature":"账号密码登录","priority":"P0"}]'
        )
        create_model.return_value = model

        result = await parse_requirement_items("system", "raw", self.config)

        self.assertEqual(result[0]["module"], "登录")
        self.assertEqual(result[0]["feature"], "账号密码登录")

    @patch("app.ai.chains.create_chat_model")
    async def test_judge_uses_evaluation_purpose(self, create_model):
        model = AsyncMock()
        model.ainvoke.return_value = AIMessage(
            content='{"judgements":[{"index":0,"relevance":5,"executability":4,'
            '"verifiability":5,"hallucination":false}]}'
        )
        create_model.return_value = model

        result = await judge_cases("system", "user", self.config)

        self.assertEqual(result[0]["relevance"], 5)
        create_model.assert_called_once_with(self.config, "evaluation")

    @patch("app.ai.chains.create_chat_model")
    async def test_invalid_json_is_visible_to_graph_for_retry(self, create_model):
        model = AsyncMock()
        model.ainvoke.return_value = AIMessage(content="not-json")
        create_model.return_value = model

        with self.assertRaises(OutputParserException):
            await generate_cases("system", "user", "case_writer", self.config)

    @patch("app.ai.chains.create_chat_model")
    async def test_coverage_judge_uses_structured_evaluation_chain(self, create_model):
        model = AsyncMock()
        model.ainvoke.return_value = AIMessage(content='{"covered_indexes":[0,2]}')
        create_model.return_value = model

        result = await judge_checkpoint_coverage("system", "user", self.config)

        self.assertEqual(result, [0, 2])
        create_model.assert_called_once_with(self.config, "evaluation")


if __name__ == "__main__":
    unittest.main()
