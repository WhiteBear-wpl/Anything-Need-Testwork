import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  App, AutoComplete, Button, Drawer, Dropdown, Form, Input, Modal, Space, Spin, Table, Tag, Timeline, Tooltip, Typography,
} from 'antd';
import { PlayCircleOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import {
  QUALITY_COLOR, QUALITY_LABEL, REVIEW_COLOR, REVIEW_LABEL, SKILL_LABEL, STATUS_LABEL, STRATEGY_LABEL, TYPE_LABEL,
} from '../pages/generate/constants';
import { CaseDetail, judgeScoreCell, priorityTag } from '../pages/generate/DetailPanels';
import {
  cancelGenerationRun, createTestTask, exportGenerationDrafts, getGeneration, getGenerationRun,
  getGenerationCollaboration, getGenerationRunEvents, getGenerationSummaries, retryGenerationRun,
} from '../services/api';
import { BATCH_PRESETS } from '../utils/runResult';
import { agentLabel, agentMetricRows, describeRuntimeEvent } from '../utils/agentRollout';
import { runStatusPresentation } from '../utils/agentRuntime';

const { Text } = Typography;

function adoptionCell(stats) {
  if (!stats?.total) return <span style={{ color: '#94a3b8' }}>—</span>;
  if (!stats.reviewed) return <Tag>待评审</Tag>;
  const color = stats.adoption_rate >= 70 ? '#16a34a' : stats.adoption_rate >= 40 ? '#ea580c' : '#dc2626';
  return (
    <Tooltip title={`共 ${stats.total} 条：采纳 ${stats.adopted}（其中编辑后采纳 ${stats.edited_adopted}）、驳回 ${stats.rejected}、未处理 ${stats.pending}`}>
      <span style={{ color, fontWeight: 600 }}>{stats.adoption_rate}%</span>
      <span style={{ color: '#94a3b8', marginLeft: 4 }}>({stats.adopted}/{stats.total})</span>
    </Tooltip>
  );
}

const DISPOSITION_LABEL = {
  selected: '选中',
  merged: '已合并',
  merged_duplicate: '合并重复',
  rejected: '未采用',
};

const candidateColumns = [
  {
    title: '来源 Agent',
    dataIndex: 'source_agent',
    render: value => agentLabel(value),
  },
  {
    title: '候选去向',
    dataIndex: 'merge_disposition',
    width: 110,
    render: value => (
      <Tag color={value === 'selected' ? 'success' : value === 'merged_duplicate' ? 'blue' : 'default'}>
        {DISPOSITION_LABEL[value] || value}
      </Tag>
    ),
  },
  { title: '原因', dataIndex: 'merge_reason', ellipsis: true, render: value => value || '—' },
];

const draftColumns = [
  { title: '用例标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
  {
    title: '用例集',
    dataIndex: 'is_smoke',
    width: 80,
    render: v => (v ? <Tag color="green">冒烟</Tag> : <Tag>完整</Tag>),
  },
  { title: '类型', dataIndex: 'case_type', width: 80, render: v => <Tag>{TYPE_LABEL[v] || v}</Tag> },
  { title: '优先级', dataIndex: 'priority', width: 80, render: priorityTag },
  { title: '质量', dataIndex: 'quality_status', width: 90, render: v => <Tag color={QUALITY_COLOR[v]}>{QUALITY_LABEL[v] || v}</Tag> },
  { title: 'AI 评分', dataIndex: 'judge_score', width: 100, render: judgeScoreCell },
  {
    title: '评审',
    dataIndex: 'review_status',
    width: 90,
    render: (v, r) => {
      const tag = <Tag color={REVIEW_COLOR[v]}>{REVIEW_LABEL[v] || v}</Tag>;
      return v === 'rejected' && r.reject_reason
        ? <Tooltip title={`驳回原因：${r.reject_reason}`}>{tag}</Tooltip>
        : tag;
    },
  },
];

export default function GenerationHistory({ projectId }) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [summaries, setSummaries] = useState([]);
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const [activeSummary, setActiveSummary] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [agentRun, setAgentRun] = useState(null);
  const [runEvents, setRunEvents] = useState([]);
  const [collaboration, setCollaboration] = useState(null);
  const [runActionLoading, setRunActionLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [runTarget, setRunTarget] = useState(null);
  const [runCreating, setRunCreating] = useState(false);
  const [runForm] = Form.useForm();
  const runtimeRequestRef = useRef(0);

  useEffect(() => {
    setLoading(true);
    getGenerationSummaries(projectId)
      .then(setSummaries)
      .catch(() => message.error('加载生成记录失败'))
      .finally(() => setLoading(false));
  }, [projectId]);

  const loadRuntimeRun = async (taskId) => {
    const requestId = ++runtimeRequestRef.current;
    try {
      const run = await getGenerationRun(projectId, taskId);
      const [events, collaborationSummary] = await Promise.all([
        getGenerationRunEvents(projectId, taskId, 0, run.id),
        getGenerationCollaboration(projectId, taskId, run.id),
      ]);
      if (requestId !== runtimeRequestRef.current) return null;
      setAgentRun(run);
      setRunEvents(events);
      setCollaboration(collaborationSummary);
      return run;
    } catch (err) {
      if (requestId !== runtimeRequestRef.current) return null;
      if (err?.response?.status === 404) {
        setAgentRun(null);
        setRunEvents([]);
        setCollaboration(null);
        return null;
      }
      throw err;
    }
  };

  const openDetail = async (record) => {
    setActiveSummary(record);
    setDetailLoading(true);
    try {
      const [task] = await Promise.all([
        getGeneration(projectId, record.id),
        loadRuntimeRun(record.id),
      ]);
      setDetail(task);
    } catch {
      message.error('加载任务详情失败');
      setActiveSummary(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    runtimeRequestRef.current += 1;
    setActiveSummary(null);
    setDetail(null);
    setAgentRun(null);
    setRunEvents([]);
    setCollaboration(null);
  };

  useEffect(() => {
    if (!activeSummary || !agentRun || !['queued', 'running', 'waiting_human'].includes(agentRun.status)) return undefined;
    const timer = window.setInterval(() => {
      loadRuntimeRun(activeSummary.id).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeSummary, agentRun?.status, projectId]);

  const handleRunCancel = async () => {
    if (!activeSummary) return;
    setRunActionLoading(true);
    try {
      await cancelGenerationRun(projectId, activeSummary.id);
      await loadRuntimeRun(activeSummary.id);
      message.success('已请求取消运行');
    } catch (err) {
      message.error(err?.response?.data?.detail || '取消运行失败');
    } finally {
      setRunActionLoading(false);
    }
  };

  const handleRunRetry = async () => {
    if (!activeSummary) return;
    setRunActionLoading(true);
    try {
      await retryGenerationRun(projectId, activeSummary.id);
      await loadRuntimeRun(activeSummary.id);
      setDetail(await getGeneration(projectId, activeSummary.id));
      message.success('已创建恢复运行');
    } catch (err) {
      message.error(err?.response?.data?.detail || '创建重试运行失败');
    } finally {
      setRunActionLoading(false);
    }
  };

  const handleExport = async (format) => {
    if (!activeSummary) return;
    setExporting(true);
    try {
      const res = await exportGenerationDrafts(projectId, activeSummary.id, format, false);
      const ext = format === 'md' ? 'md' : 'xlsx';
      const url = URL.createObjectURL(res.data);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = `${activeSummary.document_title || 'task'}-任务${activeSummary.id}-用例.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      message.error(err.response?.data?.detail || '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const openCreateRun = (record) => {
    const dateSuffix = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', '');
    runForm.setFieldsValue({
      name: `${record.document_title || `任务${record.id}`} ${dateSuffix} 测试`,
      batch_name: '线下测试',
    });
    setRunTarget(record);
  };

  const handleCreateRun = async () => {
    const values = await runForm.validateFields();
    setRunCreating(true);
    try {
      const task = await createTestTask(projectId, {
        name: values.name,
        description: `从生成记录 #${runTarget.id} 导入`,
        batch_name: values.batch_name || '线下测试',
        source_task_id: runTarget.id,
      });
      message.success('测试任务已创建');
      setRunTarget(null);
      runForm.resetFields();
      navigate(`/projects/${projectId}/tasks/${task.id}`);
    } catch (err) {
      message.error(err?.response?.data?.detail || '创建失败');
    } finally {
      setRunCreating(false);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '需求文档', dataIndex: 'document_title', ellipsis: true, render: v => v || '—' },
    {
      title: '策略',
      dataIndex: 'strategy',
      width: 180,
      render: (v, r) => (
        <Space size={4} wrap>
          <Tag color="blue">{STRATEGY_LABEL[v] || v}</Tag>
          {(r.specialist_skills || []).map(s => <Tag key={s}>{SKILL_LABEL[s] || s}</Tag>)}
        </Space>
      ),
    },
    {
      title: '用例数',
      dataIndex: 'draft_count',
      width: 110,
      render: (v, r) => (v ? <span>{v}<Text type="secondary" style={{ marginLeft: 4 }}>(冒烟 {r.smoke_count})</Text></span> : '—'),
    },
    { title: '采纳率', dataIndex: 'review_stats', width: 130, render: adoptionCell },
    {
      title: '覆盖率',
      dataIndex: 'coverage_rate',
      width: 90,
      render: v => (v === null || v === undefined ? '—' : `${v}%`),
    },
    { title: '状态', dataIndex: 'status', width: 90, render: v => <Tag>{STATUS_LABEL[v] || v}</Tag> },
    { title: '时间', dataIndex: 'created_at', width: 160, render: v => new Date(v).toLocaleString() },
    {
      title: '操作',
      width: 140,
      render: (_, record) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => openDetail(record)}>查看</Button>
          {(record.review_stats?.adopted || 0) > 0 && (
            <Tooltip title={`用本次已采纳的 ${record.review_stats.adopted} 条用例创建测试任务`}>
              <Button type="link" size="small" onClick={() => openCreateRun(record)}>建任务</Button>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  const pendingCount = detail?.review_stats?.pending || 0;

  const filteredSummaries = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return summaries;
    return summaries.filter((s) =>
      s.document_title?.toLowerCase().includes(kw)
      || String(s.id) === kw
      || (STRATEGY_LABEL[s.strategy] || s.strategy || '').toLowerCase().includes(kw));
  }, [summaries, keyword]);

  return (
    <>
      {summaries.length > 0 && (
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Input.Search
            placeholder="搜索需求文档 / 策略 / 任务 ID"
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 260 }}
          />
        </div>
      )}
      <Table
        rowKey="id"
        loading={loading}
        dataSource={filteredSummaries}
        columns={columns}
        pagination={filteredSummaries.length > 10 ? { pageSize: 10 } : false}
        locale={{ emptyText: keyword ? '没有匹配的生成记录' : '暂无生成记录，去「AI 用例生成」发起第一次生成' }}
      />

      <Drawer
        title={activeSummary ? `生成记录 #${activeSummary.id} · ${activeSummary.document_title || '未知文档'}` : ''}
        open={!!activeSummary}
        onClose={closeDetail}
        width={880}
        extra={
          <Space>
            {pendingCount > 0 && (
              <Link to={`/projects/${projectId}/generate?task=${activeSummary?.id}`}>
                <Button type="primary">继续评审 ({pendingCount})</Button>
              </Link>
            )}
            {(detail?.review_stats?.adopted || 0) > 0 && (
              <Tooltip title={`用本次已采纳的 ${detail.review_stats.adopted} 条用例创建测试任务`}>
                <Button icon={<PlayCircleOutlined />} onClick={() => openCreateRun(activeSummary)}>
                  创建测试任务
                </Button>
              </Tooltip>
            )}
            <Dropdown
              menu={{
                items: [
                  { key: 'xlsx', label: '导出用例（.xlsx）' },
                  { key: 'md', label: '导出用例（.md）' },
                ],
                onClick: ({ key }) => handleExport(key),
              }}
              disabled={!detail?.drafts?.length}
            >
              <Button loading={exporting} disabled={!detail?.drafts?.length}>导出用例</Button>
            </Dropdown>
          </Space>
        }
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : detail && (
          <>
            {detail.status === 'failed' && detail.error_message && (
              <div style={{ marginBottom: 16, padding: 12, background: '#fef2f2', borderRadius: 8, color: '#dc2626' }}>
                {detail.error_message}
              </div>
            )}
            {detail.status === 'budget_exhausted' && (
              <div style={{ marginBottom: 16, padding: 12, background: '#fffbeb', borderRadius: 8, color: '#b45309' }}>
                本轮预算已用尽，已保留完成草稿；可从检查点恢复继续生成。
              </div>
            )}

            {agentRun && (
              <div style={{ marginBottom: 16, padding: 16, background: '#f8fafc', borderRadius: 8 }}>
                <Space wrap style={{ marginBottom: runEvents.length || collaboration ? 12 : 0 }}>
                  <Text strong>Runtime V2</Text>
                  <Tag color={runStatusPresentation(agentRun.status, agentRun.stop_reason).color}>
                    {runStatusPresentation(agentRun.status, agentRun.stop_reason).label}
                  </Tag>
                  {collaboration && <Text type="secondary">候选 {collaboration.candidate_count}</Text>}
                  {collaboration && <Text type="secondary">选中 {collaboration.disposition_counts?.selected || 0}</Text>}
                  {collaboration && <Text type="secondary">合并重复 {collaboration.disposition_counts?.merged_duplicate || 0}</Text>}
                  {collaboration && (
                    <Text type="secondary">
                      Warning {Object.values(collaboration.warning_counts_by_agent || {}).reduce((sum, count) => sum + count, 0)}
                    </Text>
                  )}
                  {agentRun.attempt_count > 0 && <Text type="secondary">尝试 {agentRun.attempt_count}/{agentRun.max_attempts}</Text>}
                  {['queued', 'running', 'waiting_human'].includes(agentRun.status) && (
                    <Button size="small" danger icon={<StopOutlined />} loading={runActionLoading} onClick={handleRunCancel}>
                      取消运行
                    </Button>
                  )}
                  {['failed', 'cancelled', 'budget_exhausted'].includes(agentRun.status) && (
                    <Button size="small" icon={<ReloadOutlined />} loading={runActionLoading} onClick={handleRunRetry}>
                      恢复重试
                    </Button>
                  )}
                </Space>
                {collaboration && agentMetricRows(collaboration).length > 0 && (
                  <Space wrap style={{ display: 'flex', marginBottom: 14 }}>
                    {agentMetricRows(collaboration).map(row => (
                      <Tag key={row.agent} style={{ padding: '4px 8px' }}>
                        {row.label} · 候选 {row.candidates} · 参与采纳 {row.adopted}
                        {row.warnings > 0 ? ` · Warning ${row.warnings}` : ''}
                      </Tag>
                    ))}
                  </Space>
                )}
                {runEvents.length > 0 && (
                  <Timeline
                    items={runEvents.map((event) => {
                      const view = describeRuntimeEvent(event);
                      return {
                        color: view.color,
                        children: (
                          <div>
                            <Text>{view.title}</Text>
                            <Text type="secondary" style={{ marginLeft: 8 }}>{new Date(event.created_at).toLocaleTimeString()}</Text>
                            {view.summary && <div style={{ color: '#64748b', marginTop: 2 }}>{view.summary}</div>}
                          </div>
                        ),
                      };
                    })}
                  />
                )}
                {(collaboration?.candidates || []).length > 0 && (
                  <Table
                    rowKey="id"
                    size="small"
                    columns={candidateColumns}
                    dataSource={collaboration.candidates}
                    pagination={false}
                    style={{ marginTop: 8 }}
                  />
                )}
              </div>
            )}

            {detail.quality_report && (
              <div className="quality-stats" style={{ marginBottom: 16 }}>
                <div className="quality-stat"><div className="quality-stat-value">{detail.quality_report.total_cases}</div><div className="quality-stat-label">总计</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#16a34a' }}>{detail.review_stats?.adopted ?? 0}</div><div className="quality-stat-label">已采纳</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#dc2626' }}>{detail.review_stats?.rejected ?? 0}</div><div className="quality-stat-label">已驳回</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#ea580c' }}>{detail.review_stats?.pending ?? 0}</div><div className="quality-stat-label">未处理</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#0F766E' }}>{detail.quality_report.coverage_rate}%</div><div className="quality-stat-label">覆盖率</div></div>
                {detail.quality_report.avg_judge_score != null && (
                  <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#22A3A6' }}>{detail.quality_report.avg_judge_score}</div><div className="quality-stat-label">AI 均分</div></div>
                )}
                {detail.tokens_used > 0 && (
                  <div className="quality-stat"><div className="quality-stat-value">{detail.tokens_used >= 1000 ? `${(detail.tokens_used / 1000).toFixed(1)}k` : detail.tokens_used}</div><div className="quality-stat-label">Token</div></div>
                )}
              </div>
            )}

            {detail.quality_report?.suggestions && (
              <div style={{ marginBottom: 16, padding: '12px 16px', background: '#f8fafc', borderRadius: 8, whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.7, color: '#475569' }}>
                {detail.quality_report.suggestions}
              </div>
            )}

            <Table
              rowKey="id"
              size="small"
              dataSource={detail.drafts || []}
              columns={draftColumns}
              pagination={(detail.drafts || []).length > 20 ? { pageSize: 20 } : false}
              expandable={{ expandedRowRender: (r) => <CaseDetail record={r} /> }}
            />
          </>
        )}
      </Drawer>

      <Modal
        title="创建测试任务"
        open={!!runTarget}
        onOk={handleCreateRun}
        onCancel={() => { setRunTarget(null); runForm.resetFields(); }}
        okText="创建并开始执行"
        cancelText="取消"
        confirmLoading={runCreating}
      >
        <div style={{ marginBottom: 12, fontSize: 13, color: '#646A73' }}>
          将生成记录 #{runTarget?.id} 已采纳入库的 {runTarget?.review_stats?.adopted || 0} 条用例加入测试任务的首个批次
        </div>
        <Form form={runForm} layout="vertical">
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="batch_name" label="首个批次" rules={[{ required: true, message: '请输入批次名称' }]}>
            <AutoComplete
              options={BATCH_PRESETS.map((v) => ({ value: v }))}
              placeholder="选择或输入批次名称"
              maxLength={100}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
