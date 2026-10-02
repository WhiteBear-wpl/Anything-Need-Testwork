import {
  AppstoreOutlined,
  BookOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  FolderOutlined,
  HistoryOutlined,
  LogoutOutlined,
  MenuOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  SettingOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  Badge, ConfigProvider, Drawer, Dropdown, Spin,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';
import { clearAuth, getAuth, getHomeOverview, getProject, getSettings, logoutRequest } from '../services/api';

const GLOBAL_NAV = [
  { key: 'agent', path: '/agent', label: 'AI小助手', icon: RobotOutlined },
  { key: 'home', path: '/', label: '工作台', icon: AppstoreOutlined, exact: true },
  { key: 'wiki', path: '/wiki', label: '总Wiki', icon: BookOutlined },
  { key: 'testcases', path: '/testcases', label: '全部用例', icon: DatabaseOutlined },
  { key: 'knowledge', path: '/knowledge', label: '知识库', icon: BookOutlined },
  { key: 'evaluation', path: '/evaluation', label: 'AI 评测', icon: ExperimentOutlined },
];

const PROJECT_NAV = [
  { key: 'overview', suffix: '', label: '概览', icon: AppstoreOutlined },
  { key: 'generate', suffix: '/generate', label: 'AI 生成', icon: ThunderboltOutlined },
  { key: 'testcases', suffix: '/testcases', label: '项目用例', icon: DatabaseOutlined },
  { key: 'tasks', suffix: '/tasks', label: '测试任务', icon: PlayCircleOutlined },
  { key: 'wiki', suffix: '/wiki', label: '项目Wiki', icon: BookOutlined },
  { key: 'skeleton', suffix: '/skeleton', label: '测试骨架', icon: FileTextOutlined },
  { key: 'knowledge', suffix: '/knowledge', label: '知识库', icon: BookOutlined },
  { key: 'generations', suffix: '/generations', label: '生成记录', icon: HistoryOutlined },
];

const WORKSPACE_THEME = {
  token: {
    colorPrimary: '#0F766E',
    colorPrimaryHover: '#0D9488',
    colorPrimaryActive: '#115E59',
    colorInfo: '#0F766E',
    colorLink: '#0F766E',
    colorBgLayout: '#F6F8FA',
    colorBorder: '#E2E8F0',
    colorText: '#0F172A',
    colorTextSecondary: '#64748B',
    borderRadius: 6,
    borderRadiusLG: 8,
  },
  components: {
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      borderRadius: 6,
    },
    Card: {
      borderRadiusLG: 8,
    },
    Table: {
      headerBg: '#F6F8FA',
      headerColor: '#475569',
      borderColor: '#E2E8F0',
    },
  },
};

function SidebarContent({
  projectId,
  project,
  loadingProject,
  overview,
  loadingOverview,
  username,
  userInitial,
  isAdmin,
  needsSetup,
  onLogout,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const basePath = projectId ? `/projects/${projectId}` : '';
  const recentProjects = (overview?.projects || []).slice(0, 8);
  const currentProjectOverview = recentProjects.find((p) => String(p.id) === String(projectId));
  const switcherProjects = currentProjectOverview || !project
    ? recentProjects
    : [project, ...recentProjects].slice(0, 8);

  const switcherItems = {
    items: [
      {
        type: 'group',
        label: '切换项目',
        children: switcherProjects.map((p) => {
          const isCurrent = String(p.id) === String(projectId);
          return {
            key: String(p.id),
            label: (
              <span className="project-switch-menu-item">
                <span className="project-switch-menu-name">{p.name}</span>
              </span>
            ),
            onClick: () => {
              if (!isCurrent) navigate(`/projects/${p.id}`);
            },
          };
        }),
      },
      { type: 'divider' },
      {
        key: 'all-projects',
        icon: <AppstoreOutlined />,
        label: '全部项目',
        onClick: () => navigate('/'),
      },
    ],
    selectable: true,
    selectedKeys: [String(projectId)],
  };

  const userMenu = {
    items: [
      {
        key: 'settings',
        icon: <SettingOutlined />,
        label: (
          <span>
            个人设置
            {needsSetup && <Badge dot offset={[6, -2]} />}
          </span>
        ),
        onClick: () => navigate('/settings'),
      },
      { type: 'divider' },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        danger: true,
        onClick: onLogout,
      },
    ],
  };

  return (
    <>
      <Link to="/" className="app-brand">
        <div className="app-brand-icon" aria-hidden="true">WB</div>
        <span className="app-brand-title">WhiteBear-Test</span>
      </Link>

      <nav className="sidebar-nav">
        {GLOBAL_NAV.map(({ key, path, label, icon: Icon, exact }) => {
          const active = exact ? location.pathname === path : location.pathname.startsWith(path);
          return (
            <Link key={key} to={path} className={`sidebar-link${active ? ' active' : ''}`}>
              <Icon />
              {label}
            </Link>
          );
        })}
      </nav>

      {projectId ? (
        <>
          <div className="sidebar-divider" />
          <div className="sidebar-project">
            <div className="sidebar-project-label">当前项目</div>
            <Dropdown
              menu={switcherItems}
              trigger={['click']}
              placement="bottomLeft"
              overlayClassName="project-switch-dropdown"
              onOpenChange={setProjectMenuOpen}
            >
              <button
                type="button"
                className={`sidebar-project-switcher${projectMenuOpen ? ' open' : ''}`}
                aria-label="切换项目"
                aria-haspopup="menu"
                aria-expanded={projectMenuOpen}
              >
                <span className="sidebar-project-name">
                  {loadingProject ? <Spin size="small" /> : project?.name || '加载中...'}
                </span>
                <SwapOutlined className="sidebar-project-switch-icon" />
              </button>
            </Dropdown>
          </div>
          <nav className="sidebar-nav">
            {PROJECT_NAV.map(({ key, suffix, label, icon: Icon }) => {
              const path = `${basePath}${suffix}`;
              const active = suffix
                ? location.pathname.startsWith(path)
                : location.pathname === path;
              return (
                <Link
                  key={key}
                  to={path}
                  className={`sidebar-link${active ? ' active' : ''}`}
                >
                  <Icon />
                  {label}
                </Link>
              );
            })}
          </nav>
        </>
      ) : (
        <>
          <div className="sidebar-divider" />
          <div className="sidebar-section-label">最近项目</div>
          {loadingOverview ? (
            <div className="sidebar-loading"><Spin size="small" /></div>
          ) : recentProjects.length === 0 ? (
            <div className="sidebar-empty">暂无项目，请先创建</div>
          ) : (
            <nav className="sidebar-nav sidebar-nav-compact">
              {recentProjects.map((p) => {
                const active = location.pathname.startsWith(`/projects/${p.id}`);
                return (
                  <Link
                    key={p.id}
                    to={`/projects/${p.id}`}
                    className={`sidebar-link sidebar-link-compact${active ? ' active' : ''}`}
                    title={p.name}
                  >
                    <FolderOutlined />
                    <span className="sidebar-link-text">{p.name}</span>
                  </Link>
                );
              })}
            </nav>
          )}
        </>
      )}

      <div className="sidebar-footer">
        <Dropdown menu={userMenu} trigger={['click']} placement="topLeft">
          <button type="button" className="sidebar-user" title={username}>
            <Badge dot={needsSetup} offset={[-4, 4]}>
              <span className="sidebar-user-avatar" aria-hidden="true">{userInitial}</span>
            </Badge>
            <span className="sidebar-user-info">
              <span className="sidebar-user-name">{username}</span>
              <span className="sidebar-user-role">
                {needsSetup ? '模型未配置' : isAdmin ? '管理员' : '个人工作区'}
              </span>
            </span>
          </button>
        </Dropdown>
      </div>
    </>
  );
}

export default function AppLayout() {
  const { projectId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const auth = getAuth();
  const username = auth?.username || '当前用户';
  const userInitial = username.trim().slice(0, 1).toUpperCase() || 'U';

  const [project, setProject] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loadingProject, setLoadingProject] = useState(false);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleLogout = () => {
    logoutRequest(getAuth()?.token);
    clearAuth();
    navigate('/login', { replace: true });
  };

  useEffect(() => {
    setLoadingOverview(true);
    getHomeOverview()
      .then(setOverview)
      .catch(() => setOverview(null))
      .finally(() => setLoadingOverview(false));
  }, [location.pathname]);

  // API Key 未配置时在头像和设置入口上显示红点，把配置缺失提前暴露出来
  useEffect(() => {
    getSettings()
      .then((data) => setNeedsSetup(!data.llm_api_key_set && !data.llm_mock_mode))
      .catch(() => setNeedsSetup(false));
  }, [location.pathname]);

  useEffect(() => {
    if (!projectId) {
      setProject(null);
      return;
    }
    setLoadingProject(true);
    getProject(projectId)
      .then(setProject)
      .catch(() => setProject(null))
      .finally(() => setLoadingProject(false));
  }, [projectId]);

  // 路由变化时收起移动端抽屉
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const sidebarProps = useMemo(() => ({
    projectId,
    project,
    loadingProject,
    overview,
    loadingOverview,
    username,
    userInitial,
    isAdmin: !!auth?.is_admin,
    needsSetup,
    onLogout: handleLogout,
  }), [projectId, project, loadingProject, overview, loadingOverview, username, userInitial, auth?.is_admin, needsSetup]);

  return (
    <div className="app-layout">
      <header className="mobile-topbar">
        <button
          type="button"
          className="mobile-topbar-menu"
          aria-label="打开导航菜单"
          onClick={() => setDrawerOpen(true)}
        >
          <MenuOutlined />
        </button>
        <Link to="/" className="mobile-topbar-brand">
          <span className="app-brand-icon" aria-hidden="true">WB</span>
          <span className="mobile-topbar-title">
            {projectId && project ? project.name : 'WhiteBear-Test'}
          </span>
        </Link>
        <Badge dot={needsSetup} offset={[-4, 4]}>
          <button
            type="button"
            className="mobile-topbar-avatar"
            aria-label="打开导航菜单"
            onClick={() => setDrawerOpen(true)}
          >
            {userInitial}
          </button>
        </Badge>
      </header>

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        placement="left"
        closable={false}
        className="mobile-nav-drawer"
        styles={{ body: { padding: 0 }, wrapper: { width: 280 } }}
      >
        <div className="app-sidebar app-sidebar-drawer">
          <SidebarContent {...sidebarProps} />
        </div>
      </Drawer>

      <div className="app-body">
        <aside className="app-sidebar">
          <SidebarContent {...sidebarProps} />
        </aside>

        <main className="app-content">
          <div className="app-content-inner">
            <ConfigProvider theme={WORKSPACE_THEME}>
              <Outlet />
            </ConfigProvider>
          </div>
        </main>
      </div>
    </div>
  );
}
