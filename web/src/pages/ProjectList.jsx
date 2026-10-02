import {
  BookOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EllipsisOutlined,
  FileTextOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  App, Button, Card, Dropdown, Empty, Form, Input, Modal, Select, Spin, Tag,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { createProject, deleteProject, getHomeOverview } from '../services/api';
import {
  GEN_STATUS_LABEL,
  getGenerationStatusClass,
  getProjectWorkAction,
  getStageAction,
  formatRelativeTime,
} from '../utils/projectAction';

function hasRealDescription(desc) {
  const text = desc?.trim();
  return text && text.length > 2 && !/^\d+$/.test(text);
}

export default function ProjectList() {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('active');
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setOverview(await getHomeOverview());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    const values = await form.validateFields();
    await createProject(values);
    message.success('项目创建成功');
    setOpen(false);
    form.resetFields();
    load();
  };

  const projects = overview?.projects || [];
  const hasProjects = projects.length > 0;

  const focusProject = useMemo(() => {
    if (!hasProjects) return null;
    if (overview?.latest_active_project_id) {
      return projects.find((p) => p.id === overview.latest_active_project_id) || projects[0];
    }
    return projects[0];
  }, [overview, projects, hasProjects]);

  const filteredProjects = useMemo(() => {
    let list = [...projects];
    const keyword = search.trim().toLowerCase();
    if (keyword) {
      list = list.filter((p) =>
        p.name.toLowerCase().includes(keyword)
        || p.description?.toLowerCase().includes(keyword),
      );
    }
    list.sort((a, b) => {
      if (sortBy === 'name') return a.name.localeCompare(b.name, 'zh-CN');
      if (sortBy === 'created') return new Date(b.created_at) - new Date(a.created_at);
      const aTime = a.last_generation_at ? new Date(a.last_generation_at).getTime() : 0;
      const bTime = b.last_generation_at ? new Date(b.last_generation_at).getTime() : 0;
      if (aTime !== bTime) return bTime - aTime;
      return new Date(b.updated_at) - new Date(a.updated_at);
    });
    return list;
  }, [projects, search, sortBy]);

  const getCardMenu = (project) => ({
    items: [
      {
        key: 'generate',
        icon: <ThunderboltOutlined />,
        label: 'AI 生成',
        onClick: () => navigate(`/projects/${project.id}/generate`),
      },
      {
        key: 'testcases',
        icon: <DatabaseOutlined />,
        label: '项目用例',
        onClick: () => navigate(`/projects/${project.id}/testcases`),
      },
      { type: 'divider' },
      {
        key: 'delete',
        icon: <DeleteOutlined />,
        label: '删除项目',
        danger: true,
        onClick: () => {
          modal.confirm({
            title: '确定删除此项目？',
            content: '项目下的需求和生成记录将一并删除，已入库用例需单独确认。',
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
              await deleteProject(project.id);
              message.success('已删除');
              load();
            },
          });
        },
      },
    ],
  });

  const renderContinueHero = () => {
    if (!focusProject) return null;
    const stage = overview?.latest_active_stage;
    const stageAction = getStageAction(focusProject.id, stage) || getProjectWorkAction(focusProject);

    return (
      <section className="home-action-hero">
        <div className="home-action-main">
          <div className="home-action-label">继续上次工作</div>
          <h1 className="home-action-title">{focusProject.name}</h1>
        </div>
        <div className="home-action-buttons">
          <Button
            size="large"
            type="primary"
            icon={stageAction.kind === 'generate' ? <ThunderboltOutlined /> : undefined}
            onClick={() => navigate(stageAction.path)}
          >
            {stageAction.label}
          </Button>
          <Button size="large" onClick={() => navigate(`/projects/${focusProject.id}`)}>
            打开项目
          </Button>
        </div>
      </section>
    );
  };

  return (
    <div>
      {hasProjects ? renderContinueHero() : (
        <section className="hero-section">
          <div className="hero-content">
            <h1 className="hero-title">从需求到用例，AI 帮你完成</h1>
            <p className="hero-desc">
              上传 PRD → 结构化功能点 → 按策略生成候选用例 → 质检评审 → 一键入库。
              专注测试用例生成，不做大而全的平台。
            </p>
            <div className="hero-steps">
              <span>① 创建项目</span>
              <span>② 导入需求</span>
              <span>③ AI 生成</span>
              <span>④ 采纳入库</span>
            </div>
            <div className="hero-actions">
              <Button size="large" type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
                创建第一个项目
              </Button>
            </div>
            <div className="hero-checklist">
              首次使用：先到 <Link to="/settings">个人设置</Link> 配置模型 API Key，再创建项目导入需求
            </div>
          </div>
        </section>
      )}

      {hasProjects && (
        <div className="home-list-toolbar">
          <div>
            <h2 className="home-list-title">全部项目空间</h2>
            <p className="home-list-desc">共 {projects.length} 个项目 · 每个项目自带 Wiki 地图与测试骨架</p>
          </div>
          <div className="home-list-controls">
            <Input.Search
              placeholder="搜索项目"
              allowClear
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 200 }}
            />
            <Select
              value={sortBy}
              onChange={setSortBy}
              style={{ width: 140 }}
              options={[
                { label: '最近活跃', value: 'active' },
                { label: '创建时间', value: 'created' },
                { label: '名称', value: 'name' },
              ]}
            />
            <Button icon={<BookOutlined />} onClick={() => navigate('/wiki')}>
              工作台总 Wiki
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
              新建项目
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : !hasProjects ? (
        <Card className="surface-card">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className="empty-state">
                <div className="empty-state-title">还没有项目</div>
                <div className="empty-state-desc">创建项目后即可导入需求、生成测试用例</div>
              </div>
            }
          />
        </Card>
      ) : filteredProjects.length === 0 ? (
        <Card className="surface-card">
          <Empty description="没有匹配的项目" />
        </Card>
      ) : (
        <div className="project-grid">
          {filteredProjects.map((project) => {
            const workAction = getProjectWorkAction(project);
            const isFocus = focusProject?.id === project.id;
            return (
              <Card
                key={project.id}
                className={`project-card${isFocus ? ' project-card-focus' : ''}`}
                hoverable
                onClick={() => navigate(`/projects/${project.id}`)}
              >
                <div className="project-card-header">
                  <div className="project-card-icon">{project.name.charAt(0)}</div>
                  <div className="project-card-header-text">
                    <div className="project-card-name">{project.name}</div>
                    {hasRealDescription(project.description) && (
                      <div className="project-card-desc">{project.description}</div>
                    )}
                  </div>
                  <span onClick={(e) => e.stopPropagation()}>
                    <Dropdown menu={getCardMenu(project)} trigger={['click']}>
                      <Button type="text" size="small" icon={<EllipsisOutlined />} className="project-card-more" />
                    </Dropdown>
                  </span>
                </div>

                <div className="project-card-stats">
                  <div className="project-stat-item">
                    <span className="project-stat-value">{project.testcase_count}</span>
                    <span className="project-stat-label">用例</span>
                  </div>
                  <div className="project-stat-item">
                    <span className="project-stat-value">{project.wiki_count ?? 0}</span>
                    <span className="project-stat-label">Wiki</span>
                  </div>
                  <div className="project-stat-item">
                    <span className="project-stat-value">{project.generation_count}</span>
                    <span className="project-stat-label">生成</span>
                  </div>
                  <div className="project-stat-item">
                    <span className={`project-stat-value project-stat-time ${getGenerationStatusClass(project.last_generation_status)}`}>
                      {project.last_generation_status
                        ? (GEN_STATUS_LABEL[project.last_generation_status] || project.last_generation_status)
                        : '—'}
                    </span>
                    <span className="project-stat-label">状态</span>
                  </div>
                </div>

                <div className="project-card-footer">
                  <div className="project-card-footer-left">
                    {project.has_skeleton ? (
                      <span className="project-skeleton-badge">
                        <FileTextOutlined /> 骨架已生成
                      </span>
                    ) : (
                      <span className="project-skeleton-badge muted">
                        <FileTextOutlined /> 骨架未初始化
                      </span>
                    )}
                  </div>
                  <span className="project-card-date">
                    {project.last_generation_at ? `${formatRelativeTime(project.last_generation_at)}活跃` : '尚未开始生成'}
                  </span>
                  <div className="project-card-actions" onClick={(e) => e.stopPropagation()}>
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      onClick={() => navigate(workAction.path)}
                    >
                      {workAction.label}
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Modal
        title="新建项目"
        open={open}
        onOk={handleCreate}
        onCancel={() => setOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="例如：电商系统 v2.0" />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea rows={3} placeholder="简要描述项目背景与测试范围" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
