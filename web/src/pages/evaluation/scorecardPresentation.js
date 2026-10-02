const RULE_LABELS = {
  pass: ['通过', 'success'],
  warning: ['警告', 'warning'],
  fail: ['不通过', 'error'],
};

const JUDGE_LABELS = {
  pass: ['通过', 'success'],
  concern: ['存疑', 'warning'],
  fail: ['不通过', 'error'],
};

const STATUS_LABELS = {
  dual_pass: ['双轨通过', 'success'],
  rule_issue: ['规则问题', 'warning'],
  judge_concern: ['Judge 存疑', 'warning'],
  dual_fail: ['双轨不通过', 'error'],
  judge_unavailable: ['Judge 不可用（规则结果仍有效）', 'default'],
  not_evaluated: ['未完成评测', 'default'],
};

const label = (map, value, fallback) => {
  const [text, color] = map[value] || [fallback, 'default'];
  return { label: text, color };
};

export function presentScorecard(scorecard) {
  if (!scorecard) {
    return {
      empty: true,
      status: label(STATUS_LABELS, 'not_evaluated', '未完成评测'),
      showRuleScore: false,
      showJudgeScore: false,
      rule: null,
      judge: null,
    };
  }
  const status = scorecard.assessment_status === 'rule_issue' && scorecard.rule_verdict === 'warning'
    ? { label: '规则警告（Judge 结果独立有效）', color: 'warning' }
    : scorecard.assessment_status === 'rule_issue' && scorecard.rule_verdict === 'fail'
      ? { label: '规则不通过（Judge 结果独立有效）', color: 'error' }
      : label(STATUS_LABELS, scorecard.assessment_status, scorecard.assessment_status || '未完成评测');
  return {
    empty: false,
    status,
    showRuleScore: Number.isInteger(scorecard.rule_score),
    showJudgeScore: scorecard.judge_status === 'completed',
    rule: label(RULE_LABELS, scorecard.rule_verdict, scorecard.rule_verdict || '未评估'),
    judge: scorecard.judge_status === 'unavailable'
      ? label(STATUS_LABELS, 'judge_unavailable', 'Judge 不可用')
      : label(JUDGE_LABELS, scorecard.judge_verdict, scorecard.judge_verdict || '未评估'),
  };
}

export function presentRuleDimensions(ruleDimensions) {
  const source = ruleDimensions && typeof ruleDimensions === 'object' ? ruleDimensions : {};
  const nestedCases = source.cases && typeof source.cases === 'object' ? source.cases : null;
  const legacyCases = Object.fromEntries(
    Object.entries(source).filter(([key]) => !['schema_version', 'cases', 'suite'].includes(key)),
  );
  return {
    schemaVersion: source.schema_version || '1',
    cases: Object.entries(nestedCases || legacyCases),
    suite: Object.entries(source.suite || {}),
  };
}

export function presentDualTrackSummary(summary) {
  const source = summary || {};
  return {
    items: [
      { key: 'rule_pass_rate', label: '规则通过率', value: source.rule_pass_rate == null ? '—' : `${source.rule_pass_rate}%` },
      { key: 'judge_pass_rate', label: 'Judge 通过率', value: source.judge_pass_rate == null ? '—' : `${source.judge_pass_rate}%` },
      { key: 'judge_unavailable_count', label: 'Judge 不可用', value: source.judge_unavailable_count ?? 0 },
    ],
    statusCounts: source.assessment_status_counts || {},
  };
}
