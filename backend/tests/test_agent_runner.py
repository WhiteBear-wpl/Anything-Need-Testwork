"""测试助手 runner 单测：Mock 模式事件序列与历史消息裁剪。"""

import asyncio
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent.memory import estimate_tokens, maybe_update_summary, select_context
from app.agent_runtime.contracts import BudgetExhausted, ExecutionBudget, RunContext
from app.agent_runtime.harness import RuntimeHarness
from app.agent.runner import (
    HISTORY_LIMIT,
    _build_agent_graph,
    _history_messages,
    _is_agent_model_stream,
    run_agent,
)
from app.database import Base
from app.models.agent import AgentMessage, AgentThread
from app.models.agent_run import AgentRun
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.testcase import TestCase
from app.services.settings_service import RuntimeModelConfig


async def _collect(iterator) -> list[dict]:
    return [event async for event in iterator]


class MockModeRunnerTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(TestCase(project_id=1, title="用例A", expected_result="ok"))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_mock_event_sequence(self):
        # 默认 RuntimeModelConfig 无 API Key，use_mock_llm 为 True
        events = asyncio.run(_collect(run_agent(
            self.db, 1, "演示项目", "通过率怎么样", [], RuntimeModelConfig(),
        )))

        types = [e["type"] for e in events]
        self.assertEqual(types[0], "tool_start")
        self.assertEqual(events[0]["name"], "search_knowledge")
        self.assertEqual(types[1], "tool_end")
        self.assertIn("token", types)
        self.assertEqual(types[-1], "done")

        done = events[-1]
        self.assertIn("Mock 模式", done["content"])
        self.assertIn("1 条测试用例", done["content"])
        self.assertEqual(done["tool_calls"], [{"name": "search_knowledge"}])
        # token 事件拼接后应与最终回答一致
        streamed = "".join(e["content"] for e in events if e["type"] == "token")
        self.assertEqual(streamed, done["content"])

    def test_mock_mutation_obeys_zero_tool_budget_before_side_effect(self):
        doc = RequirementDocument(
            project_id=1,
            title="预算需求",
            status="structured",
        )
        self.db.add(doc)
        self.db.flush()
        self.db.add(RequirementItem(document_id=doc.id, feature="登录", confirmed=False))
        run = AgentRun(
            project_id=1,
            run_kind="chat",
            execution_mode="inline",
            status="running",
        )
        self.db.add(run)
        self.db.commit()
        runtime = RuntimeHarness(
            self.db,
            RunContext(
                run_id=run.id,
                project_id=1,
                task_id=0,
                budget=ExecutionBudget(max_tool_calls=0, max_runtime_seconds=300),
            ),
            budget_mode="enforce",
        )

        with self.assertRaises(BudgetExhausted):
            from app.agent.runner import _run_mock
            asyncio.run(_collect(_run_mock(
                self.db,
                1,
                "确认生成",
                RuntimeModelConfig(),
                runtime=runtime,
            )))

        self.db.refresh(doc)
        self.assertEqual(doc.status, "structured")
        from app.models.generation import GenerationTask
        self.assertEqual(self.db.query(GenerationTask).count(), 0)


class MemoryRuntimeBoundaryTests(unittest.TestCase):
    def test_summary_budget_exhaustion_propagates_to_parent_runtime(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        db = session_factory()
        thread = AgentThread(project_id=1, title="summary")
        db.add(thread)
        db.flush()
        db.add_all([
            AgentMessage(project_id=1, thread_id=thread.id, role="user", content=f"消息 {i}")
            for i in range(45)
        ])
        db.commit()

        class BudgetRuntime:
            async def call_llm(self, *args, **kwargs):
                raise BudgetExhausted("llm_calls", 2, 1)

        class FakeClient:
            async def aclose(self):
                return None

        class FakeModel:
            http_async_client = FakeClient()

        try:
            with (
                patch("app.agent.memory.SessionLocal", session_factory),
                patch("app.agent.memory.create_chat_model", return_value=FakeModel()),
            ):
                with self.assertRaises(BudgetExhausted):
                    asyncio.run(maybe_update_summary(
                        thread.id,
                        RuntimeModelConfig(llm_mock_mode=False, llm_api_key="test"),
                        force=True,
                        runtime=BudgetRuntime(),
                    ))
        finally:
            db.close()
            engine.dispose()


class HistoryMessagesTests(unittest.TestCase):
    def test_roles_and_order(self):
        messages = _history_messages([("user", "问1"), ("assistant", "答1")])
        self.assertEqual(messages[0].content, "问1")
        self.assertEqual(messages[0].type, "human")
        self.assertEqual(messages[1].type, "ai")

    def test_limit_and_empty_content_skipped(self):
        history = [("user", f"问{i}") for i in range(HISTORY_LIMIT + 5)] + [("assistant", "")]
        messages = _history_messages(history)
        self.assertLessEqual(len(messages), HISTORY_LIMIT)
        self.assertTrue(all(m.content for m in messages))

    def test_token_window_keeps_latest_messages(self):
        history = [
            ("user", "较早消息" * 20),
            ("assistant", "中间消息" * 20),
            ("user", "最新问题"),
        ]
        selected = select_context(history, token_budget=30, message_limit=10)
        self.assertEqual(selected[-1], ("user", "最新问题"))
        self.assertNotIn(history[0], selected)
        self.assertGreater(estimate_tokens("中文abc"), 0)

    def test_only_agent_node_model_tokens_are_forwarded(self):
        self.assertTrue(_is_agent_model_stream({
            "metadata": {"langgraph_node": "agent"},
        }))
        self.assertFalse(_is_agent_model_stream({
            "metadata": {"langgraph_node": "tools"},
        }))
        self.assertFalse(_is_agent_model_stream({
            "metadata": {"langgraph_node": "generate_core_cases"},
        }))
        self.assertFalse(_is_agent_model_stream({}))


class ApprovalCheckpointTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.doc = RequirementDocument(
            id=1,
            project_id=1,
            title="登录需求",
            status="structured",
        )
        self.db.add_all([
            self.doc,
            RequirementItem(
                id=1,
                document_id=1,
                module="登录",
                feature="密码登录",
                confirmed=False,
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_mock_action_pauses_and_can_be_cancelled_after_resume(self):
        async def scenario(checkpoint_path: Path):
            with patch("app.agent.checkpoint.CHECKPOINT_PATH", checkpoint_path):
                first = await _collect(run_agent(
                    self.db,
                    1,
                    "演示项目",
                    "确认生成",
                    [],
                    RuntimeModelConfig(),
                    checkpoint_thread_id="agent:test:approval",
                ))
                second = await _collect(run_agent(
                    self.db,
                    1,
                    "演示项目",
                    "确认生成",
                    [],
                    RuntimeModelConfig(),
                    checkpoint_thread_id="agent:test:approval",
                    resume_value=False,
                ))
                return first, second

        checkpoint_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / f"agent-checkpoint-{uuid.uuid4().hex}.sqlite"
        )
        try:
            first, second = asyncio.run(scenario(checkpoint_path))
        finally:
            for suffix in ("", "-shm", "-wal"):
                Path(f"{checkpoint_path}{suffix}").unlink(missing_ok=True)

        self.assertEqual(first[-1]["type"], "approval_required")
        self.assertEqual(
            [a["name"] for a in first[-1]["approval"]["actions"]],
            ["confirm_features", "start_generation"],
        )
        self.assertEqual(second[-1]["type"], "done")
        self.assertIn("没有执行", second[-1]["content"])
        self.db.refresh(self.doc)
        self.assertEqual(self.doc.status, "structured")

    def test_real_graph_interrupts_before_mutating_tool_and_resumes_once(self):
        calls = {"confirm": [], "start": []}

        @tool
        def confirm_features(document_id: int) -> str:
            """确认功能点。"""
            calls["confirm"].append(document_id)
            return '{"confirmed_count": 1}'

        @tool
        def start_generation(document_id: int, strategy: str = "full") -> str:
            """启动用例生成。"""
            calls["start"].append((document_id, strategy))
            return '{"task_id": 10}'

        class StubToolCallingModel:
            async def ainvoke(self, messages):
                tool_messages = [
                    message for message in messages if isinstance(message, ToolMessage)
                ]
                if any(message.name == "start_generation" for message in tool_messages):
                    return AIMessage(content="已完成确认")
                if any(message.name == "confirm_features" for message in tool_messages):
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "start_generation",
                            "args": {"document_id": 1, "strategy": "full"},
                            "id": "call-start-1",
                            "type": "tool_call",
                        }],
                    )
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "confirm_features",
                        "args": {"document_id": 1},
                        "id": "call-confirm-1",
                        "type": "tool_call",
                    }],
                )

        async def scenario():
            graph = _build_agent_graph(
                StubToolCallingModel(),
                [confirm_features, start_generation],
                InMemorySaver(),
            )
            config = {"configurable": {"thread_id": "real-approval"}}
            first = await graph.ainvoke(
                {
                    "messages": [HumanMessage("确认生成")],
                    "approved_actions": [],
                    "approval_decision": "",
                },
                config=config,
            )
            self.assertIn("__interrupt__", first)
            approval = first["__interrupt__"][0].value
            self.assertEqual(
                [action["name"] for action in approval["actions"]],
                ["confirm_features", "start_generation"],
            )
            self.assertEqual(calls, {"confirm": [], "start": []})
            second = await graph.ainvoke(
                Command(resume={"approved": True}),
                config=config,
            )
            return second

        result = asyncio.run(scenario())
        self.assertEqual(calls["confirm"], [1])
        self.assertEqual(calls["start"], [(1, "full")])
        self.assertEqual(result["messages"][-1].content, "已完成确认")

    def test_multiple_tools_run_serially_for_shared_database_session(self):
        execution = {"active": False, "order": []}

        @tool
        async def first_query() -> str:
            """第一个查询。"""
            if execution["active"]:
                raise RuntimeError("concurrent session use")
            execution["active"] = True
            execution["order"].append("first:start")
            await asyncio.sleep(0.01)
            execution["order"].append("first:end")
            execution["active"] = False
            return "first"

        @tool
        async def second_query() -> str:
            """第二个查询。"""
            if execution["active"]:
                raise RuntimeError("concurrent session use")
            execution["active"] = True
            execution["order"].append("second:start")
            await asyncio.sleep(0.01)
            execution["order"].append("second:end")
            execution["active"] = False
            return "second"

        class TwoToolModel:
            async def ainvoke(self, messages):
                if any(isinstance(message, ToolMessage) for message in messages):
                    return AIMessage(content="查询完成")
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "first_query",
                            "args": {},
                            "id": "call-first",
                            "type": "tool_call",
                        },
                        {
                            "name": "second_query",
                            "args": {},
                            "id": "call-second",
                            "type": "tool_call",
                        },
                    ],
                )

        async def scenario():
            graph = _build_agent_graph(
                TwoToolModel(),
                [first_query, second_query],
                InMemorySaver(),
            )
            return await graph.ainvoke(
                {
                    "messages": [HumanMessage("查询两项数据")],
                    "approved_actions": [],
                    "approval_decision": "",
                },
                config={"configurable": {"thread_id": "serial-tools"}},
            )

        result = asyncio.run(scenario())
        self.assertEqual(
            execution["order"],
            ["first:start", "first:end", "second:start", "second:end"],
        )
        self.assertEqual(result["messages"][-1].content, "查询完成")

    def test_real_graph_routes_model_and_tool_calls_through_runtime(self):
        """Catches ReAct using the old ungoverned model/Tool path."""
        calls = {"llm": 0, "tools": []}

        @tool
        async def list_testcases() -> str:
            """查询用例。"""
            return "两条用例"

        class OneToolModel:
            async def ainvoke(self, messages):
                if any(isinstance(message, ToolMessage) for message in messages):
                    return AIMessage(content="查询完成")
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "list_testcases",
                        "args": {},
                        "id": "call-list",
                        "type": "tool_call",
                    }],
                )

        class RecordingRuntime:
            async def call_llm(
                self,
                stage,
                skill_name,
                operation,
                *,
                input_value,
                max_output_tokens,
            ):
                calls["llm"] += 1
                self.assertions = (stage, skill_name, bool(input_value), max_output_tokens)
                return await operation()

            async def run_tool(self, name, operation, *, timeout_seconds=30.0):
                calls["tools"].append((name, timeout_seconds))
                return await operation()

        runtime = RecordingRuntime()

        async def scenario():
            graph = _build_agent_graph(
                OneToolModel(),
                [list_testcases],
                InMemorySaver(),
                runtime=runtime,
            )
            return await graph.ainvoke(
                {
                    "messages": [HumanMessage("有哪些用例")],
                    "approved_actions": [],
                    "approval_decision": "",
                },
                config={"configurable": {"thread_id": "governed-agent"}},
            )

        result = asyncio.run(scenario())
        self.assertEqual(result["messages"][-1].content, "查询完成")
        self.assertEqual(calls["llm"], 2)
        self.assertEqual(calls["tools"], [("list_testcases", 30.0)])
        self.assertEqual(runtime.assertions[:3], ("assistant", "assistant", True))


if __name__ == "__main__":
    unittest.main()
