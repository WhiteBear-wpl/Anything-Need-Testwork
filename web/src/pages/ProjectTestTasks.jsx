import { DeleteOutlined, EllipsisOutlined, PlusOutlined } from '@ant-design/icons';
import {
  App, AutoComplete, Button, Card, Dropdown, Empty, Form, Input, Modal, Space, Spin, Tabs, Tag, Tree,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import { createTestTask, deleteTestTask, getTestcases, getTestTasks } from '../services/api';
import { BATCH_PRESETS, RESULT_COLOR, RUN_STATUS_LABEL } from '../utils/runResult';

const DEFAULT_MODULE = '未分类';
const DEFAULT_FEATURE = '未关联功能点';

function buildCaseTree(cases) {
  const modules = {};
  cases.forEach((c) => {
    const mod = c.module?.trim() || DEFAULT_MODULE;
    const feat = c.feature?.trim() || DEFAULT_FEATURE;
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
      children: list.map((c) => ({
        key: `c:${c.id}`,
        title: c.title,
      })),
    })),
  }));
}

function extractCaseIds(checkedKeys) {
  return checkedKeys
    .filter((k) => String(k).startsWith('c:'))
    .map((k) => Number(String(k).slice(2)));
}

function BatchProgressRow({ batch }) {
  const { stats } = batch;
  const segments = [
    ['passed', stats.passed],
    ['failed', stats.failed],
    ['blocked', stats.blocked],
    ['pending', stats.pending],
  ].filter(([, n]) => n > 0);
  return (
    <div className="task-batch-row">
      <span className="task-batch-name">{batch.name}</span>
      <span className="task-batch-bar">
        {segments.map(([key, n]) => (
          <i key={key} style={{ flex: n, background: RESULT_COLOR[key] }} />
        ))}
        {segments.length === 0 && <i style={{ flex: 1, background: '#e2e8f0' }} />}
      </span>
      <span className="task-batch-count">{stats.executed}/{stats.total}</span>
    </div>
  );
}

function TaskCard({ task, onOpen, onDelete }) {
  const { stats } = task;
  const menu = {
    items: [
      {
        key: 'delete',
        icon: <DeleteOutlined />,
        label: '删除任务',
        danger: true,
        onClick: () => onDelete(task),
      },
    ],
  };
  return (
    <Card className="run-card" hoverable onClick={() => onOpen(task)}>
      <div className="run-card-header">
        <span className="run-card-name">{task.name}</span>
        <Tag color={task.status === 'completed' ? 'success' : 'processing'}>
          {RUN_STATUS_LABEL[task.status] || task.status}
        </Tag>
        <span onClick={(e) => e.stopPropagation()}>
          <Dropdown menu={menu} trigger={['click']}>
            <Button type="text" size="small" icon={<EllipsisOutlined />} />
          </Dropdown>
        </span>
      </div>
      <div className="task-batch-list">
        {task.batches.map((b) => <BatchProgressRow key={b.id} batch={b} />)}
      </div>
      <div className="run-card-stats">
        <span><i style={{ background: RESULT_COLOR.passed }} />通过 {stats.passed}</span>
        <span><i style={{ background: RESULT_COLOR.failed }} />失败 {stats.failed}</span>
        <span><i style={{ background: RESULT_COLOR.blocked }} />阻塞 {stats.blocked}</span>
        <span><i style={{ background: RESULT_COLOR.pending }} />未执行 {stats.pending}</span>
      </div>
      <div className="run-card-footer">
        {task.batches.length} 个批次 · 通过率 {stats.pass_rate}% · {new Date(task.created_at).toLocaleDateString()}
      </div>
    </Card>
  );
}

export default function ProjectTestTasks() {
  const { projectId } = useParams();
  const pid = Number(projectId);
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [tasks, setTasks] = useState([]);
  const [keyword, setKeyword] = useState('');
  const [statusTab, setStatusTab] = useState('all');
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [cases, setCases] = useState([]);
  const [casesLoading, setCasesLoading] = useState(false);
  const [checkedKeys, setCheckedKeys] = useState([]);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setTasks(await getTestTasks(pid));
    } catch {
      message.error('加载测试任务失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [pid]);

  const openCreate = async (presetCaseIds = []) => {
    setOpen(true);
    setCasesLoading(true);
    try {
      const list = await getTestcases(pid);
      setCases(list);
      if (presetCaseIds.length) {
        const valid = new Set(list.map((c) => c.id));
        setCheckedKeys(presetCaseIds.filter((id) => valid.has(id)).map((id) => `c:${id}`));
      }
    } catch {
      message.error('加载用例失败');
    } finally {
      setCasesLoading(false);
    }
  };

  // 从用例库「创建测试任务」入口带过来的预选用例
  useEffect(() => {
    const presetIds = location.state?.caseIds;
    if (presetIds?.length) {
      openCreate(presetIds);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, []);

  const treeData = useMemo(() => buildCaseTree(cases), [cases]);
  const selectedCount = useMemo(() => extractCaseIds(checkedKeys).length, [checkedKeys]);

  const runningCount = useMemo(
    () => tasks.filter((t) => t.status !== 'completed').length,
    [tasks],
  );

  const filteredTasks = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    let list = tasks;
    if (statusTab === 'running') list = list.filter((t) => t.status !== 'completed');
    if (!kw) return list;
    return list.filter((t) =>
      t.name?.toLowerCase().includes(kw)
      || t.description?.toLowerCase().includes(kw)
      || t.batches?.some((b) => b.name?.toLowerCase().includes(kw)));
  }, [tasks, keyword, statusTab]);

  const quickSelect = (filterFn) => {
    setCheckedKeys(cases.filter(filterFn).map((c) => `c:${c.id}`));
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    const caseIds = extractCaseIds(checkedKeys);
    if (!caseIds.length) {
      message.warning('请至少选择一条用例');
      return;
    }
    setCreating(true);
    try {
      const task = await createTestTask(pid, {
        name: values.name,
        description: values.description || '',
        batch_name: values.batch_name || '线下测试',
        case_ids: caseIds,
      });
      message.success('测试任务已创建');
      setOpen(false);
      form.resetFields();
      setCheckedKeys([]);
      navigate(`/projects/${pid}/tasks/${task.id}`);
    } catch (err) {
      message.error(err?.response?.data?.detail || '创建失败');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = (task) => {
    modal.confirm({
      title: `确定删除任务「${task.name}」？`,
      content: '任务下所有批次与执行记录将一并删除，用例本身不受影响。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        await deleteTestTask(pid, task.id);
        message.success('已删除');
        load();
      },
    });
  };

  return (
    <div className="page-wide">
      <PageHeader
        title="测试任务"
        description="按测试任务组织用例执行，一个任务可包含线下 / 预发 / 线上等多个批次"
      />

      <Tabs
        className="task-list-tabs"
        activeKey={statusTab}
        onChange={setStatusTab}
        items={[
          { key: 'all', label: `全部任务 (${tasks.length})` },
          { key: 'running', label: `进行中 (${runningCount})` },
        ]}
        tabBarExtraContent={
          <Space>
            {tasks.length > 0 && (
              <Input.Search
                placeholder="搜索任务 / 批次名称"
                allowClear
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                style={{ width: 220 }}
              />
            )}
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate()}>
              新建测试任务
            </Button>
          </Space>
        }
      />

      {loading ? (
        <Card className="surface-card"><div style={{ textAlign: 'center', padding: 60 }}><Spin /></div></Card>
      ) : tasks.length === 0 ? (
        <Card className="surface-card">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div>
                <div className="empty-state-title">还没有测试任务</div>
                <div className="empty-state-desc">创建任务后，圈选用例按批次逐条标记通过 / 失败 / 阻塞</div>
              </div>
            }
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate()}>新建测试任务</Button>
          </Empty>
        </Card>
      ) : filteredTasks.length === 0 ? (
        <Card className="surface-card"><Empty description={keyword ? '没有匹配的任务' : '没有进行中的任务'} /></Card>
      ) : (
        <div className="run-grid">
          {filteredTasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onOpen={(t) => navigate(`/projects/${pid}/tasks/${t.id}`)}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <Modal
        title="新建测试任务"
        open={open}
        onOk={handleCreate}
        onCancel={() => { setOpen(false); setCheckedKeys([]); }}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
        width={640}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }} initialValues={{ batch_name: '线下测试' }}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="例如：v1.2 回归测试" />
          </Form.Item>
          <Form.Item name="batch_name" label="首个批次" rules={[{ required: true, message: '请输入批次名称' }]}>
            <AutoComplete
              options={BATCH_PRESETS.map((v) => ({ value: v }))}
              placeholder="选择或输入批次名称"
              maxLength={100}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} placeholder="测试范围、环境等（可选）" />
          </Form.Item>
        </Form>
        <div className="run-quick-select">
          <span className="run-quick-select-label">快速选择</span>
          <Button size="small" onClick={() => quickSelect(() => true)}>全部</Button>
          <Button size="small" onClick={() => quickSelect((c) => c.is_smoke)}>冒烟用例</Button>
          <Button size="small" onClick={() => quickSelect((c) => c.priority === 'P0')}>P0</Button>
          <Button size="small" onClick={() => quickSelect((c) => ['P0', 'P1'].includes(c.priority))}>P0 + P1</Button>
          <Button size="small" onClick={() => setCheckedKeys([])}>清空</Button>
        </div>
        {casesLoading ? (
          <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
        ) : cases.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="项目还没有已入库用例" />
        ) : (
          <div className="run-case-tree">
            <Tree
              checkable
              checkedKeys={checkedKeys}
              onCheck={(keys) => setCheckedKeys(keys)}
              treeData={treeData}
              defaultExpandAll={cases.length <= 60}
              height={320}
            />
          </div>
        )}
        <div className="run-selected-count">已选 {selectedCount} 条用例</div>
      </Modal>
    </div>
  );
}
