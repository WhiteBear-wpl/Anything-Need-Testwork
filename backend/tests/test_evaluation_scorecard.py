import unittest


class EvaluationScorecardServiceTests(unittest.TestCase):
    def test_rule_score_has_six_dimensions_and_checkpoint_evidence(self):
        from app.services.evaluation_scorecard_service import (
            CASE_RULE_DIMENSIONS,
            SUITE_RULE_DIMENSIONS,
            score_rule_track,
        )

        track = score_rule_track(
            [
                {
                    "title": "错误密码登录失败",
                    "precondition": "已有可用账号",
                    "steps": ["输入错误密码并点击登录按钮"],
                    "expected_result": "页面显示密码错误提示且保持在登录页",
                }
            ],
            [{"text": "错误密码提示", "keywords": ["密码错误"]}],
        )

        self.assertEqual(set(track["cases"][0]["dimensions"]), set(CASE_RULE_DIMENSIONS))
        self.assertEqual(set(track["suite"]), set(SUITE_RULE_DIMENSIONS))
        self.assertEqual(track["verdict"], "pass")
        self.assertEqual(track["suite"]["checkpoint_coverage"]["score"], 100)

    def test_duplicate_and_vague_expected_result_have_deterministic_evidence(self):
        from app.services.evaluation_scorecard_service import score_rule_track

        track = score_rule_track(
            [
                {
                    "title": "登录",
                    "steps": ["输入账号并点击登录"],
                    "expected_result": "系统正常",
                },
                {
                    "title": "登录",
                    "steps": ["输入账号并点击登录"],
                    "expected_result": "系统正常",
                },
            ],
            [],
        )

        self.assertEqual(track["suite"]["duplicate_rate"]["verdict"], "fail")
        self.assertIn("模糊", " ".join(track["cases"][0]["dimensions"]["expected_verifiability"]["evidence"]))

    def test_complementary_cases_receive_full_suite_checkpoint_coverage(self):
        from app.services.evaluation_scorecard_service import score_rule_track

        track = score_rule_track(
            [
                {"title": "正常登录", "precondition": "账号有效", "steps": ["输入正确密码"], "expected_result": "进入首页"},
                {"title": "错误密码", "precondition": "账号有效", "steps": ["输入错误密码"], "expected_result": "显示密码错误"},
                {"title": "账号锁定", "precondition": "连续失败五次", "steps": ["再次提交密码"], "expected_result": "显示账号锁定"},
            ],
            [
                {"text": "正常登录", "keywords": ["进入首页"]},
                {"text": "错误密码", "keywords": ["密码错误"]},
                {"text": "账号锁定", "keywords": ["账号锁定"]},
            ],
        )

        self.assertEqual(track["suite"]["checkpoint_coverage"]["score"], 100)
        self.assertEqual(track["suite"]["checkpoint_coverage"]["missing_checkpoints"], [])
        self.assertTrue(all("checkpoint_coverage" not in item["dimensions"] for item in track["cases"]))

    def test_deterministic_contradiction_lowers_internal_consistency_with_evidence(self):
        from app.services.evaluation_scorecard_service import score_rule_track

        track = score_rule_track(
            [{
                "title": "错误密码登录失败",
                "precondition": "账号有效",
                "steps": ["输入错误密码并提交"],
                "expected_result": "登录成功并进入首页",
            }],
            [],
        )
        dimension = track["cases"][0]["dimensions"]["internal_consistency"]

        self.assertEqual(dimension["verdict"], "fail")
        self.assertIn("矛盾", " ".join(dimension["evidence"]))

    def test_dual_track_verdicts_do_not_require_a_composite_score(self):
        from app.services.evaluation_scorecard_service import assessment_status, judge_verdict

        self.assertEqual(
            judge_verdict({"business_relevance": 4, "executability": 4, "verifiability": 4}),
            "pass",
        )
        self.assertEqual(
            judge_verdict({"business_relevance": 2, "executability": 5, "verifiability": 5}),
            "fail",
        )
        self.assertEqual(assessment_status("pass", "unavailable", ""), "judge_unavailable")

    def test_assessment_status_matrix_never_treats_rule_warning_as_dual_pass(self):
        from app.services.evaluation_scorecard_service import assessment_status

        expected = {
            ("pass", "completed", "pass"): "dual_pass",
            ("warning", "completed", "pass"): "rule_issue",
            ("fail", "completed", "pass"): "rule_issue",
            ("pass", "completed", "concern"): "judge_concern",
            ("pass", "completed", "fail"): "judge_concern",
            ("warning", "unavailable", ""): "judge_unavailable",
        }
        for inputs, status in expected.items():
            with self.subTest(inputs=inputs):
                self.assertEqual(assessment_status(*inputs), status)

    def test_input_fingerprint_and_run_summary_are_stable_without_total_score(self):
        from app.services.evaluation_scorecard_service import (
            scorecard_input_fingerprint,
            summarize_scorecard_payloads,
        )

        first = scorecard_input_fingerprint(
            "登录需求", [{"text": "错误密码", "keywords": []}], {"title": "错误密码"}
        )
        changed = scorecard_input_fingerprint(
            "登录需求", [{"text": "验证码过期", "keywords": []}], {"title": "错误密码"}
        )
        summary = summarize_scorecard_payloads(
            [
                {"rule_verdict": "pass", "judge_status": "completed", "judge_verdict": "pass", "assessment_status": "dual_pass"},
                {"rule_verdict": "fail", "judge_status": "unavailable", "judge_verdict": "", "assessment_status": "judge_unavailable"},
            ]
        )

        self.assertEqual(first, scorecard_input_fingerprint("登录需求", [{"text": "错误密码", "keywords": []}], {"title": "错误密码"}))
        self.assertNotEqual(first, changed)
        self.assertEqual(summary["rule_pass_rate"], 50.0)
        self.assertEqual(summary["judge_unavailable_count"], 1)
        self.assertNotIn("total_score", summary)
        self.assertNotIn("overall_score", summary)

    def test_input_fingerprint_changes_with_frozen_runtime_versions(self):
        from app.services.evaluation_scorecard_service import scorecard_input_fingerprint

        baseline = scorecard_input_fingerprint(
            "登录需求",
            [],
            {"cases": [{"title": "登录"}]},
            run_envelope={"models": {"generation": {"model": "model-a"}}},
            ruleset_version="rules-v1",
            judge_prompt_version="judge-v1",
        )
        changed_model = scorecard_input_fingerprint(
            "登录需求",
            [],
            {"cases": [{"title": "登录"}]},
            run_envelope={"models": {"generation": {"model": "model-b"}}},
            ruleset_version="rules-v1",
            judge_prompt_version="judge-v1",
        )

        self.assertNotEqual(baseline, changed_model)


if __name__ == "__main__":
    unittest.main()
