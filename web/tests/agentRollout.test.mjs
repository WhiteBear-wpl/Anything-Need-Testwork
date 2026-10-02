import test from 'node:test';
import assert from 'node:assert/strict';

import {
  agentMetricRows,
  describeRuntimeEvent,
} from '../src/utils/agentRollout.js';


test('specialist lifecycle event exposes a safe readable summary', () => {
  const result = describeRuntimeEvent({
    event_type: 'agent_completed',
    stage: 'specialist',
    payload_summary: JSON.stringify({
      agent: 'security',
      candidate_count: 3,
      duration_ms: 1250,
      ignored_raw_field: 'must not render',
    }),
  });

  assert.deepEqual(result, {
    color: 'green',
    title: '安全测试 Agent · 完成',
    summary: '产出 3 个候选 · 1.25s',
  });
});


test('malformed warning event degrades without throwing', () => {
  const result = describeRuntimeEvent({
    event_type: 'agent_warning',
    stage: 'specialist',
    payload_summary: '{bad json',
  });

  assert.equal(result.color, 'orange');
  assert.equal(result.title, '未知 Agent · 降级失败');
  assert.equal(result.summary, '');
});


test('agent metric rows use the union of candidate warning and adoption maps', () => {
  const rows = agentMetricRows({
    candidate_counts_by_agent: { case_writer: 4, security: 2 },
    warning_counts_by_agent: { api_test: 1 },
    adopted_participation_by_agent: { security: 1 },
  });

  assert.deepEqual(rows, [
    { agent: 'case_writer', label: '基础用例 Agent', candidates: 4, warnings: 0, adopted: 0 },
    { agent: 'security', label: '安全测试 Agent', candidates: 2, warnings: 0, adopted: 1 },
    { agent: 'api_test', label: '接口测试 Agent', candidates: 0, warnings: 1, adopted: 0 },
  ]);
});
