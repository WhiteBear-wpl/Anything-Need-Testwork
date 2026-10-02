# AITC RAG 生成单次探索性 A/B 评测

同一冻结样本和配置下，唯一变量为 `use_knowledge`。单次结果只说明方向性。

| 指标 | 无 RAG | 有 RAG | 差值(B-A) |
| --- | ---: | ---: | ---: |
| avg_judge_score | 4.5 | 4.2 | -0.3 |
| dual_track | {'rule_pass_rate': 0.0, 'judge_pass_rate': None, 'judge_unavailable_count': 2, 'assessment_status_counts': {'judge_unavailable': 2}, 'evaluated_case_count': 2} | {'rule_pass_rate': 0.0, 'judge_pass_rate': None, 'judge_unavailable_count': 2, 'assessment_status_counts': {'judge_unavailable': 2}, 'evaluated_case_count': 2} | — |
| duplicate_rate | 0.0 | 0.0 | +0.0 |
| hallucination_count | 5.0 | 16.0 | +11.0 |
| recall | 83.3 | 100.0 | +16.7 |
| sample_count | 2.0 | 2.0 | +0.0 |
| success_rate | 100.0 | 100.0 | +0.0 |
| total_cases | 101.0 | 110.0 | +9.0 |
| total_duration_sec | 1694.8 | 2005.1 | +310.3 |
| total_tokens | 70682.0 | 92205.0 | +21523.0 |
| usable_rate | 63.4 | 50.0 | -13.4 |
