# AITC Rerank 生成单次 A/B 评测

本轮比较的是 **开启知识库的 Hybrid-RRF** 与 **开启知识库的 Hybrid-RRF + Rerank**，而不是无 RAG 与有 RAG。

- A Run #3：`use_knowledge=true`，Rerank 未启用
- B Run #4：`use_knowledge=true`，Rerank=`BAAI/bge-reranker-v2-m3`
- 冻结样本一致：`True`
- 除 Rerank 模型段外配置一致：`True`
- Rerank 连通性已在运行前通过；生产检索在 Rerank 请求异常时会静默回退到 RRF 顺序。

| 指标 | Hybrid-RRF | Hybrid-RRF + Rerank | 差值(B-A) |
| --- | ---: | ---: | ---: |
| success_rate | 100.0 | 100.0 | +0.0 |
| total_cases | 100.0 | 116.0 | +16.0 |
| usable_rate | 60.0 | 47.4 | -12.6 |
| recall | 66.7 | 66.7 | +0.0 |
| duplicate_rate | 0.0 | 1.7 | +1.7 |
| hallucination_count | 15.0 | 23.0 | +8.0 |
| avg_judge_score | 4.3 | 4.3 | -0.0 |
| total_tokens | 86690.0 | 91016.0 | +4326.0 |
| total_duration_sec | 1306.5 | 1927.5 | +621.0 |

## 判读边界

- B 优于 A 只能说明本次两份样本上 Rerank 的方向性收益；单次、两样本不构成统计显著性结论。
- `knowledge_refs` 记录的是 RRF 的命中来源；当前线上链路不会在引用中额外标记每个 query 是否发生了 Rerank 降级。
- 可用率、幻觉计数、Token 与耗时需与覆盖率一起解读，不能只用“用例更多”判断优化。
