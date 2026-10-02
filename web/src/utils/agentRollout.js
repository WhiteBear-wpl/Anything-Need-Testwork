const AGENT_LABEL = {
  case_writer: '基础用例 Agent',
  security: '安全测试 Agent',
  api_test: '接口测试 Agent',
  quality_reviewer: '质量评审 Agent',
};

const AGENT_ORDER = ['case_writer', 'security', 'api_test', 'quality_reviewer'];

export function agentLabel(agent) {
  return AGENT_LABEL[agent] || (agent ? `${agent} Agent` : '未知 Agent');
}

function parseSummary(raw) {
  try {
    const value = JSON.parse(raw || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function durationLabel(value) {
  if (!Number.isFinite(value)) return '';
  if (value < 1000) return `${Math.max(0, value)}ms`;
  return `${(value / 1000).toFixed(2)}s`;
}

export function describeRuntimeEvent(event) {
  const payload = parseSummary(event?.payload_summary);
  const agent = agentLabel(payload.agent);
  if (event?.event_type === 'agent_started') {
    return { color: 'blue', title: `${agent} · 开始执行`, summary: '' };
  }
  if (event?.event_type === 'agent_completed') {
    const parts = [];
    if (Number.isFinite(payload.candidate_count)) {
      parts.push(`产出 ${payload.candidate_count} 个候选`);
    }
    const duration = durationLabel(payload.duration_ms);
    if (duration) parts.push(duration);
    return { color: 'green', title: `${agent} · 完成`, summary: parts.join(' · ') };
  }
  if (event?.event_type === 'agent_warning') {
    return {
      color: 'orange',
      title: `${agent} · 降级失败`,
      summary: typeof payload.message === 'string' ? payload.message : '',
    };
  }
  const eventType = event?.event_type || '';
  const color = eventType.includes('failed')
    ? 'red'
    : eventType.includes('cancel')
      ? 'orange'
      : eventType.includes('completed') || eventType.includes('succeeded')
        ? 'green'
        : 'blue';
  return {
    color,
    title: event?.stage || eventType,
    summary: [payload.message, payload.reason, payload.skill].find(value => typeof value === 'string') || '',
  };
}

export function agentMetricRows(collaboration) {
  const candidates = collaboration?.candidate_counts_by_agent || {};
  const warnings = collaboration?.warning_counts_by_agent || {};
  const adopted = collaboration?.adopted_participation_by_agent || {};
  const agents = new Set([
    ...Object.keys(candidates),
    ...Object.keys(warnings),
    ...Object.keys(adopted),
  ]);
  const rank = agent => {
    const index = AGENT_ORDER.indexOf(agent);
    return index >= 0 ? index : AGENT_ORDER.length;
  };
  return [...agents]
    .sort((left, right) => rank(left) - rank(right) || left.localeCompare(right))
    .map(agent => ({
      agent,
      label: agentLabel(agent),
      candidates: Number(candidates[agent] || 0),
      warnings: Number(warnings[agent] || 0),
      adopted: Number(adopted[agent] || 0),
    }));
}
