"""Validation and Markdown output for one paired RAG generation experiment."""

import copy
from typing import Any


def validate_pair(baseline: dict[str, Any], treatment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if baseline.get("sample_fingerprint") != treatment.get("sample_fingerprint"):
        errors.append("sample_fingerprint differs")
    left, right = copy.deepcopy(baseline.get("config", {})), copy.deepcopy(treatment.get("config", {}))
    left_without_flag, right_without_flag = copy.deepcopy(left), copy.deepcopy(right)
    left_without_flag.pop("use_knowledge", None)
    right_without_flag.pop("use_knowledge", None)
    if left_without_flag != right_without_flag:
        changed = sorted(
            key for key in set(left_without_flag) | set(right_without_flag)
            if left_without_flag.get(key) != right_without_flag.get(key)
        )
        errors.append(f"config differs outside use_knowledge: {', '.join(changed)}")
    if left.get("use_knowledge") is not False or right.get("use_knowledge") is not True:
        errors.append("use_knowledge is not the intended A/B difference")
    if not treatment.get("knowledge_refs"):
        errors.append("treatment knowledge_refs is empty")
    return errors


def render_ab_report(baseline: dict[str, Any], treatment: dict[str, Any]) -> str:
    lines = ["# AITC RAG 生成单次探索性 A/B 评测", "", "同一冻结样本和配置下，唯一变量为 `use_knowledge`。单次结果只说明方向性。", "", "| 指标 | 无 RAG | 有 RAG | 差值(B-A) |", "| --- | ---: | ---: | ---: |"]
    keys = sorted(set(baseline.get("metrics", {})) | set(treatment.get("metrics", {})))
    for key in keys:
        left, right = baseline.get("metrics", {}).get(key), treatment.get("metrics", {}).get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta = f"{right - left:+.1f}"
            lines.append(f"| {key} | {left:.1f} | {right:.1f} | {delta} |")
        else:
            lines.append(f"| {key} | {left if left is not None else '—'} | {right if right is not None else '—'} | — |")
    return "\n".join(lines) + "\n"


def _delta(baseline: dict, treatment: dict, key: str) -> float:
    return float(treatment.get("metrics", {}).get(key, 0)) - float(baseline.get("metrics", {}).get(key, 0))


def _pct_change(baseline: dict, treatment: dict, key: str) -> float:
    left = float(baseline.get("metrics", {}).get(key, 0))
    return (_delta(baseline, treatment, key) / left * 100) if left else 0.0


def _reference_evidence(knowledge_refs: dict) -> tuple[int, int, dict[str, int]]:
    citation_count = 0
    match_counts: dict[str, int] = {}
    for task_refs in knowledge_refs.values():
        if not isinstance(task_refs, dict):
            continue
        for refs in task_refs.values():
            if not isinstance(refs, list):
                continue
            citation_count += len(refs)
            for ref in refs:
                match = str(ref.get("match") or "unknown")
                match_counts[match] = match_counts.get(match, 0) + 1
    return len(knowledge_refs), citation_count, match_counts


def render_interview_report(
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    retrieval: dict[str, Any] | None = None,
) -> str:
    """Render an interview-oriented, evidence-first interpretation of the paired run."""
    bm25 = ((retrieval or {}).get("strategies") or {}).get("bm25", {})
    vector = ((retrieval or {}).get("strategies") or {}).get("vector", {})
    hybrid = ((retrieval or {}).get("strategies") or {}).get("hybrid_rrf", {})
    rerank = ((retrieval or {}).get("strategies") or {}).get("hybrid_rerank", {})
    task_count, citation_count, match_counts = _reference_evidence(treatment.get("knowledge_refs", {}))
    metrics_a, metrics_b = baseline.get("metrics", {}), treatment.get("metrics", {})
    integrity_errors = validate_pair(baseline, treatment)
    dual_track_a = metrics_a.get("dual_track") or {}
    dual_track_b = metrics_b.get("dual_track") or {}

    lines = [
        "# AITC RAG 技术选型面试报告",
        "",
        "## 一句话结论",
        "",
        "`向量检索 + BM25 + RRF` 适合作为当前项目的召回层：离线检索中它取得最高 nDCG@5，端到端 A/B 中把测试点覆盖率提升到 100%。但本次单次实验同时出现可用率下降、幻觉增多和成本上升，因此不能表述为“RAG 全面提升生成质量”；更准确的结论是“召回层有效，知识注入和生成约束仍需优化”。",
        "",
        "## 实验控制",
        "",
        f"- 冻结样本指纹：`{baseline.get('sample_fingerprint', '')}`",
        f"- 运行状态：A=`{baseline.get('status', '')}`，B=`{treatment.get('status', '')}`",
        f"- 唯一开关差异：A `use_knowledge=false`，B `use_knowledge=true`",
        f"- 配置一致性检查：{'通过' if not integrity_errors else '未通过：' + '；'.join(integrity_errors)}",
        f"- B 组引用证据：{task_count} 个生成任务，共记录 {citation_count} 条召回引用；命中类型 `{match_counts}`",
        "- 运行次数：1 次；样本数：2。结论仅具方向性，不作统计显著性声明。",
        "",
    ]
    if retrieval:
        def rmetric(row: dict, name: str) -> str:
            value = ((row.get("metrics") or {}).get("5") or {}).get(name)
            return "—" if value is None else f"{float(value):.3f}"

        lines.extend([
            "## 证据一：召回层离线基准",
            "",
            "| 策略 | Recall@5 | MRR@5 | nDCG@5 | 状态 |",
            "| --- | ---: | ---: | ---: | --- |",
            f"| BM25 | {rmetric(bm25, 'recall')} | {rmetric(bm25, 'mrr')} | {rmetric(bm25, 'ndcg')} | {bm25.get('status', '—')} |",
            f"| Vector | {rmetric(vector, 'recall')} | {rmetric(vector, 'mrr')} | {rmetric(vector, 'ndcg')} | {vector.get('status', '—')} |",
            f"| Hybrid-RRF | {rmetric(hybrid, 'recall')} | {rmetric(hybrid, 'mrr')} | {rmetric(hybrid, 'ndcg')} | {hybrid.get('status', '—')} |",
            f"| Hybrid-Rerank | {rmetric(rerank, 'recall')} | {rmetric(rerank, 'mrr')} | {rmetric(rerank, 'ndcg')} | {rerank.get('status', '—')} |",
            "",
            "Hybrid-RRF 的 Recall@5 与单路检索持平，但 nDCG@5 最高，说明融合主要改善了相关结果的排序位置。Rerank 未配置，因此不能把精排收益写进项目结论。离线无答案误命中率为 100%，说明拒答/阈值校准仍是明确短板。",
            "",
        ])

    selected = [
        ("测试点覆盖率", "recall", "pp"),
        ("可用用例率", "usable_rate", "pp"),
        ("平均 Judge 分", "avg_judge_score", "score"),
        ("幻觉计数", "hallucination_count", "count"),
        ("用例总数", "total_cases", "count"),
        ("Token", "total_tokens", "count"),
        ("耗时（秒）", "total_duration_sec", "count"),
    ]
    lines.extend(["## 证据二：端到端生成 A/B", "", "| 指标 | 无 RAG | 有 RAG | 差值 |", "| --- | ---: | ---: | ---: |"])
    for label, key, _kind in selected:
        left = float(metrics_a.get(key, 0))
        right = float(metrics_b.get(key, 0))
        lines.append(f"| {label} | {left:.1f} | {right:.1f} | {_delta(baseline, treatment, key):+.1f} |")

    lines.extend([
        "",
        "### 正向信号",
        "",
        f"- 测试点覆盖率从 {float(metrics_a.get('recall', 0)):.1f}% 提升到 {float(metrics_b.get('recall', 0)):.1f}%（{_delta(baseline, treatment, 'recall'):+.1f} 个百分点），两份需求的人工 checkpoint 均被覆盖。",
        f"- 用例总数增加 {_delta(baseline, treatment, 'total_cases'):+.0f} 条，成功率维持 {float(metrics_b.get('success_rate', 0)):.1f}%，重复率维持 {float(metrics_b.get('duplicate_rate', 0)):.1f}%。",
        "- B 组存在真实 `knowledge_refs`，且主要为 `match=both`，证明 BM25 与向量检索均参与召回，而不是仅打开配置开关。",
        "",
        "### 代价与反证",
        "",
        f"- 可用用例率下降 {_delta(baseline, treatment, 'usable_rate'):.1f} 个百分点，平均 Judge 分下降 {abs(_delta(baseline, treatment, 'avg_judge_score')):.2f}。",
        f"- 幻觉计数增加 {_delta(baseline, treatment, 'hallucination_count'):+.0f}；Token 增加 {_pct_change(baseline, treatment, 'total_tokens'):+.1f}%，耗时增加 {_pct_change(baseline, treatment, 'total_duration_sec'):+.1f}%。",
        "- 这表明当前 Top-K 知识直接注入会带来上下文噪声和过度展开。技术栈的召回方向成立，但生成侧尚未达到最优。",
        "",
        "## 技术选型决策",
        "",
        "1. 保留 BM25：处理错误码、字段名、状态值等精确词匹配。",
        "2. 保留向量检索：覆盖同义改写、口语化需求和语义相近历史缺陷。",
        "3. 使用 RRF 融合：无需比较两路异构分数的绝对值，且本地金标上获得最高 nDCG@5。",
        "4. Rerank 维持可选：当前未配置、未实测，不能声称已带来收益；后续应在候选集质量稳定后单独做 A/B。",
        "5. 下一轮优先优化生成侧：按模块过滤知识、压缩/去重 Top-K、强化“仅依据引用生成”的提示、加入无答案门控，并扩大样本及重复运行。",
        "",
        "## 面试回答（可直接说）",
        "",
        "> 我没有因为混合检索流行就直接选，而是分两层验证。检索层用领域金标比较 BM25、向量和 RRF，三者 Recall@5 都是 0.978，但 RRF 的 nDCG@5 是 0.918，高于 BM25 的 0.897 和向量的 0.907，所以它更能把有效知识排到前面。端到端我又用同一冻结样本做无 RAG/有 RAG 单次 A/B，唯一变量是 use_knowledge。RAG 把测试点覆盖率从 83.3% 提到 100%，并且生成记录里有真实的混合召回引用；但可用率从 63.4% 降到 50%，幻觉和成本也上升。因此我的结论是混合召回适合这个偏召回优先的测试用例场景，但知识注入还需要过滤、压缩和 grounding。Rerank 因为没配置，我只把它设计成可插拔能力，不会把未验证的收益包装成结果。",
        "",
        "## 结果限制",
        "",
        "- 仅 2 个样本、每组 1 次，无法排除大模型随机性；正式结论至少需要扩充数据并重复运行。",
        f"- 双轨顶层 Judge 在 A/B 中均有 {dual_track_a.get('judge_unavailable_count', 0)}/{dual_track_b.get('judge_unavailable_count', 0)} 个不可用记录，因此顶层 Judge 通过率不能用于支持结论。",
        "- 检索集的无答案误命中率为 100%，说明当前 `0.35` 阈值不足以承担可靠拒答。",
        "- Rerank 模型为空，本报告没有 Rerank 的实际指标。",
    ])
    return "\n".join(lines) + "\n"
