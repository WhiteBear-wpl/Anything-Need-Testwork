import {
  ApartmentOutlined, ArrowLeftOutlined, BugOutlined, CheckCircleOutlined, DeleteOutlined,
  EllipsisOutlined, FolderOutlined, PlusOutlined, RedoOutlined, UnorderedListOutlined,
} from '@ant-design/icons';
import {
  App, AutoComplete, Button, Card, Checkbox, Dropdown, Empty, Form, Input, Modal, Progress,
  Radio, Segmented, Select, Space, Spin, Table, Tabs, Tag, Tooltip, Tree,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import TestCaseMindmap from '../components/TestCaseMindmap';
import {
  batchMarkBatchCases, createBatch, deleteBatch, getBatchDetail, getTaskDefects,
  getTestcases, getTestTaskDetail, markBatchCase, updateBatch, updateTestTask,
} from '../services/api';
import { stepsToText } from '../utils/caseText';
import { BATCH_PRESETS, RESULT_COLOR, RESULT_LABEL, RESULT_TAG_COLOR, RUN_STATUS_LABEL } from '../utils/runResult';

const DEFAULT_MODULE = '未分类';
const DEFAULT_FEATURE = '未关联功能点';

function normalizeModule(v) { return v?.trim() || DEFAULT_MODULE; }
function normalizeFeature(v) { return v?.trim() || DEFAULT_FEATURE; }

function summarize(list) {
  return {
    total: list.length,
    passed: list.filter((c) => c.result === 'passed').length,
    failed: list.filter((c) => c.result === 'failed').length,
    blocked: list.filter((c) => c.result === 'blocked').length,
    pending: list.filter((c) => c.result === 'pending').length,
  };
}

function NodeBadge({ list }) {
  const s = summarize(list);
  return (
    <span className="run-tree-badge">
      {s.passed > 0 && <span style={{ color: RESULT_COLOR.passed }}>{s.passed}✓</span>}
      {s.failed > 0 && <span style={{ color: RESULT_COLOR.failed }}>{s.failed}✗</span>}
      {s.blocked > 0 && <span style={{ color: RESULT_COLOR.blocked }}>{s.blocked}⊘</span>}
      {s.pending > 0 && <span style={{ color: RESULT_COLOR.pending }}>{s.pending}○</span>}
    </span>
  );
}

function buildTree(cases) {
  const modules = {};
  cases.forEach((c) => {
    const mod = normalizeModule(c.module);
    const feat = normalizeFeature(c.feature);
    if (!modules[mod]) modules[mod] = {};
    if (!modules[mod][feat]) modules[mod][feat] = [];
    modules[mod][feat].push(c);
  });
  return [{
    key: 'all',
    title: <span className="run-tree-title">全部用例 ({cases.length})<NodeBadge list={cases} /></span>,
    children: Object.entries(modules).map(([mod, feats]) => {
      const modCases = Object.values(feats).flat();
      return {
        key: `m:${mod}`,
        icon: <FolderOutlined />,
        title: <span className="run-tree-title">{mod}<NodeBadge list={modCases} /></span>,
        children: Object.entries(feats).map(([feat, list]) => ({
          key: `m:${mod}|f:${feat}`,
          isLeaf: true,
          title: <span className="run-tree-title">{feat}<NodeBadge list={list} /></span>,
        })),
      };
    }),
  }];
}

function filterByKey(cases, key) {
  if (!key || key === 'all') return cases;
  const [modPart, featPart] = key.split('|');
  const mod = modPart.slice(2);
  if (!featPart) return cases.filter((c) => normalizeModule(c.module) === mod);
  const feat = featPart.slice(2);
  return cases.filter((c) => normalizeModule(c.module) === mod && normalizeFeature(c.feature) === feat);
}

function CaseDetail({ record }) {
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
      {record.note && (
        <div className="case-detail-row">
          <span className="case-detail-label">执行备注</span>{record.note}
        </div>
      )}
      {record.defect_ref && (
        <div className="case-detail-row">
          <span className="case-detail-label">缺陷单号</span>{record.defect_ref}
        </div>
      )}
    </div>
  );
}

const priorityTag = (p) => {
  const cls = p === 'P0' ? 'tag-p0' : p === 'P1' ? 'tag-p1' : 'tag-p2';
  return <Tag className={cls} variant="filled">{p}</Tag>;
};

function BatchPanel({ pid, taskId, batch, onBatchChange, onDeleteBatch, deletable }) {
  const { message, modal } = App.useApp();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState('list');
  const [selectedKey, setSelectedKey] = useState('all');
  const [resultFilter, setResultFilter] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [markTarget, setMarkTarget] = useState(null); // { batchCases: [], result: 'failed'|'blocked' }
  const [markSaving, setMarkSaving] = useState(false);
  const [markForm] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setDetail(await getBatchDetail(pid, taskId, batch.id));
    } catch {
      message.error('加载批次失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [pid, taskId, batch.id]);

  const cases = detail?.cases || [];
  const stats = detail?.stats;
  const treeData = useMemo(() => buildTree(cases), [cases]);
  const filteredCases = useMemo(() => {
    let list = filterByKey(cases, selectedKey);
    if (resultFilter !== 'all') list = list.filter((c) => c.result === resultFilter);
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      list = list.filter((c) =>
        c.title?.toLowerCase().includes(kw)
        || c.module?.toLowerCase().includes(kw)
        || c.feature?.toLowerCase().includes(kw));
    }
    return list;
  }, [cases, selectedKey, resultFilter, keyword]);

  const applyLocal = (ids, result, note = '', defectRef = '', batchStats = null) => {
    setDetail((prev) => ({
      ...prev,
      ...(batchStats ? { stats: batchStats } : {}),
      cases: prev.cases.map((c) => (ids.includes(c.id)
        ? {
          ...c,
          result,
          note: note || (ids.length > 1 ? c.note : note),
          defect_ref: defectRef || (ids.length > 1 ? c.defect_ref : defectRef),
          executed_at: result === 'pending' ? null : new Date().toISOString(),
        }
        : c)),
    }));
    if (batchStats) onBatchChange({ ...batch, stats: batchStats });
  };

  const mark = async (batchCase, result) => {
    // 仅失败弹窗补充备注 / 缺陷；阻塞暂不强制提缺陷，直接标记
    if (result === 'failed') {
      markForm.setFieldsValue({ note: batchCase.note || '', defect_ref: batchCase.defect_ref || '' });
      setMarkTarget({ batchCases: [batchCase], result });
      return;
    }
    const keep = result === 'blocked'; // 阻塞保留已有备注 / 缺陷号
    const note = keep ? (batchCase.note || '') : '';
    const defectRef = keep ? (batchCase.defect_ref || '') : '';
    try {
      const updated = await markBatchCase(pid, taskId, batch.id, batchCase.id, { result, note, defect_ref: defectRef });
      applyLocal([batchCase.id], result, note, defectRef, updated.stats);
    } catch (err) {
      message.error(err?.response?.data?.detail || '标记失败');
    }
  };

  const batchMark = async (result) => {
    if (!selectedRowKeys.length) return;
    try {
      const updated = await batchMarkBatchCases(pid, taskId, batch.id, { batch_case_ids: selectedRowKeys, result });
      setDetail((prev) => ({
        ...prev,
        stats: updated.stats,
        cases: prev.cases.map((c) => (selectedRowKeys.includes(c.id)
          ? { ...c, result, executed_at: result === 'pending' ? null : new Date().toISOString() }
          : c)),
      }));
      onBatchChange({ ...batch, stats: updated.stats });
      setSelectedRowKeys([]);
      message.success(`已批量标记为「${RESULT_LABEL[result]}」`);
    } catch (err) {
      message.error(err?.response?.data?.detail || '批量标记失败');
    }
  };

  const handleMarkSubmit = async () => {
    const values = await markForm.validateFields();
    const { batchCases, result } = markTarget;
    setMarkSaving(true);
    try {
      let updated = null;
      for (const bc of batchCases) {
        updated = await markBatchCase(pid, taskId, batch.id, bc.id, {
          result,
          note: values.note || '',
          defect_ref: values.defect_ref || '',
        });
      }
      applyLocal(batchCases.map((c) => c.id), result, values.note || '', values.defect_ref || '', updated?.stats);
      setMarkTarget(null);
      markForm.resetFields();
    } catch (err) {
      message.error(err?.response?.data?.detail || '标记失败');
    } finally {
      setMarkSaving(false);
    }
  };

  const toggleBatchStatus = async () => {
    const next = detail.status === 'completed' ? 'in_progress' : 'completed';
    if (next === 'completed' && stats.pending > 0) {
      const ok = await new Promise((resolve) => {
        modal.confirm({
          title: '还有未执行的用例',
          content: `本批次仍有 ${stats.pending} 条用例未执行，确定要完成吗？`,
          okText: '完成批次',
          cancelText: '继续执行',
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!ok) return;
    }
    try {
      const updated = await updateBatch(pid, taskId, batch.id, { status: next });
      setDetail((prev) => ({ ...prev, status: updated.status }));
      onBatchChange({ ...batch, status: updated.status, stats: updated.stats });
      message.success(next === 'completed' ? '本批次已完成' : '已重新打开');
    } catch (err) {
      message.error(err?.response?.data?.detail || '操作失败');
    }
  };

  const resultButtons = (record) => (
    <Space size={4}>
      {['passed', 'failed', 'blocked', 'pending'].map((r) => (
        <Button
          key={r}
          size="small"
          className={`run-result-btn run-result-btn-${r}${record.result === r ? ' active' : ''}`}
          onClick={() => record.result !== r && mark(record, r)}
        >
          {RESULT_LABEL[r]}
        </Button>
      ))}
    </Space>
  );

  const columns = [
    { title: '用例标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    { title: '功能点', dataIndex: 'feature', width: 120, ellipsis: true, render: (v) => v || '—' },
    { title: '优先级', dataIndex: 'priority', width: 64, render: priorityTag },
    {
      title: '结果',
      dataIndex: 'result',
      width: 236,
      render: (_, record) => resultButtons(record),
    },
    {
      title: '备注 / 缺陷',
      key: 'note',
      width: 130,
      ellipsis: true,
      render: (_, r) => {
        if (!r.note && !r.defect_ref) return <span style={{ color: '#cbd5e1' }}>—</span>;
        return (
          <Tooltip title={<>{r.note && <div>备注：{r.note}</div>}{r.defect_ref && <div>缺陷：{r.defect_ref}</div>}</>}>
            <span>{r.defect_ref ? <Tag color="red">{r.defect_ref}</Tag> : r.note}</span>
          </Tooltip>
        );
      },
    },
  ];

  if (loading || !detail) {
    return <Card className="surface-card"><div style={{ textAlign: 'center', padding: 60 }}><Spin /></div></Card>;
  }

  const batchMenu = {
    items: [
      {
        key: 'delete',
        icon: <DeleteOutlined />,
        label: '删除批次',
        danger: true,
        disabled: !deletable,
        onClick: () => onDeleteBatch(batch),
      },
    ],
  };

  return (
    <>
      <div className="run-detail-stats batch-stats-bar">
        <Tag color={detail.status === 'completed' ? 'success' : 'processing'}>
          {RUN_STATUS_LABEL[detail.status] || detail.status}
        </Tag>
        <div className="run-detail-progress">
          <Progress
            percent={stats.total ? Math.round((stats.executed / stats.total) * 100) : 0}
            success={{ percent: stats.pass_rate, strokeColor: RESULT_COLOR.passed }}
            strokeColor="#f59e0b"
            format={() => `通过率 ${stats.pass_rate}%`}
          />
        </div>
        <div className="run-detail-actions">
          <Button
            icon={detail.status === 'completed' ? <RedoOutlined /> : <CheckCircleOutlined />}
            onClick={toggleBatchStatus}
          >
            {detail.status === 'completed' ? '重新打开' : '完成批次'}
          </Button>
          <Dropdown menu={batchMenu} trigger={['click']}>
            <Button icon={<EllipsisOutlined />} />
          </Dropdown>
        </div>
      </div>

      <div className="library-layout">
        <Card className="surface-card library-tree-panel" title="功能点">
          <Tree
            showIcon
            defaultExpandAll
            selectedKeys={[selectedKey]}
            onSelect={(keys) => keys.length && setSelectedKey(keys[0])}
            treeData={treeData}
          />
        </Card>
        <Card
          className={`surface-card library-table-panel${viewMode === 'mindmap' ? ' library-mindmap-panel' : ''}`}
          title="执行清单"
          extra={(
            <div className="library-panel-extra">
              <Tag>{filteredCases.length} 条</Tag>
              <Segmented
                size="small"
                value={viewMode}
                onChange={setViewMode}
                options={[
                  { label: '列表', value: 'list', icon: <UnorderedListOutlined /> },
                  { label: '脑图', value: 'mindmap', icon: <ApartmentOutlined /> },
                ]}
              />
            </div>
          )}
        >
          {viewMode === 'list' ? (
            <>
              <Space wrap className="library-filter-bar">
                {selectedRowKeys.length > 0 && (
                  <Space size={4} className="run-batch-bar">
                    <span className="run-batch-label">批量标记 {selectedRowKeys.length} 条：</span>
                    <Button size="small" onClick={() => batchMark('passed')}>通过</Button>
                    <Button size="small" onClick={() => batchMark('failed')}>失败</Button>
                    <Button size="small" onClick={() => batchMark('blocked')}>阻塞</Button>
                    <Button size="small" onClick={() => batchMark('pending')}>重置</Button>
                  </Space>
                )}
                <Segmented
                  size="small"
                  value={resultFilter}
                  onChange={setResultFilter}
                  options={[
                    { label: '全部', value: 'all' },
                    ...['pending', 'passed', 'failed', 'blocked'].map((r) => ({
                      label: RESULT_LABEL[r],
                      value: r,
                    })),
                  ]}
                />
                <Input.Search
                  placeholder="搜索标题 / 模块 / 功能点"
                  allowClear
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  style={{ width: 220 }}
                />
              </Space>
              <Table
                rowKey="id"
                dataSource={filteredCases}
                columns={columns}
                pagination={{ pageSize: 20, showSizeChanger: true }}
                rowSelection={{
                  selectedRowKeys,
                  onChange: setSelectedRowKeys,
                }}
                expandable={{ expandedRowRender: (r) => <CaseDetail record={r} /> }}
                rowClassName={(r) => `run-row-${r.result}`}
              />
            </>
          ) : (
            <TestCaseMindmap
              cases={filteredCases}
              rootLabel={batch.name}
              executionMode
              showFullMapButton
              onMarkResult={mark}
            />
          )}
        </Card>
      </div>

      <Modal
        title={markTarget ? `标记为「${RESULT_LABEL[markTarget.result]}」` : ''}
        open={!!markTarget}
        onOk={handleMarkSubmit}
        onCancel={() => { setMarkTarget(null); markForm.resetFields(); }}
        okText="确定"
        cancelText="取消"
        confirmLoading={markSaving}
        width={480}
      >
        <Form form={markForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="note"
            label={markTarget?.result === 'blocked' ? '阻塞原因（可选）' : '失败备注（可选）'}
          >
            <Input.TextArea rows={3} maxLength={500} showCount />
          </Form.Item>
          <Form.Item name="defect_ref" label="缺陷单号 / 链接（可选）">
            <Input placeholder="例如：BUG-1024 或缺陷链接" maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function DefectsPanel({ pid, taskId, onJumpToBatch }) {
  const { message } = App.useApp();
  const [defects, setDefects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [includeBlocked, setIncludeBlocked] = useState(false);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    getTaskDefects(pid, taskId, includeBlocked)
      .then((list) => { if (!ignore) setDefects(list); })
      .catch(() => { if (!ignore) message.error('加载缺陷列表失败'); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [pid, taskId, includeBlocked]);

  const columns = [
    { title: '用例标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    {
      title: '模块 / 功能点',
      key: 'module',
      width: 180,
      ellipsis: true,
      render: (_, r) => [r.module, r.feature].filter(Boolean).join(' / ') || '—',
    },
    { title: '优先级', dataIndex: 'priority', width: 64, render: priorityTag },
    {
      title: '所属批次',
      dataIndex: 'batch_name',
      width: 110,
      render: (v, r) => (
        <a onClick={() => onJumpToBatch(r.batch_id)}>{v}</a>
      ),
    },
    {
      title: '结果',
      dataIndex: 'result',
      width: 72,
      render: (v) => <Tag color={RESULT_TAG_COLOR[v]}>{RESULT_LABEL[v]}</Tag>,
    },
    {
      title: '失败备注',
      dataIndex: 'note',
      ellipsis: true,
      render: (v) => v || <span style={{ color: '#cbd5e1' }}>—</span>,
    },
    {
      title: '缺陷单号',
      dataIndex: 'defect_ref',
      width: 140,
      ellipsis: true,
      render: (v) => {
        if (!v) return <span style={{ color: '#cbd5e1' }}>—</span>;
        return /^https?:\/\//.test(v)
          ? <a href={v} target="_blank" rel="noreferrer"><Tag color="red">{v}</Tag></a>
          : <Tag color="red">{v}</Tag>;
      },
    },
    {
      title: '执行时间',
      dataIndex: 'executed_at',
      width: 150,
      render: (v) => (v ? new Date(v).toLocaleString() : '—'),
    },
  ];

  return (
    <Card
      className="surface-card"
      title="缺陷列表"
      extra={(
        <Checkbox checked={includeBlocked} onChange={(e) => setIncludeBlocked(e.target.checked)}>
          含阻塞
        </Checkbox>
      )}
    >
      <Table
        rowKey="batch_case_id"
        loading={loading}
        dataSource={defects}
        columns={columns}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败用例，继续保持" /> }}
      />
    </Card>
  );
}

function buildCaseTree(cases) {
  const modules = {};
  cases.forEach((c) => {
    const mod = normalizeModule(c.module);
    const feat = normalizeFeature(c.feature);
    if (!modules[mod]) modules[mod] = {};
    if (!modules[mod][feat]) modules[mod][feat] = [];
    modules[mod][feat].push(c);
  });
  return Object.entries(modules).map(([mod, feats]) => ({
    key: `m:${mod}`,
    title: `${mod} (${Object.values(feats).reduce((n, list) => n + list.length, 0)})`,
    children: Object.entries(feats).map(([feat, list]) => ({
      key: `m:${mod}|f:${feat}`,
      title: `${feat} (${list.length})`,
      children: list.map((c) => ({ key: `c:${c.id}`, title: c.title })),
    })),
  }));
}

function extractCaseIds(checkedKeys) {
  return checkedKeys
    .filter((k) => String(k).startsWith('c:'))
    .map((k) => Number(String(k).slice(2)));
}

export default function TestTaskDetail() {
  const { projectId, taskId } = useParams();
  const pid = Number(projectId);
  const tid = Number(taskId);
  const { message, modal } = App.useApp();
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeKey, setActiveKey] = useState(null);
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchCreating, setBatchCreating] = useState(false);
  const [caseSource, setCaseSource] = useState('copy'); // copy | pick
  const [allCases, setAllCases] = useState([]);
  const [casesLoading, setCasesLoading] = useState(false);
  const [checkedKeys, setCheckedKeys] = useState([]);
  const [batchForm] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const t = await getTestTaskDetail(pid, tid);
      setTask(t);
      setActiveKey((prev) => {
        if (prev && (prev === 'defects' || t.batches.some((b) => `b:${b.id}` === prev))) return prev;
        return t.batches.length ? `b:${t.batches[0].id}` : 'defects';
      });
    } catch {
      message.error('加载测试任务失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [pid, tid]);

  const taskStats = useMemo(() => {
    const batches = task?.batches || [];
    const sum = (key) => batches.reduce((n, b) => n + (b.stats?.[key] || 0), 0);
    const total = sum('total');
    const passed = sum('passed');
    return {
      total,
      passed,
      failed: sum('failed'),
      blocked: sum('blocked'),
      pending: sum('pending'),
      executed: sum('executed'),
      pass_rate: total ? Math.round((passed / total) * 1000) / 10 : 0,
    };
  }, [task]);

  const handleBatchChange = (updated) => {
    setTask((prev) => ({
      ...prev,
      batches: prev.batches.map((b) => (b.id === updated.id ? { ...b, ...updated } : b)),
    }));
  };

  const handleDeleteBatch = (batch) => {
    modal.confirm({
      title: `确定删除批次「${batch.name}」？`,
      content: '批次内的执行记录将一并删除，用例本身不受影响。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteBatch(pid, tid, batch.id);
          message.success('已删除');
          setActiveKey(null);
          load();
        } catch (err) {
          message.error(err?.response?.data?.detail || '删除失败');
        }
      },
    });
  };

  const toggleTaskStatus = async () => {
    const next = task.status === 'completed' ? 'in_progress' : 'completed';
    try {
      const updated = await updateTestTask(pid, tid, { status: next });
      setTask((prev) => ({ ...prev, status: updated.status }));
      message.success(next === 'completed' ? '测试任务已完成' : '已重新打开');
    } catch (err) {
      message.error(err?.response?.data?.detail || '操作失败');
    }
  };

  const openBatchModal = () => {
    batchForm.resetFields();
    setCaseSource(task.batches.length ? 'copy' : 'pick');
    setCheckedKeys([]);
    setBatchModalOpen(true);
  };

  useEffect(() => {
    if (!batchModalOpen || caseSource !== 'pick' || allCases.length) return;
    setCasesLoading(true);
    getTestcases(pid)
      .then(setAllCases)
      .catch(() => message.error('加载用例失败'))
      .finally(() => setCasesLoading(false));
  }, [batchModalOpen, caseSource]);

  const caseTreeData = useMemo(() => buildCaseTree(allCases), [allCases]);
  const selectedCount = useMemo(() => extractCaseIds(checkedKeys).length, [checkedKeys]);

  const handleCreateBatch = async () => {
    const values = await batchForm.validateFields();
    const payload = { name: values.name };
    if (caseSource === 'copy') {
      payload.copy_from_batch_id = values.copy_from_batch_id;
    } else {
      const caseIds = extractCaseIds(checkedKeys);
      if (!caseIds.length) {
        message.warning('请至少选择一条用例');
        return;
      }
      payload.case_ids = caseIds;
    }
    setBatchCreating(true);
    try {
      const updated = await createBatch(pid, tid, payload);
      message.success('批次已创建');
      setBatchModalOpen(false);
      setTask(updated);
      const newBatch = updated.batches[updated.batches.length - 1];
      if (newBatch) setActiveKey(`b:${newBatch.id}`);
    } catch (err) {
      message.error(err?.response?.data?.detail || '创建失败');
    } finally {
      setBatchCreating(false);
    }
  };

  if (loading && !task) {
    return (
      <div className="page-wide">
        <Card className="surface-card"><div style={{ textAlign: 'center', padding: 60 }}><Spin /></div></Card>
      </div>
    );
  }
  if (!task) {
    return (
      <div className="page-wide">
        <Card className="surface-card">
          <div style={{ textAlign: 'center', padding: 40 }}>
            测试任务不存在或已删除，<Link to={`/projects/${pid}/tasks`}>返回测试任务</Link>
          </div>
        </Card>
      </div>
    );
  }

  const defectCount = taskStats.failed;
  const tabItems = [
    ...task.batches.map((b) => ({
      key: `b:${b.id}`,
      label: (
        <span>
          {b.name}
          <span className="batch-tab-count">{b.stats.executed}/{b.stats.total}</span>
        </span>
      ),
      children: (
        <BatchPanel
          pid={pid}
          taskId={tid}
          batch={b}
          onBatchChange={handleBatchChange}
          onDeleteBatch={handleDeleteBatch}
          deletable={task.batches.length > 1}
        />
      ),
    })),
    {
      key: 'defects',
      label: (
        <span>
          <BugOutlined /> 缺陷列表
          {defectCount > 0 && <span className="batch-tab-count batch-tab-count-danger">{defectCount}</span>}
        </span>
      ),
      children: (
        <DefectsPanel
          pid={pid}
          taskId={tid}
          onJumpToBatch={(batchId) => setActiveKey(`b:${batchId}`)}
        />
      ),
    },
  ];

  return (
    <div className="page-wide">
      <div className="run-detail-header">
        <div className="run-detail-title-row">
          <Link to={`/projects/${pid}/tasks`} className="run-detail-back">
            <ArrowLeftOutlined /> 测试任务
          </Link>
          <h1 className="run-detail-title">{task.name}</h1>
          <Tag color={task.status === 'completed' ? 'success' : 'processing'}>
            {RUN_STATUS_LABEL[task.status] || task.status}
          </Tag>
          <div className="run-detail-actions">
            <Button
              icon={task.status === 'completed' ? <RedoOutlined /> : <CheckCircleOutlined />}
              onClick={toggleTaskStatus}
            >
              {task.status === 'completed' ? '重新打开' : '完成任务'}
            </Button>
          </div>
        </div>
        <div className="run-detail-stats">
          <span className="run-stat"><i style={{ background: RESULT_COLOR.passed }} />通过 <b>{taskStats.passed}</b></span>
          <span className="run-stat"><i style={{ background: RESULT_COLOR.failed }} />失败 <b>{taskStats.failed}</b></span>
          <span className="run-stat"><i style={{ background: RESULT_COLOR.blocked }} />阻塞 <b>{taskStats.blocked}</b></span>
          <span className="run-stat"><i style={{ background: RESULT_COLOR.pending }} />未执行 <b>{taskStats.pending}</b></span>
          <div className="run-detail-progress">
            <Progress
              percent={taskStats.total ? Math.round((taskStats.executed / taskStats.total) * 100) : 0}
              success={{ percent: taskStats.pass_rate, strokeColor: RESULT_COLOR.passed }}
              strokeColor="#f59e0b"
              format={() => `通过率 ${taskStats.pass_rate}%`}
            />
          </div>
        </div>
      </div>

      <Tabs
        className="task-batch-tabs"
        activeKey={activeKey}
        onChange={setActiveKey}
        destroyOnHidden
        items={tabItems}
        tabBarExtraContent={{
          right: (
            <Button size="small" icon={<PlusOutlined />} onClick={openBatchModal}>
              新建批次
            </Button>
          ),
        }}
      />

      <Modal
        title="新建批次"
        open={batchModalOpen}
        onOk={handleCreateBatch}
        onCancel={() => setBatchModalOpen(false)}
        okText="创建"
        cancelText="取消"
        confirmLoading={batchCreating}
        width={620}
      >
        <Form
          form={batchForm}
          layout="vertical"
          style={{ marginTop: 8 }}
          initialValues={{ copy_from_batch_id: task.batches[task.batches.length - 1]?.id }}
        >
          <Form.Item name="name" label="批次名称" rules={[{ required: true, message: '请输入批次名称' }]}>
            <AutoComplete
              options={BATCH_PRESETS.map((v) => ({ value: v }))}
              placeholder="选择或输入批次名称，例如：预发测试"
              maxLength={100}
            />
          </Form.Item>
          <Form.Item label="用例来源">
            <Radio.Group value={caseSource} onChange={(e) => setCaseSource(e.target.value)}>
              <Radio value="copy" disabled={!task.batches.length}>复用已有批次的用例</Radio>
              <Radio value="pick">重新圈选用例</Radio>
            </Radio.Group>
          </Form.Item>
          {caseSource === 'copy' && (
            <Form.Item name="copy_from_batch_id" label="复用批次" rules={[{ required: true, message: '请选择批次' }]}>
              <Select
                options={task.batches.map((b) => ({
                  value: b.id,
                  label: `${b.name}（${b.stats.total} 条用例）`,
                }))}
              />
            </Form.Item>
          )}
        </Form>
        {caseSource === 'pick' && (
          casesLoading ? (
            <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
          ) : allCases.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="项目还没有已入库用例" />
          ) : (
            <>
              <div className="run-case-tree">
                <Tree
                  checkable
                  checkedKeys={checkedKeys}
                  onCheck={(keys) => setCheckedKeys(keys)}
                  treeData={caseTreeData}
                  defaultExpandAll={allCases.length <= 60}
                  height={300}
                />
              </div>
              <div className="run-selected-count">已选 {selectedCount} 条用例</div>
            </>
          )
        )}
      </Modal>
    </div>
  );
}
