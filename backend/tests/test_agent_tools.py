"""测试助手工具层单测：项目隔离、筛选、截断与空数据兜底。

全部走内存 SQLite，search_knowledge 通过 mock retrieve 验证格式化与截断。
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  确保所有表注册到 Base.metadata
from app.agent.tools import MAX_LIST_ITEMS, SNIPPET_CHARS, build_agent_tools
from app.database import Base
from app.models.execution import TestBatch, TestBatchCase, TestTask
from app.models.generation import GeneratedCaseDraft, GenerationTask
from app.models.agent_run import AgentRun, AgentRunEvent, AgentSpec
from app.models.requirement import RequirementDocument, RequirementItem
from app.models.testcase import TestCase
from app.services.settings_service import RuntimeModelConfig

PROJECT_ID = 1
OTHER_PROJECT_ID = 2


class AgentToolsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self._seed()
        tools = build_agent_tools(self.db, PROJECT_ID, RuntimeModelConfig())
        self.tools = {t.name: t for t in tools}

    def tearDown(self):
        self.db.close()

    def _seed(self):
        doc = RequirementDocument(id=1, project_id=PROJECT_ID, title="需求", status="confirmed")
        items = [
            RequirementItem(id=1, document_id=1, module="支付", feature="退款", confirmed=True),
            RequirementItem(id=2, document_id=1, module="支付", feature="对账", confirmed=True),
            RequirementItem(id=3, document_id=1, module="账户", feature="草稿功能点", confirmed=False),
        ]
        cases = [
            TestCase(id=1, project_id=PROJECT_ID, requirement_item_id=1, title="退款成功路径",
                     priority="P0", case_type="functional", steps="1. 发起退款", expected_result="退款成功"),
            TestCase(id=2, project_id=PROJECT_ID, requirement_item_id=1, title="退款金额超限",
                     priority="P1", case_type="boundary", expected_result="提示金额超限"),
            TestCase(id=3, project_id=OTHER_PROJECT_ID, title="其他项目的用例",
                     priority="P0", expected_result="不应出现"),
        ]
        task = TestTask(id=1, project_id=PROJECT_ID, name="预发验证")
        batch = TestBatch(id=1, task_id=1, name="预发测试")
        batch_cases = [
            TestBatchCase(id=1, batch_id=1, case_id=1, result="passed"),
            TestBatchCase(id=2, batch_id=1, case_id=2, result="failed", note="金额校验缺失", defect_ref="BUG-1"),
        ]
        self.db.add_all([doc, *items, *cases, task, batch, *batch_cases])
        self.db.commit()

    # ---- list_testcases ----

    def test_list_testcases_scoped_to_project(self):
        data = json.loads(self.tools["list_testcases"].invoke({}))
        self.assertEqual(data["total"], 2)
        self.assertTrue(all(c["title"] != "其他项目的用例" for c in data["cases"]))

    def test_list_testcases_filters(self):
        data = json.loads(self.tools["list_testcases"].invoke({"priority": "p0"}))
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["cases"][0]["title"], "退款成功路径")

        data = json.loads(self.tools["list_testcases"].invoke({"keyword": "超限"}))
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["cases"][0]["case_type"], "boundary")

    def test_list_testcases_truncation_note(self):
        for i in range(MAX_LIST_ITEMS + 5):
            self.db.add(TestCase(project_id=PROJECT_ID, title=f"批量用例{i}", expected_result="ok"))
        self.db.commit()
        data = json.loads(self.tools["list_testcases"].invoke({"limit": 999}))
        self.assertEqual(data["returned"], MAX_LIST_ITEMS)
        self.assertIn("仅返回前", data["note"])

    # ---- get_testcase_detail ----

    def test_get_testcase_detail(self):
        data = json.loads(self.tools["get_testcase_detail"].invoke({"case_id": 1}))
        self.assertEqual(data["title"], "退款成功路径")
        self.assertEqual(data["module"], "支付")
        self.assertEqual(data["steps"], "1. 发起退款")

    def test_get_testcase_detail_cross_project_denied(self):
        data = json.loads(self.tools["get_testcase_detail"].invoke({"case_id": 3}))
        self.assertIn("error", data)

    # ---- get_coverage_summary ----

    def test_coverage_summary(self):
        data = json.loads(self.tools["get_coverage_summary"].invoke({}))
        # 已确认 2 个功能点，只有「退款」有用例；未确认的草稿功能点不参与统计
        self.assertEqual(data["confirmed_features"], 2)
        self.assertEqual(data["covered_features"], 1)
        self.assertEqual(data["coverage_rate"], 50.0)
        self.assertEqual(data["uncovered"], [{"module": "支付", "feature": "对账"}])

    def test_coverage_summary_without_confirmed_items(self):
        tools = {t.name: t for t in build_agent_tools(self.db, OTHER_PROJECT_ID, RuntimeModelConfig())}
        data = json.loads(tools["get_coverage_summary"].invoke({}))
        self.assertIn("message", data)

    # ---- get_test_task_stats ----

    def test_task_stats(self):
        data = json.loads(self.tools["get_test_task_stats"].invoke({}))
        task = data["tasks"][0]
        self.assertEqual(task["name"], "预发验证")
        self.assertEqual(task["stats"]["passed"], 1)
        self.assertEqual(task["stats"]["failed"], 1)
        self.assertEqual(task["stats"]["pass_rate"], 50.0)
        self.assertEqual(task["batches"][0]["name"], "预发测试")

    def test_task_stats_name_filter_no_match(self):
        data = json.loads(self.tools["get_test_task_stats"].invoke({"task_name": "不存在"}))
        self.assertIn("message", data)

    # ---- list_defects ----

    def test_list_defects(self):
        data = json.loads(self.tools["list_defects"].invoke({}))
        self.assertEqual(len(data["defects"]), 1)
        defect = data["defects"][0]
        self.assertEqual(defect["title"], "退款金额超限")
        self.assertEqual(defect["defect_ref"], "BUG-1")
        self.assertEqual(defect["task"], "预发验证")

    def test_list_defects_exclude_blocked(self):
        self.db.add(TestCase(id=4, project_id=PROJECT_ID, title="阻塞用例", expected_result="ok"))
        self.db.add(TestBatchCase(id=3, batch_id=1, case_id=4, result="blocked"))
        self.db.commit()
        with_blocked = json.loads(self.tools["list_defects"].invoke({"include_blocked": True}))
        without = json.loads(self.tools["list_defects"].invoke({"include_blocked": False}))
        self.assertEqual(len(with_blocked["defects"]), 2)
        self.assertEqual(len(without["defects"]), 1)

    # ---- search_knowledge ----

    def test_search_knowledge_formats_and_clips(self):
        long_content = "规" * (SNIPPET_CHARS + 100)
        with patch(
            "app.agent.tools.knowledge_service.retrieve",
            new=AsyncMock(return_value=[
                {"content": long_content, "title": "退款规则", "heading": "支付 > 退款",
                 "source_type": "doc", "score": 0.9, "match": "both"},
            ]),
        ):
            data = json.loads(asyncio.run(self.tools["search_knowledge"].ainvoke({"query": "退款"})))
        hit = data["hits"][0]
        self.assertEqual(hit["title"], "退款规则")
        self.assertEqual(hit["match"], "both")
        self.assertLess(len(hit["content"]), len(long_content))
        self.assertIn("已截断", hit["content"])

    def test_search_knowledge_no_hits(self):
        with patch("app.agent.tools.knowledge_service.retrieve", new=AsyncMock(return_value=[])):
            data = json.loads(asyncio.run(self.tools["search_knowledge"].ainvoke({"query": "x"})))
        self.assertEqual(data["hits"], [])
        self.assertIn("message", data)

    def test_search_knowledge_error_degrades(self):
        with patch(
            "app.agent.tools.knowledge_service.retrieve",
            new=AsyncMock(side_effect=RuntimeError("embedding down")),
        ):
            data = json.loads(asyncio.run(self.tools["search_knowledge"].ainvoke({"query": "x"})))
        self.assertIn("error", data)

    def test_search_knowledge_never_converts_runtime_stop_to_business_error(self):
        from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled

        for control_error in (
            BudgetExhausted("llm_calls", 2, 1),
            RuntimeCancelled("cancelled"),
        ):
            with self.subTest(error=type(control_error).__name__):
                with patch(
                    "app.agent.tools.knowledge_service.retrieve",
                    new=AsyncMock(side_effect=control_error),
                ):
                    with self.assertRaises(type(control_error)):
                        asyncio.run(self.tools["search_knowledge"].ainvoke({"query": "x"}))


class AgentPipelineToolsTests(unittest.TestCase):
    """流水线工具单测：解析、确认、启动生成、进度查询与评审的边界与项目隔离。"""

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self._seed()
        tools = build_agent_tools(self.db, PROJECT_ID, RuntimeModelConfig())
        self.tools = {t.name: t for t in tools}

    def tearDown(self):
        self.db.close()

    def _seed(self):
        # doc1：已上传原文、未解析；doc2：已确认，供生成/评审用例使用
        doc1 = RequirementDocument(
            id=1, project_id=PROJECT_ID, title="登录需求",
            raw_content="# 登录\n支持账号密码登录", status="uploaded",
        )
        doc2 = RequirementDocument(id=2, project_id=PROJECT_ID, title="支付需求", status="confirmed")
        items = [
            RequirementItem(id=1, document_id=2, module="支付", feature="退款", confirmed=True),
            RequirementItem(id=2, document_id=2, module="支付", feature="对账", confirmed=True),
        ]
        task = GenerationTask(id=1, project_id=PROJECT_ID, document_id=2, status="completed", progress=100)
        drafts = [
            GeneratedCaseDraft(id=1, task_id=1, requirement_item_id=1, title="退款成功",
                               priority="P0", review_status="pending"),
            GeneratedCaseDraft(id=2, task_id=1, requirement_item_id=1, title="退款失败",
                               priority="P1", review_status="pending"),
            GeneratedCaseDraft(id=3, task_id=1, requirement_item_id=2, title="已采纳的用例",
                               priority="P0", review_status="adopted"),
        ]
        other_doc = RequirementDocument(id=3, project_id=OTHER_PROJECT_ID, title="别人的需求", status="confirmed")
        self.db.add_all([doc1, doc2, *items, task, *drafts, other_doc])
        self.db.commit()

    # ---- parse_requirement_document ----

    def test_start_generation_creates_linked_worker_child_when_parent_is_present(self):
        spec = AgentSpec(name="assistant", version="v1", definition="{}")
        self.db.add(spec)
        self.db.flush()
        parent = AgentRun(
            project_id=PROJECT_ID,
            agent_spec_id=spec.id,
            run_kind="chat",
            execution_mode="inline",
            status="running",
        )
        self.db.add(parent)
        self.db.commit()
        tools = {
            tool.name: tool
            for tool in build_agent_tools(
                self.db,
                PROJECT_ID,
                RuntimeModelConfig(),
                parent_run_id=parent.id,
            )
        }

        with patch("app.agent.tools.start_generation_background") as legacy_start:
            data = json.loads(asyncio.run(
                tools["start_generation"].ainvoke({"document_id": 2})
            ))

        legacy_start.assert_not_called()
        child = self.db.get(AgentRun, data["agent_run_id"])
        self.assertEqual(child.parent_run_id, parent.id)
        self.assertEqual(child.generation_task_id, data["task_id"])
        self.assertEqual((child.run_kind, child.execution_mode), ("generation", "worker"))
        parent_events = (
            self.db.query(AgentRunEvent)
            .filter(AgentRunEvent.agent_run_id == parent.id)
            .order_by(AgentRunEvent.sequence)
            .all()
        )
        self.assertEqual(parent_events[-1].event_type, "child_run_created")

    def test_start_generation_legacy_path_still_launches_background_task(self):
        with patch("app.agent.tools.start_generation_background") as legacy_start:
            data = json.loads(asyncio.run(
                self.tools["start_generation"].ainvoke({"document_id": 2})
            ))

        legacy_start.assert_called_once_with(data["task_id"])
        self.assertNotIn("agent_run_id", data)

    def test_parse_document(self):
        async def fake_structure(db, doc):
            db.add(RequirementItem(id=10, document_id=doc.id, module="登录", feature="密码登录"))
            doc.status = "structured"
            db.commit()

        with patch("app.agent.tools.structure_requirements", new=AsyncMock(side_effect=fake_structure)):
            data = json.loads(asyncio.run(
                self.tools["parse_requirement_document"].ainvoke({"document_id": 1})
            ))
        self.assertEqual(data["item_count"], 1)
        self.assertEqual(data["items"][0]["feature"], "密码登录")
        self.assertIn("确认", data["next_step"])

    def test_parse_document_never_converts_runtime_stop_to_business_error(self):
        from app.agent_runtime.contracts import BudgetExhausted, RuntimeCancelled

        for control_error in (
            BudgetExhausted("llm_calls", 2, 1),
            RuntimeCancelled("cancelled"),
        ):
            with self.subTest(error=type(control_error).__name__):
                with patch(
                    "app.agent.tools.structure_requirements",
                    new=AsyncMock(side_effect=control_error),
                ):
                    with self.assertRaises(type(control_error)):
                        asyncio.run(self.tools["parse_requirement_document"].ainvoke({
                            "document_id": 1,
                        }))

    def test_parse_document_cross_project_denied(self):
        data = json.loads(asyncio.run(
            self.tools["parse_requirement_document"].ainvoke({"document_id": 3})
        ))
        self.assertIn("error", data)

    def test_parse_document_without_content(self):
        data = json.loads(asyncio.run(
            self.tools["parse_requirement_document"].ainvoke({"document_id": 2})
        ))
        self.assertIn("error", data)

    # ---- confirm_features ----

    def test_confirm_features_all(self):
        self.db.add(RequirementItem(id=11, document_id=1, module="登录", feature="密码登录", confirmed=False))
        doc = self.db.get(RequirementDocument, 1)
        doc.status = "structured"
        self.db.commit()

        data = json.loads(self.tools["confirm_features"].invoke({"document_id": 1}))
        self.assertEqual(data["confirmed_count"], 1)
        self.assertEqual(self.db.get(RequirementDocument, 1).status, "confirmed")

    def test_confirm_features_invalid_item_ids(self):
        data = json.loads(self.tools["confirm_features"].invoke({"document_id": 2, "item_ids": [999]}))
        self.assertIn("error", data)

    def test_confirm_features_without_items(self):
        data = json.loads(self.tools["confirm_features"].invoke({"document_id": 1}))
        self.assertIn("error", data)

    # ---- start_generation ----

    def test_start_generation_creates_task(self):
        with patch("app.agent.tools.start_generation_background") as bg:
            data = json.loads(asyncio.run(
                self.tools["start_generation"].ainvoke({"document_id": 2, "strategy": "quick"})
            ))
        task = self.db.get(GenerationTask, data["task_id"])
        self.assertEqual(task.strategy, "quick")
        self.assertEqual(task.project_id, PROJECT_ID)
        bg.assert_called_once_with(task.id)

    def test_start_generation_requires_confirmed(self):
        data = json.loads(asyncio.run(
            self.tools["start_generation"].ainvoke({"document_id": 1})
        ))
        self.assertIn("error", data)

    def test_start_generation_rejects_unknown_specialist_without_creating_task(self):
        before = self.db.query(GenerationTask).count()
        data = json.loads(
            asyncio.run(
                self.tools["start_generation"].ainvoke(
                    {
                        "document_id": 2,
                        "specialist_skills": ["future_specialist"],
                    }
                )
            )
        )
        self.assertIn("error", data)
        self.assertEqual(self.db.query(GenerationTask).count(), before)

    # ---- get_generation_status ----

    def test_get_generation_status(self):
        data = json.loads(self.tools["get_generation_status"].invoke({"task_id": 1}))
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["draft_count"], 3)
        self.assertEqual(data["review_stats"]["adopted"], 1)

    def test_get_generation_status_cross_project_denied(self):
        tools = {t.name: t for t in build_agent_tools(self.db, OTHER_PROJECT_ID, RuntimeModelConfig())}
        data = json.loads(tools["get_generation_status"].invoke({"task_id": 1}))
        self.assertIn("error", data)

    # ---- review_generated_drafts ----

    def test_review_adopt_by_priority_skips_terminal(self):
        data = json.loads(self.tools["review_generated_drafts"].invoke(
            {"task_id": 1, "action": "adopt", "priority": "P0"}
        ))
        # P0 有两条，但 id=3 已是终态，只采纳 id=1
        self.assertEqual(data["count"], 1)
        self.assertEqual(self.db.get(GeneratedCaseDraft, 1).review_status, "adopted")
        self.assertEqual(
            self.db.query(TestCase).filter(TestCase.project_id == PROJECT_ID).count(), 1
        )

    def test_review_reject_rest(self):
        data = json.loads(self.tools["review_generated_drafts"].invoke(
            {"task_id": 1, "action": "reject", "reject_reason": "场景重复"}
        ))
        self.assertEqual(data["count"], 2)
        self.assertEqual(self.db.get(GeneratedCaseDraft, 2).review_status, "rejected")

    def test_review_invalid_action(self):
        data = json.loads(self.tools["review_generated_drafts"].invoke(
            {"task_id": 1, "action": "delete"}
        ))
        self.assertIn("error", data)

    def test_review_no_matching_drafts(self):
        json.loads(self.tools["review_generated_drafts"].invoke({"task_id": 1, "action": "reject"}))
        data = json.loads(self.tools["review_generated_drafts"].invoke({"task_id": 1, "action": "adopt"}))
        self.assertIn("message", data)


if __name__ == "__main__":
    unittest.main()
