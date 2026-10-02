import { Button, Card, Col, Row, Spin, Tabs } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import AgentChatPanel from '../components/AgentChatPanel';
import AgentRolloutPanel from '../components/AgentRolloutPanel';
import PageHeader from '../components/PageHeader';
import TestCaseMindmap from '../components/TestCaseMindmap';
import {
  getGenerations,
  getProject,
  getProjectStage,
  getRequirements,
  getTestcases,
  getTestTasks,
} from '../services/api';
import { getStageAction, getStageIndex, STAGE_META } from '../utils/projectAction';

const TYPE_META = [
  { key: 'functional', label: '功能' },
  { key: 'boundary', label: '边界' },
  { key: 'exception', label: '异常' },
];
const PRIORITY_META = [
  { key: 'P0', label: 'P0' },
  { key: 'P1', label: 'P1' },
  { key: 'P2', label: 'P2' },
];

function hasRealDescription(desc) {
  const text = desc?.trim();
  return text && text.length > 2 && !/^\d+$/.test(text);
}

function formatRate(value) {
  return Number.isFinite(value) ? `${value}%` : '—';
}

function MetricItem({ label, value, note }) {
  return (
    <div className="overview-metric">
      <div className="overview-metric-label">{label}</div>
      <div className="overview-metric-value">{value}</div>
      {note && <div className="overview-metric-note">{note}</div>}
    </div>
  );
}

function BarList({ items, emptyText = '暂无数据' }) {
  const maxValue = Math.max(...items.map((item) => item.value), 0);
  if (!maxValue) return <div className="overview-empty">{emptyText}</div>;

  return (
    <div className="overview-bar-list">
      {items.map((item) => (
        <div className="overview-bar-row" key={item.label}>
          <span className="overview-bar-label" title={item.label}>{item.label}</span>
          <span className="overview-bar-track">
            <i style={{ width: `${(item.value / maxValue) * 100}%` }} />
          </span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

function CoverageBars({ modules }) {
  if (!modules.length) {
    return <div className="overview-empty">暂无已确认的需求项</div>;
  }

  return (
    <div className="coverage-list">
      {modules.map((module) => (
        <div className="coverage-row" key={module.name}>
          <div className="coverage-row-head">
            <span title={module.name}>{module.name}</span>
            <strong>{module.rate}%</strong>
          </div>
          <div className="coverage-track">
            <i style={{ width: `${module.rate}%` }} />
          </div>
          <div className="coverage-row-meta">{module.covered} / {module.total} 个需求项已覆盖</div>
        </div>
      ))}
    </div>
  );
}

function ExecutionDonut({ stats }) {
  const total = stats?.total || 0;
  const segments = [
    { key: 'passed', label: '通过', value: stats?.passed || 0, color: '#2f6feb' },
    { key: 'failed', label: '失败', value: stats?.failed || 0, color: '#d95c5c' },
    { key: 'blocked', label: '阻塞', value: stats?.blocked || 0, color: '#91a9cc' },
    { key: 'pending', label: '未执行', value: stats?.pending || 0, color: '#e7ebf0' },
  ];
  let cursor = 0;
  const stops = total
    ? segments.map((segment) => {
      const start = cursor;
      cursor += (segment.value / total) * 100;
      return `${segment.color} ${start}% ${cursor}%`;
    }).join(', ')
    : '#e7ebf0 0 100%';
  const passRate = total ? Math.round(((stats?.passed || 0) / total) * 1000) / 10 : 0;

  return (
    <div className="execution-overview">
      <div
        className="execution-donut"
        style={{ background: `conic-gradient(${stops})` }}
        role="img"
        aria-label={`通过率 ${passRate}%`}
      >
        <div className="execution-donut-center">
          <strong>{passRate}%</strong>
          <span>通过率</span>
        </div>
      </div>
      <div className="execution-legend">
        {segments.map((segment) => (
          <div key={segment.key}>
            <span><i style={{ background: segment.color }} />{segment.label}</span>
            <strong>{segment.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrendLine({ values }) {
  if (!values.length) {
    return <div className="overview-empty overview-trend-empty">暂无评审趋势</div>;
  }

  const width = 360;
  const height = 84;
  const padding = 6;
  const points = values.map((value, index) => {
    const x = values.length === 1
      ? width / 2
      : padding + (index / (values.length - 1)) * (width - padding * 2);
    const y = height - padding - (value / 100) * (height - padding * 2);
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg
      className="quality-trend"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`最近 ${values.length} 次任务采纳率趋势`}
    >
      <line x1="0" y1="21" x2={width} y2="21" />
      <line x1="0" y1="63" x2={width} y2="63" />
      <polyline points={points} />
    </svg>
  );
}

function StageWorkbench({ projectId, stage }) {
  const navigate = useNavigate();
  if (!stage) return null;

  const stageIndex = getStageIndex(stage.stage);
  const stageMeta = STAGE_META[stageIndex];
  const action = getStageAction(projectId, stage);
  const hint = [
    action?.hint,
    stage.document_title ? `需求文档《${stage.document_title}》` : '',
  ].filter(Boolean).join(' · ');

  return (
    <section className="workbench-hero">
      <div className="workbench-steps">
        <div className="workbench-flow" aria-label="项目阶段">
          {STAGE_META.map((item, index) => (
            <span className="workbench-flow-group" key={item.key}>
              <span
                className={[
                  'workbench-flow-step',
                  index < stageIndex ? 'is-complete' : '',
                  index === stageIndex ? 'is-current' : '',
                ].filter(Boolean).join(' ')}
                title={index === stageIndex ? stageMeta.desc : undefined}
              >
                {item.label}
              </span>
              {index < STAGE_META.length - 1 && <span className="workbench-flow-separator">›</span>}
            </span>
          ))}
        </div>
        {hint && <div className="workbench-step-hint">{hint}</div>}
      </div>
      <div className="workbench-actions">
        {action && (
          <Button
            type="primary"
            onClick={() => navigate(action.path)}
          >
            {action.label}
          </Button>
        )}
        {stage.stage === 'done' && (
          <Button onClick={() => navigate(`/projects/${projectId}/generate`)}>
            新一轮生成
          </Button>
        )}
      </div>
    </section>
  );
}

export default function ProjectDetail() {
  const { projectId } = useParams();
  const [searchParams] = useSearchParams();
  const [project, setProject] = useState(null);
  const [stage, setStage] = useState(null);
  const [cases, setCases] = useState([]);
  const [generations, setGenerations] = useState([]);
  const [requirementDocs, setRequirementDocs] = useState([]);
  const [testTasks, setTestTasks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [p, st, tc, gen, docs, tasks] = await Promise.all([
          getProject(projectId),
          getProjectStage(projectId).catch(() => null),
          getTestcases(projectId),
          getGenerations(projectId),
          getRequirements(projectId).catch(() => []),
          getTestTasks(projectId).catch(() => []),
        ]);
        setProject(p);
        setStage(st);
        setCases(tc);
        setGenerations(gen);
        setRequirementDocs(docs);
        setTestTasks(tasks);
      } finally {
        setLoading(false);
      }
    })();
  }, [projectId]);

  // 汇总所有已评审任务，并保留最近几次任务的采纳率趋势。
  const reviewSummary = useMemo(() => {
    const reviewed = generations.filter((g) => g.review_stats?.reviewed);
    if (!reviewed.length) return null;
    const sum = reviewed.reduce(
      (acc, g) => {
        acc.total += g.review_stats.total;
        acc.adopted += g.review_stats.adopted;
        acc.rejected += g.review_stats.rejected;
        acc.editedAdopted += g.review_stats.edited_adopted;
        return acc;
      },
      { total: 0, adopted: 0, rejected: 0, editedAdopted: 0 },
    );
    const rate = (part, whole) => (whole ? Math.round((part / whole) * 1000) / 10 : 0);
    return {
      taskCount: reviewed.length,
      total: sum.total,
      adopted: sum.adopted,
      adoptionRate: rate(sum.adopted, sum.total),
      editRate: rate(sum.editedAdopted, sum.adopted),
      rejectionRate: rate(sum.rejected, sum.total),
      trend: [...reviewed]
        .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
        .slice(-6)
        .map((task) => rate(task.review_stats.adopted, task.review_stats.total)),
    };
  }, [generations]);

  const composition = useMemo(() => {
    const byType = { functional: 0, boundary: 0, exception: 0 };
    const byPriority = { P0: 0, P1: 0, P2: 0 };
    let ai = 0;
    cases.forEach((c) => {
      if (byType[c.case_type] !== undefined) byType[c.case_type] += 1;
      if (byPriority[c.priority] !== undefined) byPriority[c.priority] += 1;
      if (c.source === 'ai_generated') ai += 1;
    });
    const total = cases.length;
    return {
      typeItems: TYPE_META.map((meta) => ({ label: meta.label, value: byType[meta.key] })),
      priorityItems: PRIORITY_META.map((meta) => ({ label: meta.label, value: byPriority[meta.key] })),
      aiCount: ai,
      total,
    };
  }, [cases]);

  const coverageSummary = useMemo(() => {
    const items = requirementDocs.flatMap((doc) => doc.items || []).filter((item) => item.confirmed);
    const coveredIds = new Set(
      cases.map((testcase) => testcase.requirement_item_id).filter((id) => id != null),
    );
    const grouped = new Map();
    items.forEach((item) => {
      const name = item.module?.trim() || '未分类';
      const current = grouped.get(name) || { name, total: 0, covered: 0 };
      current.total += 1;
      if (coveredIds.has(item.id)) current.covered += 1;
      grouped.set(name, current);
    });
    const modules = [...grouped.values()]
      .map((module) => ({
        ...module,
        rate: module.total ? Math.round((module.covered / module.total) * 100) : 0,
      }))
      .sort((a, b) => a.rate - b.rate || b.total - a.total || a.name.localeCompare(b.name, 'zh-CN'))
      .slice(0, 5);
    const covered = items.filter((item) => coveredIds.has(item.id)).length;
    return {
      total: items.length,
      covered,
      uncovered: Math.max(items.length - covered, 0),
      rate: items.length ? Math.round((covered / items.length) * 100) : null,
      modules,
    };
  }, [cases, requirementDocs]);

  // 与顶部“继续评审”保持同一口径：展示当前生成任务的待处理数量。
  const pendingReview = stage?.pending_drafts || 0;

  const latestTestTask = testTasks[0] || null;

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;
  }

  if (!project) return null;

  return (
    <div>
      <PageHeader
        title={project.name}
        description={hasRealDescription(project.description) ? project.description : undefined}
      />

      <StageWorkbench projectId={projectId} stage={stage} />

      <Tabs
        defaultActiveKey={searchParams.get('tab') || 'overview'}
        items={[
          {
            key: 'overview',
            label: '数据概览',
            children: (
              <div className="project-overview">
                <Card className="surface-card overview-metrics-card">
                  <div className="overview-metrics">
                    <MetricItem
                      label="需求覆盖率"
                      value={formatRate(coverageSummary.rate)}
                      note={coverageSummary.total
                        ? `${coverageSummary.covered} / ${coverageSummary.total} 个需求项`
                        : '暂无已确认需求'}
                    />
                    <MetricItem
                      label="用例总数"
                      value={composition.total}
                      note={`${composition.aiCount} 条由 AI 生成`}
                    />
                    <MetricItem
                      label="待评审"
                      value={pendingReview}
                      note={stage?.task_id ? '当前生成任务' : `共 ${generations.length} 次生成任务`}
                    />
                    <MetricItem
                      label="AI 采纳率"
                      value={formatRate(reviewSummary?.adoptionRate)}
                      note={reviewSummary ? `基于 ${reviewSummary.taskCount} 次已评审任务` : '暂无已评审任务'}
                    />
                  </div>
                </Card>

                <AgentRolloutPanel project={project} onProjectChange={setProject} />

                <Row gutter={[16, 16]} className="overview-row">
                  <Col xs={24} xl={10}>
                    <Card
                      className="surface-card overview-card"
                      title="测试执行概况"
                      extra={<Link to={`/projects/${projectId}/tasks`}>查看任务</Link>}
                    >
                      {latestTestTask ? (
                        <>
                          <div className="overview-card-context" title={latestTestTask.name}>
                            最近任务：{latestTestTask.name}
                          </div>
                          <ExecutionDonut stats={latestTestTask.stats} />
                        </>
                      ) : (
                        <div className="overview-empty overview-card-empty">
                          暂无测试任务，执行用例后展示结果
                        </div>
                      )}
                    </Card>
                  </Col>
                  <Col xs={24} xl={14}>
                    <Card className="surface-card overview-card" title="需求模块覆盖">
                      <CoverageBars modules={coverageSummary.modules} />
                      {coverageSummary.total > 0 && (
                        <div className="coverage-summary">
                          共 {coverageSummary.total} 个已确认需求项，仍有 {coverageSummary.uncovered} 个未覆盖
                        </div>
                      )}
                    </Card>
                  </Col>
                </Row>

                <Row gutter={[16, 16]} className="overview-row">
                  <Col xs={24} xl={14}>
                    <Card className="surface-card overview-card" title="用例分布">
                      {composition.total === 0 ? (
                        <div className="overview-empty overview-card-empty">
                          暂无用例，<Link to={`/projects/${projectId}/generate`}>去 AI 生成</Link> 并采纳后展示
                        </div>
                      ) : (
                        <div className="distribution-columns">
                          <div>
                            <h4>按类型</h4>
                            <BarList items={composition.typeItems} />
                          </div>
                          <div>
                            <h4>按优先级</h4>
                            <BarList items={composition.priorityItems} />
                          </div>
                        </div>
                      )}
                    </Card>
                  </Col>
                  <Col xs={24} xl={10}>
                    <Card className="surface-card overview-card" title="AI 生成质量">
                      <div className="quality-metrics">
                        <div>
                          <span>采纳率</span>
                          <strong className="is-primary">{formatRate(reviewSummary?.adoptionRate)}</strong>
                        </div>
                        <div>
                          <span>编辑率</span>
                          <strong>{formatRate(reviewSummary?.editRate)}</strong>
                        </div>
                        <div>
                          <span>驳回率</span>
                          <strong>{formatRate(reviewSummary?.rejectionRate)}</strong>
                        </div>
                      </div>
                      <TrendLine values={reviewSummary?.trend || []} />
                      <div className="quality-note">
                        {reviewSummary
                          ? `基于 ${reviewSummary.taskCount} 次已评审任务，共 ${reviewSummary.total} 条候选用例`
                          : '完成用例评审后展示质量趋势'}
                      </div>
                    </Card>
                  </Col>
                </Row>
              </div>
            ),
          },
          {
            key: 'mindmap',
            label: '用例脑图',
            children: <TestCaseMindmap cases={cases} projectName={project.name} />,
          },
        ]}
      />

      <AgentChatPanel projectId={projectId} />
    </div>
  );
}
