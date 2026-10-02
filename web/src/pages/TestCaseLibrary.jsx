import { ApartmentOutlined, DatabaseOutlined, EditOutlined, FolderOutlined, PlayCircleOutlined, ProjectOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import { App, Button, Card, Empty, Input, Segmented, Select, Space, Spin, Table, Tag, Tooltip, Tree } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';
import CatalogEditModal from '../components/CatalogEditModal';
import PageHeader from '../components/PageHeader';
import TestCaseEditModal from '../components/TestCaseEditModal';
import TestCaseMindmap from '../components/TestCaseMindmap';
import { getAllTestcases, renameTestcaseCatalog, updateTestcase } from '../services/api';
import { stepsToText, textToSteps } from '../utils/caseText';

const DEFAULT_MODULE = '未分类';
const DEFAULT_FEATURE = '未关联功能点';

function normalizeModule(value) {
  return value?.trim() || DEFAULT_MODULE;
}

function normalizeFeature(value) {
  return value?.trim() || DEFAULT_FEATURE;
}

function parseTreeKey(key) {
  if (!key || key === 'all') return null;
  const parts = key.split('|');
  const projectPart = parts.find((p) => p.startsWith('p:'));
  const modulePart = parts.find((p) => p.startsWith('m:'));
  const featurePart = parts.find((p) => p.startsWith('f:'));
  if (!projectPart || !modulePart) return null;

  const projectId = Number(projectPart.slice(2));
  const module = modulePart.slice(2);

  if (featurePart) {
    return {
      type: 'feature',
      projectId,
      module,
      feature: featurePart.slice(2),
      key,
    };
  }
  return { type: 'module', projectId, module, key };
}

function isCatalogEditable(meta) {
  if (!meta) return false;
  if (meta.type === 'module' && meta.module === DEFAULT_MODULE) return false;
  if (meta.type === 'feature' && (meta.module === DEFAULT_MODULE || meta.feature === DEFAULT_FEATURE)) {
    return false;
  }
  return true;
}

function remapSelectedKey(selectedKey, renameInfo) {
  const { type, projectId, oldModule, oldFeature, newName } = renameInfo;
  if (!selectedKey || selectedKey === 'all') return selectedKey;

  if (type === 'module') {
    const oldPrefix = `p:${projectId}|m:${oldModule}`;
    const newPrefix = `p:${projectId}|m:${newName}`;
    if (selectedKey === oldPrefix) return newPrefix;
    if (selectedKey.startsWith(`${oldPrefix}|`)) {
      return selectedKey.replace(oldPrefix, newPrefix);
    }
  }

  if (type === 'feature') {
    const oldKey = `p:${projectId}|m:${oldModule}|f:${oldFeature}`;
    const newKey = `p:${projectId}|m:${oldModule}|f:${newName}`;
    if (selectedKey === oldKey) return newKey;
  }

  return selectedKey;
}

function applyCatalogRenameToCases(cases, renameInfo) {
  const { type, projectId, oldModule, oldFeature, newName } = renameInfo;
  return cases.map((c) => {
    if (c.project_id !== projectId) return c;
    const mod = normalizeModule(c.module);
    const feat = normalizeFeature(c.feature);
    if (type === 'module' && mod === oldModule) {
      return { ...c, module: newName };
    }
    if (type === 'feature' && mod === oldModule && feat === oldFeature) {
      return { ...c, feature: newName };
    }
    return c;
  });
}

const TYPE_LABEL = { functional: '功能', boundary: '边界', exception: '异常' };
const SOURCE_LABEL = { ai_generated: 'AI 生成', manual: '手动创建' };

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
    </div>
  );
}

function buildTreeData(cases, singleProject = false) {
  const projects = {};
  cases.forEach((c) => {
    const pid = c.project_id;
    const pname = c.project_name || `项目 #${pid}`;
    const mod = c.module?.trim() || '未分类';
    const feat = c.feature?.trim() || '未关联功能点';
    if (!projects[pid]) projects[pid] = { name: pname, modules: {} };
    if (!projects[pid].modules[mod]) projects[pid].modules[mod] = {};
    if (!projects[pid].modules[mod][feat]) projects[pid].modules[mod][feat] = [];
    projects[pid].modules[mod][feat].push(c);
  });

  const projectNodes = Object.entries(projects).map(([pid, proj]) => {
    const projCount = Object.values(proj.modules).reduce(
      (n, feats) => n + Object.values(feats).reduce((m, list) => m + list.length, 0),
      0,
    );
    return {
      key: `p:${pid}`,
      title: `${proj.name} (${projCount})`,
      icon: <ProjectOutlined />,
      children: Object.entries(proj.modules).map(([mod, feats]) => {
        const modCount = Object.values(feats).reduce((n, list) => n + list.length, 0);
        return {
          key: `p:${pid}|m:${mod}`,
          title: `${mod} (${modCount})`,
          icon: <FolderOutlined />,
          children: Object.entries(feats).map(([feat, list]) => ({
            key: `p:${pid}|m:${mod}|f:${feat}`,
            title: `${feat} (${list.length})`,
            isLeaf: true,
          })),
        };
      }),
    };
  });

  // 项目内视图不需要项目层级，模块直接挂在根节点下
  const children = singleProject
    ? projectNodes.flatMap((node) => node.children)
    : projectNodes;

  return [{
    key: 'all',
    title: `全部用例 (${cases.length})`,
    children,
  }];
}

function filterCases(cases, selectedKey) {
  if (!selectedKey || selectedKey === 'all') return cases;

  const parts = selectedKey.split('|');
  const projectPart = parts.find(p => p.startsWith('p:'));
  const modulePart = parts.find(p => p.startsWith('m:'));
  const featurePart = parts.find(p => p.startsWith('f:'));

  if (projectPart && modulePart && featurePart) {
    const pid = Number(projectPart.slice(2));
    const mod = modulePart.slice(2);
    const feat = featurePart.slice(2);
    return cases.filter(
      c => c.project_id === pid
        && (c.module?.trim() || '未分类') === mod
        && (c.feature?.trim() || '未关联功能点') === feat,
    );
  }
  if (projectPart && modulePart) {
    const pid = Number(projectPart.slice(2));
    const mod = modulePart.slice(2);
    return cases.filter(
      c => c.project_id === pid && (c.module?.trim() || '未分类') === mod,
    );
  }
  if (projectPart) {
    const pid = Number(projectPart.slice(2));
    return cases.filter(c => c.project_id === pid);
  }
  return cases;
}

function getPanelTitle(selectedKey) {
  if (selectedKey === 'all') return '全部用例';
  return '筛选结果';
}

function getMindmapRootLabel(selectedKey, filteredCases) {
  if (selectedKey === 'all') return '全部用例';
  const projectPart = selectedKey.split('|').find((p) => p.startsWith('p:'));
  if (projectPart) {
    const pid = Number(projectPart.slice(2));
    const match = filteredCases.find((c) => c.project_id === pid);
    return match?.project_name || `项目 #${pid}`;
  }
  return '筛选结果';
}

function isMultiProject(cases) {
  return new Set(cases.map((c) => c.project_id)).size > 1;
}

export default function TestCaseLibrary({ scopeProjectId }) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const projectFilter = scopeProjectId ? null : searchParams.get('project');
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState('list');
  const [selectedKey, setSelectedKey] = useState(projectFilter ? `p:${projectFilter}` : 'all');
  const [expandedKeys, setExpandedKeys] = useState([]);
  const [editingCase, setEditingCase] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [catalogTarget, setCatalogTarget] = useState(null);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogSaving, setCatalogSaving] = useState(false);
  const [suiteFilter, setSuiteFilter] = useState('all');
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [keyword, setKeyword] = useState('');
  const [priorityFilter, setPriorityFilter] = useState(null);
  const [typeFilter, setTypeFilter] = useState(null);
  const [sourceFilter, setSourceFilter] = useState(null);

  useEffect(() => {
    setLoading(true);
    getAllTestcases(scopeProjectId || undefined)
      .then(setCases)
      .finally(() => setLoading(false));
  }, [scopeProjectId]);

  useEffect(() => {
    if (projectFilter) setSelectedKey(`p:${projectFilter}`);
  }, [projectFilter]);

  useEffect(() => {
    if (!projectFilter) return;
    setExpandedKeys((prev) => (prev.includes(`p:${projectFilter}`) ? prev : [...prev, `p:${projectFilter}`]));
  }, [projectFilter]);

  const treeData = useMemo(() => buildTreeData(cases, !!scopeProjectId), [cases, scopeProjectId]);
  const filteredCases = useMemo(() => {
    let list = filterCases(cases, selectedKey);
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      list = list.filter((c) =>
        c.title?.toLowerCase().includes(kw)
        || c.module?.toLowerCase().includes(kw)
        || c.feature?.toLowerCase().includes(kw));
    }
    if (priorityFilter) list = list.filter((c) => c.priority === priorityFilter);
    if (typeFilter) list = list.filter((c) => c.case_type === typeFilter);
    if (sourceFilter) list = list.filter((c) => c.source === sourceFilter);
    return list;
  }, [cases, selectedKey, keyword, priorityFilter, typeFilter, sourceFilter]);
  const listCases = useMemo(
    () => (suiteFilter === 'smoke' ? filteredCases.filter((c) => c.is_smoke) : filteredCases),
    [filteredCases, suiteFilter],
  );
  const smokeCount = useMemo(() => filteredCases.filter((c) => c.is_smoke).length, [filteredCases]);
  const panelTitle = getPanelTitle(selectedKey);
  const mindmapRootLabel = getMindmapRootLabel(selectedKey, filteredCases);
  const multiProject = isMultiProject(filteredCases);

  const priorityTag = (p) => {
    const cls = p === 'P0' ? 'tag-p0' : p === 'P1' ? 'tag-p1' : 'tag-p2';
    return <Tag className={cls} variant="filled">{p}</Tag>;
  };

  const openEdit = (record) => {
    setEditingCase(record);
    setEditOpen(true);
  };

  const openCatalogEdit = (meta) => {
    setCatalogTarget(meta);
    setCatalogOpen(true);
  };

  const renderTreeTitle = (node) => {
    const meta = parseTreeKey(node.key);
    const editable = isCatalogEditable(meta);
    return (
      <span className="library-tree-title">
        <span className="library-tree-title-text">{node.title}</span>
        {editable && (
          <Tooltip title="重命名">
            <Button
              type="text"
              size="small"
              className="library-tree-edit-btn"
              icon={<EditOutlined />}
              onClick={(e) => {
                e.stopPropagation();
                openCatalogEdit(meta);
              }}
            />
          </Tooltip>
        )}
      </span>
    );
  };

  const handleSaveCatalog = async (newName) => {
    if (!catalogTarget || newName === (catalogTarget.type === 'module' ? catalogTarget.module : catalogTarget.feature)) {
      setCatalogOpen(false);
      setCatalogTarget(null);
      return;
    }

    setCatalogSaving(true);
    try {
      const payload = {
        type: catalogTarget.type,
        old_module: catalogTarget.module,
        old_feature: catalogTarget.type === 'feature' ? catalogTarget.feature : undefined,
        new_name: newName,
      };
      const result = await renameTestcaseCatalog(catalogTarget.projectId, payload);
      const renameInfo = {
        type: catalogTarget.type,
        projectId: catalogTarget.projectId,
        oldModule: catalogTarget.module,
        oldFeature: catalogTarget.feature,
        newName,
      };
      setCases((prev) => applyCatalogRenameToCases(prev, renameInfo));
      setSelectedKey((prev) => remapSelectedKey(prev, renameInfo));
      setCatalogOpen(false);
      setCatalogTarget(null);
      message.success(`目录已更新，共 ${result.updated_items} 项`);
    } catch (err) {
      message.error(err?.response?.data?.detail || '目录重命名失败');
    } finally {
      setCatalogSaving(false);
    }
  };

  const handleSaveEdit = async (values) => {
    if (!editingCase) return;
    setSaving(true);
    try {
      const payload = {
        title: values.title,
        priority: values.priority,
        case_type: values.case_type,
        precondition: values.precondition || '',
        steps: textToSteps(values.steps_text),
        expected_result: values.expected_result,
        module: values.module?.trim() || '',
        feature: values.feature?.trim() || '',
      };
      const updated = await updateTestcase(editingCase.project_id, editingCase.id, payload);
      setCases((prev) => prev.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)));
      setEditOpen(false);
      setEditingCase(null);
      message.success('用例已更新');
    } catch (err) {
      message.error(err?.response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    ...(scopeProjectId ? [] : [{ title: '项目', dataIndex: 'project_name', width: 120, ellipsis: true }]),
    { title: '用例标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    {
      title: '用例集',
      dataIndex: 'is_smoke',
      width: 80,
      render: v => (v ? <Tag color="green">冒烟</Tag> : <Tag>完整</Tag>),
    },
    { title: '模块', dataIndex: 'module', width: 110, ellipsis: true, render: v => v || '—' },
    { title: '功能点', dataIndex: 'feature', width: 140, ellipsis: true, className: 'key-text-cell', render: v => v || '—' },
    { title: '类型', dataIndex: 'case_type', width: 80, render: v => <Tag>{TYPE_LABEL[v] || v}</Tag> },
    { title: '优先级', dataIndex: 'priority', width: 80, render: priorityTag },
    { title: '来源', dataIndex: 'source', width: 90, render: v => SOURCE_LABEL[v] || v },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: v => new Date(v).toLocaleString() },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      fixed: 'right',
      render: (_, record) => (
        <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <div className="page-wide">
      <PageHeader
        title={scopeProjectId ? '项目用例' : '全部用例'}
        description={
          scopeProjectId
            ? (cases.length ? `本项目共 ${cases.length} 条已入库用例，按模块与功能点浏览` : '在 AI 生成流程中采纳的用例会出现在这里')
            : (cases.length ? `全部项目共 ${cases.length} 条已入库用例，按项目与模块浏览` : '采纳的测试用例会汇总在这里，按项目划分')
        }
        extra={
          !loading && cases.length > 0 && (
            <Tag icon={<DatabaseOutlined />} color="processing">{cases.length} 条用例</Tag>
          )
        }
      />

      {loading ? (
        <Card className="surface-card"><div style={{ textAlign: 'center', padding: 60 }}><Spin /></div></Card>
      ) : cases.length === 0 ? (
        <Card className="surface-card">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div>
                <div className="empty-state-title">暂无用例</div>
                <div className="empty-state-desc">在各项目的 AI 生成流程中评审并采纳用例后，会汇总出现在这里</div>
              </div>
            }
          />
        </Card>
      ) : (
        <div className="library-layout">
          <Card className="surface-card library-tree-panel" title="目录">
            <Tree
              showIcon
              expandedKeys={expandedKeys}
              onExpand={setExpandedKeys}
              selectedKeys={[selectedKey]}
              onSelect={(keys) => keys.length && setSelectedKey(keys[0])}
              treeData={treeData}
              titleRender={renderTreeTitle}
            />
          </Card>
          <Card
            className={`surface-card library-table-panel${viewMode === 'mindmap' ? ' library-mindmap-panel' : ''}`}
            title={panelTitle}
            extra={(
              <div className="library-panel-extra">
                <Tag>{filteredCases.length} 条</Tag>
                {viewMode === 'list' && (
                  <Segmented
                    size="small"
                    value={suiteFilter}
                    onChange={setSuiteFilter}
                    options={[
                      { label: '全部', value: 'all' },
                      { label: `冒烟 (${smokeCount})`, value: 'smoke' },
                    ]}
                  />
                )}
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
                  {scopeProjectId && selectedRowKeys.length > 0 && (
                    <Button
                      type="primary"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={() => navigate(`/projects/${scopeProjectId}/tasks`, { state: { caseIds: selectedRowKeys } })}
                    >
                      创建测试任务 ({selectedRowKeys.length})
                    </Button>
                  )}
                  <Select
                    placeholder="优先级"
                    allowClear
                    value={priorityFilter}
                    onChange={setPriorityFilter}
                    style={{ width: 100 }}
                    options={['P0', 'P1', 'P2'].map((p) => ({ label: p, value: p }))}
                  />
                  <Select
                    placeholder="类型"
                    allowClear
                    value={typeFilter}
                    onChange={setTypeFilter}
                    style={{ width: 100 }}
                    options={Object.entries(TYPE_LABEL).map(([v, l]) => ({ label: l, value: v }))}
                  />
                  <Select
                    placeholder="来源"
                    allowClear
                    value={sourceFilter}
                    onChange={setSourceFilter}
                    style={{ width: 120 }}
                    options={Object.entries(SOURCE_LABEL).map(([v, l]) => ({ label: l, value: v }))}
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
                  dataSource={listCases}
                  columns={columns}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  rowSelection={scopeProjectId ? { selectedRowKeys, onChange: setSelectedRowKeys } : undefined}
                  expandable={{ expandedRowRender: (r) => <CaseDetail record={r} /> }}
                />
              </>
            ) : (
              <TestCaseMindmap
                cases={filteredCases}
                rootLabel={mindmapRootLabel}
                multiProject={multiProject}
                showFullMapButton
                onEditCase={openEdit}
              />
            )}
          </Card>
        </div>
      )}

      <TestCaseEditModal
        open={editOpen}
        testcase={editingCase}
        saving={saving}
        onCancel={() => { setEditOpen(false); setEditingCase(null); }}
        onSave={handleSaveEdit}
      />

      <CatalogEditModal
        open={catalogOpen}
        target={catalogTarget}
        saving={catalogSaving}
        onCancel={() => { setCatalogOpen(false); setCatalogTarget(null); }}
        onSave={handleSaveCatalog}
      />
    </div>
  );
}
