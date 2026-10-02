import { Card, Descriptions, Tag, Typography } from 'antd';
import { presentRuleDimensions, presentScorecard } from '../pages/evaluation/scorecardPresentation';

const { Text } = Typography;

const RULE_DIMENSION_LABELS = {
  completeness: '完整性',
  step_executability: '步骤可执行性',
  expected_verifiability: '预期可验证性',
  internal_consistency: '内部一致性',
  duplicate_rate: '任务内重复度',
  checkpoint_coverage: '检查点覆盖度',
};

const JUDGE_DIMENSION_LABELS = {
  business_relevance: '业务相关性',
  executability: '步骤可执行性',
  verifiability: '预期可验证性',
  scenario_completeness: '场景完整性',
  boundary_awareness: '边界/异常意识',
  coverage_reasonableness: '覆盖合理性',
};

function caseEntries(section) {
  return Object.entries(section?.cases || {});
}

export default function EvalScorecard({ scorecard }) {
  const view = presentScorecard(scorecard);
  if (view.empty) return <Text type="secondary">该历史结果尚未执行双轨评测。</Text>;
  const ruleDimensions = presentRuleDimensions(scorecard.rule_dimensions);

  return (
    <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
      <Card size="small" title="规则轨" extra={<Tag color={view.rule.color}>{view.rule.label}</Tag>}>
        {view.showRuleScore && <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>{scorecard.rule_score} / 100</div>}
        {ruleDimensions.cases.map(([caseId, item]) => (
          <Descriptions key={caseId} size="small" column={1} title={`用例 #${caseId}`}>
            {Object.entries(item.dimensions || {}).map(([name, dimension]) => (
              <Descriptions.Item key={name} label={RULE_DIMENSION_LABELS[name] || name}>
                <Tag color={dimension.verdict === 'pass' ? 'success' : dimension.verdict === 'warning' ? 'warning' : 'error'}>{dimension.score}</Tag>
                {(dimension.evidence || []).join('；')}
              </Descriptions.Item>
            ))}
          </Descriptions>
        ))}
        {ruleDimensions.suite.length > 0 && (
          <Descriptions size="small" column={1} title="套件级指标">
            {ruleDimensions.suite.map(([name, dimension]) => (
              <Descriptions.Item key={name} label={RULE_DIMENSION_LABELS[name] || name}>
                <Tag color={dimension.verdict === 'pass' ? 'success' : dimension.verdict === 'warning' ? 'warning' : 'error'}>{dimension.score}</Tag>
                {(dimension.evidence || []).join('；')}
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Card>
      <Card size="small" title="LLM Judge 轨" extra={<Tag color={view.judge.color}>{view.judge.label}</Tag>}>
        {view.showJudgeScore ? caseEntries(scorecard.judge_dimensions).map(([caseId, item]) => (
          <Descriptions key={caseId} size="small" column={1} title={`用例 #${caseId}`}>
            {Object.entries(item.dimensions || {}).map(([name, value]) => (
              <Descriptions.Item key={name} label={JUDGE_DIMENSION_LABELS[name] || name}>{value} / 5</Descriptions.Item>
            ))}
            {item.reason && <Descriptions.Item label="理由">{item.reason}</Descriptions.Item>}
          </Descriptions>
        )) : <Text type="secondary">{scorecard.judge_reason || 'Judge 尚未完成。'}</Text>}
      </Card>
      <div style={{ gridColumn: '1 / -1' }}><Tag color={view.status.color}>{view.status.label}</Tag></div>
    </div>
  );
}
