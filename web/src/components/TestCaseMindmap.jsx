import { CaretDownOutlined, CaretRightOutlined, FullscreenExitOutlined, FullscreenOutlined, WarningOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons';
import { Button, Drawer, Dropdown, Empty, Segmented, Space, Tag, Tooltip } from 'antd';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { stepsToText } from '../utils/caseText';
import { REVIEW_COLOR, REVIEW_LABEL } from '../pages/generate/constants';
import { RESULT_COLOR, RESULT_LABEL, RESULT_TAG_COLOR } from '../utils/runResult';

const TYPE_LABEL = { functional: '功能', boundary: '边界', exception: '异常' };
const TYPE_CLASS = { functional: 'mm-type-functional', boundary: 'mm-type-boundary', exception: 'mm-type-exception' };
const RESULT_CLASS = {
  passed: 'mm-result-passed',
  failed: 'mm-result-failed',
  blocked: 'mm-result-blocked',
  pending: 'mm-result-pending',
};
const REVIEW_CLASS = {
  pending: 'mm-review-pending',
  to_confirm: 'mm-review-to-confirm',
  adopted: 'mm-review-adopted',
  rejected: 'mm-review-rejected',
  edited: 'mm-review-edited',
};
const REVIEW_BADGE_COLOR = {
  adopted: '#16a34a',
  rejected: '#dc2626',
  to_confirm: '#ea580c',
  edited: '#2563eb',
  pending: '#94a3b8',
};
const PRIORITY_CLASS = { P0: 'tag-p0', P1: 'tag-p1', P2: 'tag-p2' };
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 2.5;
const ZOOM_STEP = 0.1;
const ZOOM_PRESETS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const PAN_MARGIN = 24; // 复位时内容距画布左上角的留白

function groupCasesByModuleFeature(cases) {
  const modules = {};
  cases.forEach((c) => {
    const mod = c.module?.trim() || '未分类';
    const feat = c.feature?.trim() || '未关联功能点';
    if (!modules[mod]) modules[mod] = {};
    if (!modules[mod][feat]) modules[mod][feat] = [];
    modules[mod][feat].push(c);
  });
  return modules;
}

function summarizeResults(list) {
  if (!list.length || list[0].result === undefined) return null;
  return {
    passed: list.filter((c) => c.result === 'passed').length,
    failed: list.filter((c) => c.result === 'failed').length,
    blocked: list.filter((c) => c.result === 'blocked').length,
    pending: list.filter((c) => c.result === 'pending').length,
  };
}

function summarizeReviews(list) {
  if (!list.length || list[0].review_status === undefined) return null;
  return {
    adopted: list.filter((c) => c.review_status === 'adopted').length,
    rejected: list.filter((c) => c.review_status === 'rejected').length,
    to_confirm: list.filter((c) => c.review_status === 'to_confirm').length,
    pending: list.filter((c) => ['pending', 'edited'].includes(c.review_status)).length,
  };
}

function buildModuleNodes(modules, keyPrefix = '') {
  return Object.entries(modules).map(([mod, feats]) => {
    const featureNodes = Object.entries(feats).map(([feat, list]) => {
      const types = new Set(list.map((c) => c.case_type));
      const missing = [];
      if (!types.has('boundary')) missing.push('边界');
      if (!types.has('exception')) missing.push('异常');
      return {
        key: `${keyPrefix}m:${mod}|f:${feat}`,
        type: 'feature',
        label: feat,
        count: list.length,
        missing,
        stats: summarizeResults(list),
        reviewStats: summarizeReviews(list),
        children: list.map((c) => ({
          key: `case:${c.id}`,
          type: 'case',
          label: c.title,
          data: c,
          leaf: true,
        })),
      };
    });
    const modCount = featureNodes.reduce((n, f) => n + f.count, 0);
    const modCases = Object.values(feats).flat();
    return {
      key: `${keyPrefix}m:${mod}`,
      type: 'module',
      label: mod,
      count: modCount,
      stats: summarizeResults(modCases),
      reviewStats: summarizeReviews(modCases),
      children: featureNodes,
    };
  });
}

function buildMindmap(cases, rootLabel, multiProject = false) {
  if (multiProject) {
    const projects = {};
    cases.forEach((c) => {
      const pid = c.project_id;
      const pname = c.project_name || `项目 #${pid}`;
      if (!projects[pid]) projects[pid] = { name: pname, cases: [] };
      projects[pid].cases.push(c);
    });

    const projectNodes = Object.entries(projects).map(([pid, proj]) => {
      const modules = groupCasesByModuleFeature(proj.cases);
      const moduleNodes = buildModuleNodes(modules, `p:${pid}|`);
      const count = proj.cases.length;
      return {
        key: `p:${pid}`,
        type: 'project',
        label: proj.name,
        count,
        children: moduleNodes,
      };
    });

    return {
      key: 'root',
      type: 'root',
      label: rootLabel || '全部用例',
      count: cases.length,
      children: projectNodes,
    };
  }

  const modules = groupCasesByModuleFeature(cases);
  const moduleNodes = buildModuleNodes(modules);

  return {
    key: 'root',
    type: 'root',
    label: rootLabel || '当前项目',
    count: cases.length,
    stats: summarizeResults(cases),
    reviewStats: summarizeReviews(cases),
    children: moduleNodes,
  };
}

function collectKeysByType(node, type, acc = []) {
  if (node.type === type) acc.push(node.key);
  (node.children || []).forEach((child) => collectKeysByType(child, type, acc));
  return acc;
}

function collectAllKeys(node, acc = []) {
  acc.push(node.key);
  (node.children || []).forEach((child) => collectAllKeys(child, acc));
  return acc;
}

function Branch({ node, collapsed, onToggle, colorBy, onSelectCase }) {
  const hasChildren = node.children && node.children.length > 0;
  const isCollapsed = collapsed.has(node.key);

  return (
    <div className="mm-subtree">
      <NodeCard
        node={node}
        collapsible={hasChildren}
        isCollapsed={isCollapsed}
        onToggle={onToggle}
        colorBy={colorBy}
        onSelectCase={onSelectCase}
      />
      {hasChildren && !isCollapsed && (
        <div className="mm-children">
          {node.children.map((child) => (
            <div className="mm-child-conn" key={child.key}>
              <Branch
                node={child}
                collapsed={collapsed}
                onToggle={onToggle}
                colorBy={colorBy}
                onSelectCase={onSelectCase}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultBadge({ stats }) {
  if (!stats) return null;
  return (
    <span className="mm-result-badge">
      {stats.passed > 0 && <span style={{ color: RESULT_COLOR.passed }}>{stats.passed}✓</span>}
      {stats.failed > 0 && <span style={{ color: RESULT_COLOR.failed }}>{stats.failed}✗</span>}
      {stats.blocked > 0 && <span style={{ color: RESULT_COLOR.blocked }}>{stats.blocked}⊘</span>}
      {stats.pending > 0 && <span style={{ color: RESULT_COLOR.pending }}>{stats.pending}○</span>}
    </span>
  );
}

function ReviewBadge({ stats }) {
  if (!stats) return null;
  return (
    <span className="mm-result-badge">
      {stats.adopted > 0 && <span style={{ color: REVIEW_BADGE_COLOR.adopted }}>{stats.adopted}✓</span>}
      {stats.rejected > 0 && <span style={{ color: REVIEW_BADGE_COLOR.rejected }}>{stats.rejected}✗</span>}
      {stats.to_confirm > 0 && <span style={{ color: REVIEW_BADGE_COLOR.to_confirm }}>{stats.to_confirm}?</span>}
      {stats.pending > 0 && <span style={{ color: REVIEW_BADGE_COLOR.pending }}>{stats.pending}○</span>}
    </span>
  );
}

function NodeCard({ node, collapsible, isCollapsed, onToggle, colorBy, onSelectCase }) {
  if (node.type === 'case') {
    const c = node.data;
    const colorClass = colorBy === 'type'
      ? TYPE_CLASS[c.case_type]
      : colorBy === 'result'
        ? (RESULT_CLASS[c.result] || '')
        : colorBy === 'review'
          ? (REVIEW_CLASS[c.review_status] || '')
          : '';
    return (
      <button
        type="button"
        className={`mm-node mm-node-case ${colorClass}`}
        onClick={() => onSelectCase(c)}
      >
        <span className="mm-case-title">{node.label || '未命名用例'}</span>
        <span className="mm-case-tags">
          {colorBy === 'result' && c.result !== undefined ? (
            <Tag color={RESULT_TAG_COLOR[c.result]} variant="filled">{RESULT_LABEL[c.result] || c.result}</Tag>
          ) : colorBy === 'review' && c.review_status !== undefined ? (
            <Tag color={REVIEW_COLOR[c.review_status]} variant="filled">{REVIEW_LABEL[c.review_status] || c.review_status}</Tag>
          ) : (
            <>
              <Tag className={PRIORITY_CLASS[c.priority] || ''} variant="filled">{c.priority}</Tag>
              <Tag variant="filled">{TYPE_LABEL[c.case_type] || c.case_type}</Tag>
            </>
          )}
        </span>
      </button>
    );
  }

  return (
    <div
      className={`mm-node mm-node-${node.type}${collapsible ? ' mm-clickable' : ''}`}
      onClick={collapsible ? () => onToggle(node.key) : undefined}
    >
      {collapsible && (
        <span className="mm-caret">
          {isCollapsed ? <CaretRightOutlined /> : <CaretDownOutlined />}
        </span>
      )}
      <span className="mm-node-label">{node.label}</span>
      <span className="mm-node-count">{node.count}</span>
      {colorBy === 'result' && <ResultBadge stats={node.stats} />}
      {colorBy === 'review' && <ReviewBadge stats={node.reviewStats} />}
      {node.type === 'feature' && node.missing && node.missing.length > 0 && (
        <Tooltip title={`缺少${node.missing.join('、')}用例`}>
          <WarningOutlined className="mm-node-warn" />
        </Tooltip>
      )}
    </div>
  );
}

function defaultCollapsedKeys(tree, multiProject) {
  const keys = collectKeysByType(tree, 'feature');
  if (multiProject) {
    collectKeysByType(tree, 'project').forEach((k) => keys.push(k));
  }
  return new Set(keys);
}

export default function TestCaseMindmap({
  cases = [],
  projectName = '',
  rootLabel,
  multiProject = false,
  showFullMapButton = false,
  executionMode = false,
  reviewMode = false,
  onEditCase,
  onReviewCase,
  onMarkResult,
}) {
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [colorBy, setColorBy] = useState(executionMode ? 'result' : reviewMode ? 'review' : 'priority');
  const [activeCase, setActiveCase] = useState(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [contentSize, setContentSize] = useState({ w: 0, h: 0 });
  const [fitPending, setFitPending] = useState(false);
  const canvasRef = useRef(null);
  const innerRef = useRef(null);
  // 视野用 translate 平移（不用滚动条）：平移量可以为负，
  // 内容比画布小或贴边时也能保持缩放锚点不动
  const panRef = useRef({ x: PAN_MARGIN, y: PAN_MARGIN });
  const zoomRef = useRef(1);

  const label = rootLabel || projectName || '当前项目';
  const tree = useMemo(
    () => buildMindmap(cases, label, multiProject),
    [cases, label, multiProject],
  );

  // 只在树结构（节点增减）变化时重置折叠与视野；
  // 单条用例标记结果 / 评审后数据刷新不应打断当前浏览位置
  const treeSignature = useMemo(() => collectAllKeys(tree).join('|'), [tree]);
  useEffect(() => {
    setCollapsed(defaultCollapsedKeys(tree, multiProject));
    setFullscreen(false);
    resetView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeSignature, multiProject]);

  const updateContentSize = useCallback(() => {
    if (!innerRef.current) return;
    setContentSize({
      w: innerRef.current.offsetWidth,
      h: innerRef.current.offsetHeight,
    });
  }, []);

  useEffect(() => {
    updateContentSize();
  }, [tree, collapsed, updateContentSize]);

  useEffect(() => {
    const el = innerRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(updateContentSize);
    observer.observe(el);
    return () => observer.disconnect();
  }, [updateContentSize, tree, collapsed]);

  // 把当前平移量 + 缩放写到内容元素上（视野的唯一事实来源是 panRef/zoomRef）
  const applyTransform = useCallback(() => {
    const inner = innerRef.current;
    if (!inner) return;
    const { x, y } = panRef.current;
    inner.style.transform = `translate(${x}px, ${y}px) scale(${zoomRef.current})`;
    inner.style.transformOrigin = '0 0';
  }, []);

  // 防止内容被拖到完全看不见：保证画布内至少留 60px 内容可见
  const clampPan = useCallback((pan, nextZoom) => {
    const canvas = canvasRef.current;
    const inner = innerRef.current;
    if (!canvas || !inner) return pan;
    const m = 60;
    const w = inner.offsetWidth * nextZoom;
    const h = inner.offsetHeight * nextZoom;
    return {
      x: Math.min(canvas.clientWidth - m, Math.max(m - w, pan.x)),
      y: Math.min(canvas.clientHeight - m, Math.max(m - h, pan.y)),
    };
  }, []);

  // 带锚点缩放：先算出锚点（默认画布中心）对应的内容坐标，
  // 缩放后调整平移量，让该内容点在屏幕上保持不动
  const applyZoom = useCallback((value, anchor) => {
    const prev = zoomRef.current;
    const target = typeof value === 'function' ? value(prev) : value;
    const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, +target.toFixed(2)));
    if (clamped === prev) return;
    const canvas = canvasRef.current;
    if (canvas) {
      const ax = anchor?.x ?? canvas.clientWidth / 2;
      const ay = anchor?.y ?? canvas.clientHeight / 2;
      const ratio = clamped / prev;
      const pan = panRef.current;
      panRef.current = clampPan({
        x: ax - (ax - pan.x) * ratio,
        y: ay - (ay - pan.y) * ratio,
      }, clamped);
    }
    zoomRef.current = clamped;
    setZoom(clamped);
    applyTransform();
  }, [applyTransform, clampPan]);

  // zoom 状态变化（含组件重挂载）后同步 transform
  useLayoutEffect(() => {
    zoomRef.current = zoom;
    applyTransform();
  }, [zoom, fullscreen, applyTransform]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        // Ctrl/Cmd + 滚轮：以鼠标位置为锚点缩放
        const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
        const rect = canvas.getBoundingClientRect();
        applyZoom((z) => z + delta, { x: e.clientX - rect.left, y: e.clientY - rect.top });
      } else {
        // 普通滚轮/触控板：平移视野
        const pan = panRef.current;
        panRef.current = clampPan({ x: pan.x - e.deltaX, y: pan.y - e.deltaY }, zoomRef.current);
        applyTransform();
      }
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
    // 全图切换会把画布重新挂载（portal），必须重新绑定滚轮监听
  }, [fullscreen, applyZoom, applyTransform, clampPan]);

  // 按住画布空白处拖拽平移视野
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    let drag = null;
    const onPointerDown = (e) => {
      if (e.button !== 0) return;
      // 点在节点或按钮上时不启动拖拽，保留点击展开/查看详情
      if (e.target.closest('.mm-node, button, a, input')) return;
      drag = { x: e.clientX, y: e.clientY, panX: panRef.current.x, panY: panRef.current.y };
      canvas.classList.add('mm-panning');
    };
    const onPointerMove = (e) => {
      if (!drag) return;
      panRef.current = clampPan({
        x: drag.panX + (e.clientX - drag.x),
        y: drag.panY + (e.clientY - drag.y),
      }, zoomRef.current);
      applyTransform();
    };
    const endDrag = () => {
      drag = null;
      canvas.classList.remove('mm-panning');
    };
    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', endDrag);
    return () => {
      canvas.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', endDrag);
    };
  }, [fullscreen, applyTransform, clampPan]);

  const zoomIn = () => applyZoom((z) => z + ZOOM_STEP);
  const zoomOut = () => applyZoom((z) => z - ZOOM_STEP);
  // 适配缩放：让整棵树刚好放进画布并居中
  const fitToView = useCallback(() => {
    const canvas = canvasRef.current;
    const inner = innerRef.current;
    if (!canvas || !inner) return;
    const w = inner.offsetWidth;
    const h = inner.offsetHeight;
    const availW = canvas.clientWidth;
    const availH = canvas.clientHeight;
    if (!w || !h || availW <= 0 || availH <= 0) return;
    const fit = Math.min(availW / w, availH / h, 1);
    const z = Math.max(ZOOM_MIN, Math.floor(fit * 100) / 100);
    panRef.current = { x: (availW - w * z) / 2, y: (availH - h * z) / 2 };
    zoomRef.current = z;
    setZoom(z);
    applyTransform();
  }, [applyTransform]);

  // 视野复位：回到左上角、100%
  const resetView = useCallback(() => {
    panRef.current = { x: PAN_MARGIN, y: PAN_MARGIN };
    zoomRef.current = 1;
    setZoom(1);
    applyTransform();
  }, [applyTransform]);

  // 进入全图：等展开全部节点、内容尺寸测量完成后再做适配
  useEffect(() => {
    if (!fullscreen || !fitPending) return;
    fitToView();
    setFitPending(false);
  }, [fullscreen, fitPending, contentSize, fitToView]);

  useEffect(() => {
    if (!activeCase) return;
    const latest = cases.find((c) => c.id === activeCase.id);
    if (latest) setActiveCase(latest);
  }, [cases, activeCase?.id]);

  const exitFullscreen = useCallback(() => {
    setFullscreen(false);
    resetView();
    setCollapsed(defaultCollapsedKeys(tree, multiProject));
  }, [tree, multiProject, resetView]);

  useEffect(() => {
    if (!fullscreen) return undefined;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (e) => {
      if (e.key === 'Escape') exitFullscreen();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [fullscreen, exitFullscreen]);

  const toggle = (key) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const expandAll = () => setCollapsed(new Set());
  const collapseToProject = () => setCollapsed(new Set(collectKeysByType(tree, 'project')));
  const collapseToModule = () => setCollapsed(new Set(collectKeysByType(tree, 'module')));
  const collapseToFeature = () => setCollapsed(defaultCollapsedKeys(tree, multiProject));

  const toggleFullscreen = () => {
    setFullscreen((prev) => {
      const next = !prev;
      if (next) {
        setCollapsed(new Set());
        setFitPending(true); // 展开全部后自动缩放到能看到整棵树
      } else {
        setCollapsed(defaultCollapsedKeys(tree, multiProject));
        resetView();
      }
      return next;
    });
  };

  if (!cases.length) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div>
            <div className="empty-state-title">暂无用例</div>
            <div className="empty-state-desc">采纳 AI 生成的用例入库后，会在此以脑图呈现结构</div>
          </div>
        }
      />
    );
  }

  const content = (
    <div className={`mm-wrap${fullscreen ? ' mm-wrap-fullscreen' : ''}`}>
      <div className="mm-toolbar">
        <Space size={8} wrap>
          {showFullMapButton && (
            <button type="button" className={`mm-toolbar-btn${fullscreen ? ' mm-toolbar-btn-active' : ''}`} onClick={toggleFullscreen}>
              {fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              {fullscreen ? '退出全图' : '全图展示'}
            </button>
          )}
          <button type="button" className="mm-toolbar-btn" onClick={expandAll}>展开全部</button>
          {multiProject && (
            <button type="button" className="mm-toolbar-btn" onClick={collapseToProject}>折叠到项目</button>
          )}
          <button type="button" className="mm-toolbar-btn" onClick={collapseToFeature}>折叠到功能点</button>
          <button type="button" className="mm-toolbar-btn" onClick={collapseToModule}>折叠到模块</button>
          <Space size={4} className="mm-zoom-controls">
            <Tooltip title="缩小">
              <button type="button" className="mm-toolbar-btn mm-toolbar-btn-icon" onClick={zoomOut} disabled={zoom <= ZOOM_MIN}>
                <ZoomOutOutlined />
              </button>
            </Tooltip>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'fit', label: '适配屏幕' },
                  { type: 'divider' },
                  ...ZOOM_PRESETS.map((v) => ({ key: String(v), label: `${Math.round(v * 100)}%` })),
                ],
                onClick: ({ key }) => {
                  if (key === 'fit') fitToView();
                  else applyZoom(Number(key));
                },
              }}
            >
              <button type="button" className="mm-toolbar-btn mm-zoom-label">
                {Math.round(zoom * 100)}%
              </button>
            </Dropdown>
            <Tooltip title="放大">
              <button type="button" className="mm-toolbar-btn mm-toolbar-btn-icon" onClick={zoomIn} disabled={zoom >= ZOOM_MAX}>
                <ZoomInOutlined />
              </button>
            </Tooltip>
          </Space>
        </Space>
        <Space size={8} align="center">
          <span className="mm-toolbar-label">用例着色</span>
          <Segmented
            size="small"
            value={colorBy}
            onChange={setColorBy}
            options={[
              ...(executionMode ? [{ label: '结果', value: 'result' }] : []),
              ...(reviewMode ? [{ label: '评审', value: 'review' }] : []),
              { label: '优先级', value: 'priority' },
              { label: '类型', value: 'type' },
            ]}
          />
        </Space>
      </div>

      <div ref={canvasRef} className={`mm-canvas${fullscreen ? ' mm-canvas-fullscreen' : ''}`}>
        <div ref={innerRef} className="mm-canvas-inner">
          <Branch
            node={tree}
            collapsed={collapsed}
            onToggle={toggle}
            colorBy={colorBy}
            onSelectCase={setActiveCase}
          />
        </div>
      </div>

      <Drawer
        title={activeCase?.title || '用例详情'}
        width={460}
        open={!!activeCase}
        onClose={() => setActiveCase(null)}
        extra={onEditCase && activeCase ? (
          <Button type="link" onClick={() => onEditCase(activeCase)}>编辑</Button>
        ) : null}
      >
        {activeCase && (
          <div className="mm-detail">
            <div className="mm-detail-tags">
              {reviewMode ? (
                activeCase.review_status !== undefined && (
                  <Tag color={REVIEW_COLOR[activeCase.review_status]} variant="filled">
                    {REVIEW_LABEL[activeCase.review_status] || activeCase.review_status}
                  </Tag>
                )
              ) : (
                <>
                  {activeCase.result !== undefined && (
                    <Tag color={RESULT_TAG_COLOR[activeCase.result]} variant="filled">
                      {RESULT_LABEL[activeCase.result] || activeCase.result}
                    </Tag>
                  )}
                  <Tag className={PRIORITY_CLASS[activeCase.priority] || ''} variant="filled">{activeCase.priority}</Tag>
                  <Tag variant="filled">{TYPE_LABEL[activeCase.case_type] || activeCase.case_type}</Tag>
                  {activeCase.project_name && <Tag variant="filled">{activeCase.project_name}</Tag>}
                  {activeCase.module && <Tag variant="filled">{activeCase.module}</Tag>}
                  {activeCase.feature && <Tag variant="filled">{activeCase.feature}</Tag>}
                </>
              )}
            </div>
            {reviewMode && onReviewCase && !['adopted', 'rejected'].includes(activeCase.review_status) && (
              <div className="mm-review-actions">
                <Button type="primary" onClick={() => onReviewCase(activeCase, 'adopt')}>采纳</Button>
                <Button onClick={() => onReviewCase(activeCase, 'to_confirm')}>待确认</Button>
                <Button danger onClick={() => onReviewCase(activeCase, 'reject')}>驳回</Button>
              </div>
            )}
            {executionMode && onMarkResult && (
              <div className="mm-review-actions">
                {['passed', 'failed', 'blocked', 'pending'].map((r) => (
                  <Button
                    key={r}
                    className={`run-result-btn run-result-btn-${r}${activeCase.result === r ? ' active' : ''}`}
                    onClick={() => activeCase.result !== r && onMarkResult(activeCase, r)}
                  >
                    {RESULT_LABEL[r] || r}
                  </Button>
                ))}
              </div>
            )}
            <div className="case-detail">
              <div className="case-detail-row">
                <span className="case-detail-label">前置条件</span>{activeCase.precondition || '无'}
              </div>
              <div className="case-detail-row case-detail-row-block">
                <span className="case-detail-label">操作步骤</span>
                <span style={{ whiteSpace: 'pre-wrap' }}>{stepsToText(activeCase.steps)}</span>
              </div>
              <div className="case-detail-row">
                <span className="case-detail-label">预期结果</span>{activeCase.expected_result || '无'}
              </div>
              {activeCase.note && (
                <div className="case-detail-row">
                  <span className="case-detail-label">执行备注</span>{activeCase.note}
                </div>
              )}
              {activeCase.defect_ref && (
                <div className="case-detail-row">
                  <span className="case-detail-label">缺陷单号</span>{activeCase.defect_ref}
                </div>
              )}
              {reviewMode && activeCase.reject_reason && (
                <div className="case-detail-row">
                  <span className="case-detail-label">驳回原因</span>{activeCase.reject_reason}
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );

  // 全图时渲染到 body：避免任何祖先的 transform/filter 使 fixed 定位失效
  return fullscreen ? createPortal(content, document.body) : content;
}
