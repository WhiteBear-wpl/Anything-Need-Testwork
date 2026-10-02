import {
  BookOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  MoreOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import {
  App, Button, Dropdown, Empty, Form, Input, Modal, Select, Spin, Tree,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  copyWikiToProject, createWikiPage, deleteWikiPage, getHomeOverview,
  getWikiPages, updateWikiPage,
} from '../services/api';

// 由扁平列表构建 antd Tree 数据
function buildTree(pages) {
  const byParent = {};
  pages.forEach((p) => {
    const key = p.parent_id ?? 'root';
    (byParent[key] = byParent[key] || []).push(p);
  });
  const toNode = (page) => ({
    key: String(page.id),
    title: page.title,
    children: (byParent[page.id] || []).map(toNode),
  });
  return (byParent.root || []).map(toNode);
}

export default function WikiPage() {
  const { projectId } = useParams();
  const isGlobal = !projectId;
  const { message, modal } = App.useApp();
  const [pages, setPages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [editor, setEditor] = useState(null); // {mode, page, parentId}
  const [copyTarget, setCopyTarget] = useState(false);
  const [projects, setProjects] = useState([]);
  const [copyForm] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setPages(await getWikiPages(projectId || null));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [projectId]);
  useEffect(() => {
    if (!isGlobal) return;
    getHomeOverview().then((ov) => setProjects(ov.projects || [])).catch(() => {});
  }, [isGlobal]);

  const treeData = useMemo(() => buildTree(pages), [pages]);
  const selected = pages.find((p) => String(p.id) === String(selectedId));

  const openCreate = (parentId) => setEditor({ mode: 'create', page: null, parentId });
  const openRename = (page) => setEditor({ mode: 'rename', page });

  const handleEditorSubmit = async (values) => {
    if (editor.mode === 'create') {
      await createWikiPage({
        title: values.title,
        content: '',
        project_id: projectId ? Number(projectId) : null,
        parent_id: editor.parentId ?? null,
      });
      message.success('页面已创建');
    } else if (editor.page) {
      await updateWikiPage(editor.page.id, { title: values.title });
      message.success('已重命名');
    }
    setEditor(null);
    load();
  };

  const saveContent = async () => {
    await updateWikiPage(selected.id, { content: draft });
    setEditing(false);
    message.success('已保存');
    load();
  };

  const confirmDelete = (page) => {
    modal.confirm({
      title: `删除「${page.title}」？`,
      content: '该页面及其全部子页面会一并删除，此操作不可撤销。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        await deleteWikiPage(page.id);
        if (String(selectedId) === String(page.id)) setSelectedId(null);
        message.success('已删除');
        load();
      },
    });
  };

  const doCopy = async () => {
    const { target_project_id } = await copyForm.validateFields();
    const res = await copyWikiToProject(selected.id, target_project_id);
    message.success(`已复制 ${res.copied_pages} 页到项目`);
    setCopyTarget(false);
    copyForm.resetFields();
  };

  const pageActions = (page) => ({
    items: [
      { key: 'add', icon: <FileAddOutlined />, label: '新建子页', onClick: () => openCreate(page.id) },
      { key: 'rename', icon: <EditOutlined />, label: '重命名', onClick: () => openRename(page) },
      ...(isGlobal ? [{
        key: 'copy', icon: <CopyOutlined />, label: '复制到项目', onClick: () => { setSelectedId(String(page.id)); setCopyTarget(true); },
      }] : []),
      { type: 'divider' },
      { key: 'del', icon: <DeleteOutlined />, label: '删除', danger: true, onClick: () => confirmDelete(page) },
    ],
  });

  const treeRender = (title, page) => (
    <span className="wiki-tree-node">
      <span className="wiki-tree-title">{title}</span>
      <span className="wiki-tree-actions" onClick={(e) => e.stopPropagation()}>
        <Dropdown menu={pageActions(page)} trigger={['click']}>
          <Button type="text" size="small" icon={<MoreOutlined />} />
        </Dropdown>
      </span>
    </span>
  );

  return (
    <div className="wiki-page">
      <aside className="wiki-side">
        <div className="wiki-side-header">
          <div className="wiki-side-title">
            <BookOutlined />
            <span>{isGlobal ? '工作台总 Wiki' : '项目 Wiki 地图'}</span>
          </div>
          <Button size="small" type="primary" ghost icon={<PlusOutlined />} onClick={() => openCreate(null)}>
            新建
          </Button>
        </div>
        <div className="wiki-side-tip">
          {isGlobal
            ? '总 Wiki 的页面可作为模板复制到任意项目复用。'
            : '按树形组织页面，用 Markdown 编写接口测试规范。'}
        </div>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : treeData.length === 0 ? (
          <div className="wiki-side-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无页面" /></div>
        ) : (
          <Tree
            className="wiki-tree"
            treeData={treeData.map((n) => ({ ...n, title: treeRender(n.title, pages.find((p) => String(p.id) === String(n.key))) }))}
            selectedKeys={selectedId ? [String(selectedId)] : []}
            onSelect={(keys) => setSelectedId(keys[0] ? Number(keys[0]) : null)}
            defaultExpandAll
          />
        )}
      </aside>

      <main className="wiki-main">
        {!selected ? (
          <Empty
            className="wiki-main-empty"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="从左侧选择一页，或在顶部新建一个 Wiki 页面。"
          />
        ) : editing ? (
          <div className="wiki-edit">
            <div className="wiki-edit-bar">
              <span className="wiki-edit-title">{selected.title}</span>
              <div>
                <Button size="small" onClick={() => setEditing(false)}>取消</Button>
                <Button size="small" type="primary" icon={<SaveOutlined />} onClick={saveContent} style={{ marginLeft: 8 }}>
                  保存
                </Button>
              </div>
            </div>
            <textarea
              className="wiki-textarea"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="使用 Markdown 编写…"
              spellCheck={false}
            />
          </div>
        ) : (
          <div className="wiki-view">
            <div className="wiki-view-head">
              <div>
                <h2 className="wiki-view-title">{selected.title}</h2>
                <span className="wiki-view-meta">
                  最后更新：{new Date(selected.updated_at).toLocaleString('zh-CN')}
                </span>
              </div>
              <div className="wiki-view-actions">
                {isGlobal && (
                  <Button size="small" icon={<CopyOutlined />} onClick={() => setCopyTarget(true)}>
                    复制到项目
                  </Button>
                )}
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => { setDraft(selected.content || ''); setEditing(true); }}
                >
                  编辑
                </Button>
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => confirmDelete(selected)}>
                  删除
                </Button>
              </div>
            </div>
            <div className="wiki-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{selected.content || ''}</ReactMarkdown>
            </div>
          </div>
        )}
      </main>

      <Modal
        title={editor?.mode === 'rename' ? '重命名页面' : '新建 Wiki 页面'}
        open={editor !== null}
        onCancel={() => setEditor(null)}
        footer={null}
        destroyOnClose
      >
        <Form
          layout="vertical"
          initialValues={editor?.mode === 'rename' ? { title: editor.page?.title } : {}}
          onFinish={handleEditorSubmit}
          style={{ marginTop: 8 }}
        >
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例如：接口测试规范 / 环境说明" autoFocus />
          </Form.Item>
          <div style={{ textAlign: 'right' }}>
            <Button onClick={() => setEditor(null)} style={{ marginRight: 8 }}>取消</Button>
            <Button type="primary" htmlType="submit">{editor?.mode === 'rename' ? '保存' : '创建'}</Button>
          </div>
        </Form>
      </Modal>

      <Modal
        title={`把「${selected?.title || ''}」复制到项目`}
        open={copyTarget}
        onOk={doCopy}
        onCancel={() => setCopyTarget(false)}
        okText="复制"
        cancelText="取消"
      >
        <Form form={copyForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="target_project_id"
            label="目标项目"
            rules={[{ required: true, message: '请选择项目' }]}
          >
            <Select
              placeholder="选择要复制到的项目"
              options={(projects || []).map((p) => ({ label: p.name, value: p.id }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
