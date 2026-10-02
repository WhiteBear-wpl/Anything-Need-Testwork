import { Tag, Tooltip } from 'antd';
import { judgeScoreColor, parseJudgeIssues, stepsToText } from './constants';

function parseQualityIssues(raw) {
  if (!raw) return [];
  try {
    const d = JSON.parse(raw);
    return Array.isArray(d) ? d : [];
  } catch {
    return [];
  }
}

export function CaseDetail({ record }) {
  const judge = parseJudgeIssues(record.judge_issues);
  const qualityIssues = parseQualityIssues(record.quality_issues);
  return (
    <div className="case-detail">
      <div className="case-detail-row">
        <span className="case-detail-label">前置条件</span>{record.precondition || '无'}
      </div>
      <div className="case-detail-row case-detail-row-block">
        <span className="case-detail-label">操作步骤</span>
        <span style={{ whiteSpace: 'pre-wrap' }}>{stepsToText(record.steps)}</span>
      </div>
      <div className="case-detail-row">
        <span className="case-detail-label">预期结果</span>{record.expected_result}
      </div>
      {qualityIssues.length > 0 && (
        <div className="case-detail-row">
          <span className="case-detail-label">质检问题</span>
          <span style={{ color: '#ea580c' }}>{qualityIssues.join('；')}</span>
        </div>
      )}
      {judge && (
        <div className="case-detail-row">
          <span className="case-detail-label">AI 评分</span>
          <span>
            相关性 {judge.relevance ?? '—'} / 可执行 {judge.executability ?? '—'} / 可判定 {judge.verifiability ?? '—'}
            {judge.hallucination && (
              <Tag color="red" style={{ marginLeft: 8 }}>
                疑似幻觉{judge.hallucination_reason ? `：${judge.hallucination_reason}` : ''}
              </Tag>
            )}
            {judge.comment && <span style={{ color: '#94a3b8', marginLeft: 8 }}>{judge.comment}</span>}
          </span>
        </div>
      )}
      {record.review_status === 'rejected' && record.reject_reason && (
        <div className="case-detail-row">
          <span className="case-detail-label">驳回原因</span>{record.reject_reason}
        </div>
      )}
    </div>
  );
}

export function judgeScoreCell(score, record) {
  if (score === null || score === undefined) return <span style={{ color: '#94a3b8' }}>—</span>;
  const judge = parseJudgeIssues(record.judge_issues);
  return (
    <span>
      <span style={{ color: judgeScoreColor(score), fontWeight: 600 }}>{score}</span>
      {judge?.hallucination && (
        <Tooltip title={judge.hallucination_reason || '编造了需求中没有的规则'}>
          <Tag color="red" style={{ marginLeft: 4 }}>幻觉?</Tag>
        </Tooltip>
      )}
    </span>
  );
}

export function ItemDetail({ record }) {
  return (
    <div className="case-detail">
      <div className="case-detail-row">
        <span className="case-detail-label">功能描述</span>
        <span style={{ whiteSpace: 'pre-wrap' }}>{record.description || '无'}</span>
      </div>
      <div className="case-detail-row">
        <span className="case-detail-label">验收标准</span>
        <span style={{ whiteSpace: 'pre-wrap' }}>{record.acceptance_criteria || '无'}</span>
      </div>
      <div className="case-detail-row">
        <span className="case-detail-label">约束/边界</span>
        <span style={{ whiteSpace: 'pre-wrap' }}>{record.constraints || '无'}</span>
      </div>
    </div>
  );
}

export function priorityTag(p) {
  const cls = p === 'P0' ? 'tag-p0' : p === 'P1' ? 'tag-p1' : 'tag-p2';
  return <Tag className={cls} variant="filled">{p}</Tag>;
}
