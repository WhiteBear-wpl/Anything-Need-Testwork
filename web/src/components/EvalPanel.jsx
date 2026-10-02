import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, App, Button, Card, Checkbox, Drawer, Form, Input, Modal, Popconfirm, Progress,
  Segmented, Select, Space, Spin, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import { DiffOutlined, PlayCircleOutlined, PlusOutlined } from '@ant-design/icons';
import {
  createEvalRun, createEvalSample, deleteEvalRun, deleteEvalSample,
  dismissFailureCandidate, getEvalRuns, getEvalSamples, getEvalTask, getFailureCandidates,
  promoteFailureCandidate, setEvalRunBaseline, updateEvalSample,
} from '../services/api';
import EvalRunCompare from './EvalRunCompare';
import EvalScorecard from './EvalScorecard';
import { QUALITY_COLOR, QUALITY_LABEL, TYPE_LABEL, parseJudgeIssues } from '../pages/generate/constants';
import { CaseDetail, judgeScoreCell, priorityTag } from '../pages/generate/DetailPanels';
import { presentDualTrackSummary, presentScorecard } from '../pages/evaluation/scorecardPresentation';

const { Text } = Typography;

const RUN_STATUS = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '运行中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
};

// 文本框里一行一个测试点：`测试点描述 | 关键词1,关键词2`
function checkpointsToText(checkpoints) {
  return (checkpoints || [])
    .map(cp => (cp.keywords?.length ? `${cp.text} | ${cp.keywords.join(',')}` : cp.text))
    .join('\n');
}

function textToCheckpoints(text) {
  return (text || '')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const [t, kw] = line.split('|');
      return {
        text: t.trim(),
        keywords: (kw || '').split(/[,，]/).map(k => k.trim()).filter(Boolean),
      };
    })
    .filter(cp => cp.text);
}

function pct(v) {
  return v === null || v === undefined ? '—' : `${v}%`;
}

function metricColor(v, good = 70, mid = 40) {
  if (v === null || v === undefined) return '#94a3b8';
  return v >= good ? '#16a34a' : v >= mid ? '#ea580c' : '#dc2626';
}

export default function EvalPanel() {
  const { message } = App.useApp();
  const [view, setView] = useState('runs');
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);

  const [sampleModalOpen, setSampleModalOpen] = useState(false);
  const [editingSample, setEditingSample] = useState(null);
  const [sampleForm] = Form.useForm();
  const [promoteForm] = Form.useForm();
  const [promotingCandidate, setPromotingCandidate] = useState(null);

  const [runModalOpen, setRunModalOpen] = useState(false);
  const [runForm] = Form.useForm();

  const [detailRun, setDetailRun] = useState(null);
  const [compareIds, setCompareIds] = useState([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [caseResult, setCaseResult] = useState(null);
  const [caseTask, setCaseTask] = useState(null);
  const [caseLoading, setCaseLoading] = useState(false);
  const [caseFilter, setCaseFilter] = useState('problem');
  const pollRef = useRef(null);

  const loadAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [s, r, c] = await Promise.all([getEvalSamples(), getEvalRuns(), getFailureCandidates()]);
      setSamples(s);
      setRuns(r);
      setCandidates(c);
      return r;
    } catch {
      if (!silent) message.error('加载评测数据失败');
      return [];
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // 有运行中的评测时轮询
  useEffect(() => {
    const hasActive = runs.some(r => ['pending', 'running'].includes(r.status));
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        const latest = await loadAll(true);
        if (!latest.some(r => ['pending', 'running'].includes(r.status))) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }, 3000);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [runs, loadAll]);

  // ---------- 样本 ----------

  const openSampleModal = (sample = null) => {
    setEditingSample(sample);
    sampleForm.setFieldsValue(sample
      ? { title: sample.title, content: sample.content, checkpoints: checkpointsToText(sample.checkpoints) }
      : { title: '', content: '', checkpoints: '' });
    setSampleModalOpen(true);
  };

  const saveSample = async () => {
    const values = await sampleForm.validateFields();
    const payload = {
      title: values.title,
      content: values.content,
      checkpoints: textToCheckpoints(values.checkpoints),
    };
    try {
      if (editingSample) {
        await updateEvalSample(editingSample.id, payload);
      } else {
        await createEvalSample(payload);
      }
      message.success('已保存');
      setSampleModalOpen(false);
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '保存失败');
    }
  };

  const removeSample = async (sample) => {
    try {
      await deleteEvalSample(sample.id);
      message.success('已删除');
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '删除失败');
    }
  };

  const openPromoteCandidate = (candidate) => {
    setPromotingCandidate(candidate);
    promoteForm.setFieldsValue({ title: candidate.title || '失败用例回归', checkpoints: '' });
  };

  const confirmPromoteCandidate = async () => {
    const values = await promoteForm.validateFields();
    try {
      await promoteFailureCandidate(promotingCandidate.id, {
        title: values.title,
        checkpoints: textToCheckpoints(values.checkpoints),
      });
      message.success('已提升为评测样本');
      setPromotingCandidate(null);
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '提升失败');
    }
  };

  const dismissCandidate = async (candidate) => {
    try {
      await dismissFailureCandidate(candidate.id);
      message.success('已忽略候选');
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  // ---------- 运行 ----------

  const startRun = async () => {
    const values = await runForm.validateFields();
    try {
      await createEvalRun(values);
      message.success('评测已启动，请稍候');
      setRunModalOpen(false);
      runForm.resetFields();
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '启动失败');
    }
  };

  const markBaseline = async (run) => {
    try {
      await setEvalRunBaseline(run.id);
      message.success('已设为该样本集基线');
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '设置基线失败');
    }
  };

  const removeRun = async (run) => {
    try {
      await deleteEvalRun(run.id);
      message.success('已删除');
      loadAll();
    } catch (err) {
      message.error(err.response?.data?.detail || '删除失败');
    }
  };

  // ---------- 用例明细下钻 ----------

  const isProblemDraft = (d) => {
    const judge = parseJudgeIssues(d.judge_issues);
    return (d.judge_score != null && d.judge_score < 4)
      || !!judge?.hallucination
      || d.quality_status !== 'pass';
  };

  const openCaseDetail = async (result) => {
    setCaseResult(result);
    setCaseTask(null);
    setCaseFilter('problem');
    setCaseLoading(true);
    try {
      setCaseTask(await getEvalTask(result.task_id));
    } catch {
      message.error('加载用例明细失败');
      setCaseResult(null);
    } finally {
      setCaseLoading(false);
    }
  };

  const problemDrafts = useMemo(
    () => (caseTask?.drafts || []).filter(isProblemDraft),
    [caseTask],
  );
  const shownDrafts = caseFilter === 'problem' ? problemDrafts : (caseTask?.drafts || []);

  const caseColumns = [
    { title: '用例标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    { title: '类型', dataIndex: 'case_type', width: 80, render: v => <Tag>{TYPE_LABEL[v] || v}</Tag> },
    { title: '优先级', dataIndex: 'priority', width: 80, render: priorityTag },
    { title: '质量', dataIndex: 'quality_status', width: 90, render: v => <Tag color={QUALITY_COLOR[v]}>{QUALITY_LABEL[v] || v}</Tag> },
    { title: 'AI 评分', dataIndex: 'judge_score', width: 100, render: judgeScoreCell },
  ];

  const sampleColumns = [
    { title: '样本标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    {
      title: '标准测试点',
      dataIndex: 'checkpoints',
      width: 120,
      render: v => `${(v || []).length} 个`,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: v => new Date(v).toLocaleString() },
    {
      title: '操作',
      width: 140,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" onClick={() => openSampleModal(r)}>编辑</Button>
          <Popconfirm title="确定删除该样本？" onConfirm={() => removeSample(r)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const candidateColumns = [
    { title: '功能点', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    { title: '失败码', dataIndex: 'failure_code', width: 180, render: value => <Tag color="orange">{value || 'UNKNOWN'}</Tag> },
    { title: '状态', dataIndex: 'status', width: 100, render: value => <Tag>{value}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: value => new Date(value).toLocaleString() },
    {
      title: '操作', width: 160,
      render: (_, candidate) => candidate.status === 'pending' ? (
        <Space>
          <Button type="link" size="small" onClick={() => openPromoteCandidate(candidate)}>提升为样本</Button>
          <Popconfirm title="忽略这个失败候选？" onConfirm={() => dismissCandidate(candidate)}>
            <Button type="link" size="small" danger>忽略</Button>
          </Popconfirm>
        </Space>
      ) : <Text type="secondary">已处理</Text>,
    },
  ];

  const runColumns = [
    { title: '标签', dataIndex: 'label', width: 160, render: (v, r) => <Space><Text strong>{v}</Text>{r.is_baseline && <Tag color="blue">基线</Tag>}</Space> },
    {
      title: '状态',
      dataIndex: 'status',
      width: 200,
      render: (v, r) => {
        const s = RUN_STATUS[v] || { label: v, color: 'default' };
        if (v !== 'running' && v !== 'pending') return <Tag color={s.color}>{s.label}</Tag>;
        const current = (r.results || []).find(x => x.status === 'running');
        const done = (r.results || []).filter(x => ['completed', 'failed'].includes(x.status)).length;
        return (
          <div>
            <Progress percent={r.progress} size="small" style={{ width: 160 }} />
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
              {current
                ? `正在评测（${done + 1}/${r.results.length}）：${current.sample_title}`
                : '排队中…'}
            </div>
            {r.stage && (
              <div style={{ fontSize: 12, color: '#0F766E', marginTop: 2 }}>{r.stage}</div>
            )}
          </div>
        );
      },
    },
    { title: '样本', dataIndex: ['metrics', 'sample_count'], width: 70, render: (v, r) => v ?? r.results?.length ?? '—' },
    {
      title: '成功率',
      dataIndex: ['metrics', 'success_rate'],
      width: 90,
      render: v => <span style={{ color: metricColor(v, 99, 80) }}>{pct(v)}</span>,
    },
    {
      title: '可用率',
      dataIndex: ['metrics', 'usable_rate'],
      width: 90,
      render: v => (
        <Tooltip title="AI Judge 综合分 ≥ 4 的用例占比">
          <span style={{ color: metricColor(v), fontWeight: 600 }}>{pct(v)}</span>
        </Tooltip>
      ),
    },
    {
      title: '召回率',
      dataIndex: ['metrics', 'recall'],
      width: 90,
      render: v => (
        <Tooltip title="标准测试点被生成用例覆盖的比例">
          <span style={{ color: metricColor(v), fontWeight: 600 }}>{pct(v)}</span>
        </Tooltip>
      ),
    },
    {
      title: '重复率',
      dataIndex: ['metrics', 'duplicate_rate'],
      width: 90,
      render: v => <span style={{ color: v > 10 ? '#dc2626' : '#475569' }}>{pct(v)}</span>,
    },
    {
      title: '幻觉',
      dataIndex: ['metrics', 'hallucination_count'],
      width: 70,
      render: v => (v > 0 ? <Tag color="red">{v}</Tag> : v === 0 ? '0' : '—'),
    },
    { title: 'AI 均分', dataIndex: ['metrics', 'avg_judge_score'], width: 90, render: v => v ?? '—' },
    {
      title: 'Token',
      dataIndex: ['metrics', 'total_tokens'],
      width: 90,
      render: v => (v ? (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v) : '—'),
    },
    { title: '时间', dataIndex: 'created_at', width: 160, render: v => new Date(v).toLocaleString() },
    {
      title: '操作',
      width: 130,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" onClick={() => setDetailRun(r)}>详情</Button>
          <Button type="link" size="small" disabled={r.status !== 'completed' || r.is_baseline} onClick={() => markBaseline(r)}>设为基线</Button>
          <Popconfirm title="确定删除该次运行？" onConfirm={() => removeRun(r)}>
            <Button type="link" size="small" danger disabled={r.status === 'running'}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const resultColumns = [
    { title: '样本', dataIndex: 'sample_title', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: v => {
        const map = {
          completed: ['success', '成功'],
          failed: ['error', '失败'],
          running: ['processing', '运行中'],
        };
        const [color, label] = map[v] || ['default', '待运行'];
        return <Tag color={color}>{label}</Tag>;
      },
    },
    { title: '用例数', dataIndex: ['metrics', 'total_cases'], width: 80, render: v => v ?? '—' },
    { title: '可用率', dataIndex: ['metrics', 'usable_rate'], width: 90, render: pct },
    { title: '召回率', dataIndex: ['metrics', 'recall'], width: 90, render: pct },
    { title: '重复', dataIndex: ['metrics', 'duplicate_count'], width: 70, render: v => v ?? '—' },
    { title: '幻觉', dataIndex: ['metrics', 'hallucination_count'], width: 70, render: v => v ?? '—' },
    { title: 'AI 均分', dataIndex: ['metrics', 'avg_judge_score'], width: 90, render: v => v ?? '—' },
    {
      title: '双轨', width: 110,
      render: (_, r) => {
        const status = presentScorecard(r.scorecard).status;
        return r.scorecard ? <Tag color={status.color}>{status.label}</Tag> : '—';
      },
    },
    { title: '耗时', dataIndex: ['metrics', 'duration_sec'], width: 80, render: v => (v ? `${v}s` : '—') },
    {
      title: '操作',
      width: 100,
      render: (_, r) => (
        <Button type="link" size="small" disabled={!r.task_id} onClick={() => openCaseDetail(r)}>
          查看用例
        </Button>
      ),
    },
  ];

  return (
    <>
      <Tabs
        className="task-list-tabs"
        activeKey={view}
        onChange={setView}
        items={[
          { key: 'runs', label: `评测运行 (${runs.length})` },
          { key: 'samples', label: `评测样本 (${samples.length})` },
          { key: 'candidates', label: `失败候选 (${candidates.filter(c => c.status === 'pending').length})` },
        ]}
        tabBarExtraContent={view === 'samples' ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openSampleModal()}>新建样本</Button>
        ) : (
          <Space>
            <Button
              icon={<DiffOutlined />}
              disabled={compareIds.length < 2}
              onClick={() => setCompareOpen(true)}
            >
              对比选中 ({compareIds.length})
            </Button>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              disabled={!samples.length}
              onClick={() => {
                runForm.setFieldsValue({ label: '', strategy: 'full', sample_ids: samples.map(s => s.id) });
                setRunModalOpen(true);
              }}
            >
              发起评测
            </Button>
          </Space>
        )}
      />

      <Card className="surface-card">
      {view === 'samples' ? (
        <Table
          rowKey="id"
          loading={loading}
          dataSource={samples}
          columns={sampleColumns}
          pagination={false}
          locale={{ emptyText: '暂无评测样本。样本 = 固化的需求内容 + 人工整理的标准测试点，用于回归对比' }}
        />
      ) : view === 'candidates' ? (
        <Table
          rowKey="id"
          loading={loading}
          dataSource={candidates}
          columns={candidateColumns}
          pagination={false}
          locale={{ emptyText: '暂无失败候选。最终未修复的生成失败会自动出现在这里。' }}
        />
      ) : (
        <Table
          rowKey="id"
          loading={loading}
          dataSource={runs}
          columns={runColumns}
          pagination={false}
          scroll={{ x: 1200 }}
          rowSelection={{
            selectedRowKeys: compareIds,
            onChange: (keys) => setCompareIds(keys.slice(-3)), // 最多对比 3 次运行
            getCheckboxProps: (r) => ({ disabled: r.status !== 'completed' }),
            columnTitle: <Tooltip title="勾选 2~3 次已完成的运行进行对比">选</Tooltip>,
          }}
          locale={{ emptyText: '暂无评测运行。先录入样本，再发起评测得到基线指标' }}
        />
      )}

      <EvalRunCompare
        runs={runs.filter(r => compareIds.includes(r.id))}
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
      />

      <Modal
        title={editingSample ? '编辑评测样本' : '新建评测样本'}
        open={sampleModalOpen}
        onOk={saveSample}
        onCancel={() => setSampleModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <Form form={sampleForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="title" label="样本标题" rules={[{ required: true, message: '请填写标题' }]}>
            <Input placeholder="如：登录模块需求 v1" maxLength={100} />
          </Form.Item>
          <Form.Item name="content" label="需求内容（固化快照，保证每次评测输入一致）" rules={[{ required: true, message: '请填写需求内容' }]}>
            <Input.TextArea rows={6} placeholder="粘贴需求文档内容" />
          </Form.Item>
          <Form.Item
            name="checkpoints"
            label="标准测试点（一行一个，可选加关键词：测试点描述 | 关键词1,关键词2）"
            tooltip="人工整理的应覆盖场景清单，用于计算召回率。关键词用于快速匹配，留空则整句匹配"
          >
            <Input.TextArea rows={6} placeholder={'密码错误提示登录失败 | 密码错误,失败\n验证码 60 秒内有效 | 验证码,60'} />
          </Form.Item>
          <Alert
            type="warning"
            showIcon
            message="请按每行一个测试点的格式填写"
            description="仅支持“测试点描述 | 关键词1,关键词2”。不支持 Markdown 表格；表格行会被识别为空，导致测试点无法导入，召回率无法计算。"
            style={{ marginTop: -8 }}
          />
        </Form>
      </Modal>

      <Modal
        title="提升失败候选为回归样本"
        open={!!promotingCandidate}
        onOk={confirmPromoteCandidate}
        onCancel={() => setPromotingCandidate(null)}
        okText="提升"
        cancelText="取消"
        width={600}
      >
        <Form form={promoteForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="title" label="样本标题" rules={[{ required: true, message: '请填写标题' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            name="checkpoints"
            label="标准测试点"
            rules={[{
              validator: (_, value) => textToCheckpoints(value).length
                ? Promise.resolve()
                : Promise.reject(new Error('至少填写一个测试点')),
            }]}
          >
            <Input.TextArea rows={5} placeholder="一行一个测试点；可选：测试点 | 关键词1,关键词2" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="发起评测运行"
        open={runModalOpen}
        onOk={startRun}
        onCancel={() => setRunModalOpen(false)}
        okText="开始运行"
        cancelText="取消"
        width={520}
      >
        <Form form={runForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="label" label="运行标签（用于对比，如 baseline / prompt-v2）" rules={[{ required: true, message: '请填写标签' }]}>
            <Input placeholder="baseline" maxLength={50} />
          </Form.Item>
          <Form.Item name="strategy" label="生成策略">
            <Select options={[{ label: '完整用例', value: 'full' }, { label: '快速冒烟', value: 'quick' }]} />
          </Form.Item>
          <Form.Item name="sample_ids" label="评测样本" rules={[{ required: true, message: '请选择样本' }]}>
            <Checkbox.Group
              style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
              options={samples.map(s => ({ label: s.title, value: s.id }))}
            />
          </Form.Item>
        </Form>
        <div style={{ color: '#94a3b8', fontSize: 12 }}>
          评测会对每个样本走完整生成链路（真实调用 LLM，消耗 Token），产生的数据不会进入业务列表。
        </div>
      </Modal>

      <Drawer
        title={detailRun ? `评测运行 · ${detailRun.label}` : ''}
        open={!!detailRun}
        onClose={() => setDetailRun(null)}
        width={860}
      >
        {detailRun && (
          <>
            {detailRun.status === 'failed' && detailRun.error_message && (
              <div style={{ marginBottom: 16, padding: 12, background: '#fef2f2', borderRadius: 8, color: '#dc2626' }}>
                {detailRun.error_message}
              </div>
            )}
            {detailRun.metrics?.sample_count != null && (
              <div className="quality-stats" style={{ marginBottom: 16 }}>
                <div className="quality-stat"><div className="quality-stat-value">{detailRun.metrics.total_cases}</div><div className="quality-stat-label">生成用例</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: metricColor(detailRun.metrics.usable_rate) }}>{pct(detailRun.metrics.usable_rate)}</div><div className="quality-stat-label">可用率</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: metricColor(detailRun.metrics.recall) }}>{pct(detailRun.metrics.recall)}</div><div className="quality-stat-label">召回率</div></div>
                <div className="quality-stat"><div className="quality-stat-value">{pct(detailRun.metrics.duplicate_rate)}</div><div className="quality-stat-label">重复率</div></div>
                <div className="quality-stat"><div className="quality-stat-value" style={{ color: detailRun.metrics.hallucination_count > 0 ? '#dc2626' : undefined }}>{detailRun.metrics.hallucination_count ?? '—'}</div><div className="quality-stat-label">疑似幻觉</div></div>
              </div>
            )}
            {detailRun.dual_track_summary && (
              <Card size="small" title="双轨评测汇总" style={{ marginBottom: 16 }}>
                <Space wrap>
                  {presentDualTrackSummary(detailRun.dual_track_summary).items.map(item => (
                    <Tag key={item.key}>{item.label}: {item.value}</Tag>
                  ))}
                  {Object.entries(presentDualTrackSummary(detailRun.dual_track_summary).statusCounts).map(([status, count]) => (
                    <Tag key={status}>{presentScorecard({ assessment_status: status }).status.label}: {count}</Tag>
                  ))}
                </Space>
              </Card>
            )}
            <Table
              rowKey="id"
              size="small"
              dataSource={detailRun.results || []}
              columns={resultColumns}
              pagination={false}
              expandable={{
                expandedRowRender: (result) => <EvalScorecard scorecard={result.scorecard} />,
                rowExpandable: (result) => !!result.scorecard,
              }}
            />
          </>
        )}
      </Drawer>

      <Drawer
        title={caseResult ? `用例明细 · ${caseResult.sample_title}` : ''}
        open={!!caseResult}
        onClose={() => setCaseResult(null)}
        width={780}
      >
        {caseLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : caseTask && (
          <>
            {(caseResult?.metrics?.uncovered_checkpoints || []).length > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message={`有 ${caseResult.metrics.uncovered_checkpoints.length} 个标准测试点未被覆盖`}
                description={
                  <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                    {caseResult.metrics.uncovered_checkpoints.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                }
              />
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Segmented
                value={caseFilter}
                onChange={setCaseFilter}
                options={[
                  { label: `问题用例 (${problemDrafts.length})`, value: 'problem' },
                  { label: `全部 (${caseTask.drafts?.length || 0})`, value: 'all' },
                ]}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                问题用例 = AI 评分低于 4 / 疑似幻觉 / 规则质检未通过；展开行可见具体原因
              </Text>
            </div>

            {caseFilter === 'problem' && !problemDrafts.length ? (
              <Alert type="success" showIcon message="本样本没有问题用例，全部通过质检且 AI 评分不低于 4 分" />
            ) : (
              <Table
                key={caseFilter}
                rowKey="id"
                size="small"
                dataSource={shownDrafts}
                columns={caseColumns}
                pagination={shownDrafts.length > 20 ? { pageSize: 20 } : false}
                expandable={{
                  expandedRowRender: (r) => <CaseDetail record={r} />,
                  defaultExpandedRowKeys: caseFilter === 'problem' ? problemDrafts.slice(0, 3).map(d => d.id) : [],
                }}
              />
            )}
          </>
        )}
      </Drawer>
      </Card>
    </>
  );
}
