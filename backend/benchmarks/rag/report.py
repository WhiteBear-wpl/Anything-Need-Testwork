"""Render auditable benchmark summaries without inventing unavailable metrics."""

from __future__ import annotations

from typing import Any


def render_report(summary: dict[str, Any]) -> str:
    lines = ["# AITC RAG 检索离线领域基准评测", "", "本报告使用仓库内可追溯语料和金标，不代表线上用户流量表现。", ""]
    lines += ["| 策略 | Recall@5 | MRR@5 | nDCG@5 | 无答案误命中 | P95 延迟(ms) | 可用性 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, data in summary["strategies"].items():
        if data["status"] == "not_executed":
            lines.append(f"| {name} | 未执行 | 未执行 | 未执行 | 未执行 | 未执行 | 0.000 |")
            lines.append(f"\n> {name}：未执行，原因：{data['error']}\n")
            continue
        metrics = data["metrics"]["5"]
        def value(key: str) -> str:
            number = metrics[key]
            return "—" if number is None else f"{number:.3f}"
        lines.append(f"| {name} | {value('recall')} | {value('mrr')} | {value('ndcg')} | {value('no_answer_false_positive_rate')} | {data['p95_latency_ms']:.2f} | {data['availability']:.3f} |")
    return "\n".join(lines) + "\n"
