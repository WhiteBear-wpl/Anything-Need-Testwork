import {
  CheckCircleOutlined,
  CodeOutlined,
  FileTextOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  App, Badge, Button, Empty, Modal, Radio, Segmented, Spin, Tag,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  generateSkeleton, getProject, getSkeleton, getSkeletonOptions, updateSkeletonFiles,
} from '../services/api';

export default function SkeletonPage() {
  const { projectId } = useParams();
  const { message } = App.useApp();
  const [project, setProject] = useState(null);
  const [skeleton, setSkeleton] = useState(null);
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [genOpen, setGenOpen] = useState(false);
  const [genForm, setGenForm] = useState({ language: 'Python', mode: 'template', base_url: '' });

  const load = async () => {
    setLoading(true);
    try {
      const [proj, opts] = await Promise.all([getProject(projectId), getSkeletonOptions()]);
      setProject(proj);
      setOptions(opts);
      const sk = await getSkeleton(projectId);
      setSkeleton(sk);
      setGenForm((f) => ({ ...f, base_url: proj.base_url || '' }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [projectId]);

  const selectedFile = useMemo(
    () => (skeleton?.files || []).find((f) => f.path === selectedPath)
      || (skeleton?.files || [])[0]
      || null,
    [skeleton, selectedPath],
  );

  const runGenerate = async () => {
    setGenOpen(false);
    setLoading(true);
    try {
      const sk = await generateSkeleton(projectId, genForm);
      setSkeleton(sk);
      setSelectedPath(null);
      setEditing(false);
      message.success(
        genForm.mode === 'ai'
          ? `AI 已生成 ${sk.files.length} 个骨架文件`
          : `已生成 ${sk.language} 测试骨架`,
      );
    } finally {
      setLoading(false);
    }
  };

  const saveEdit = async () => {
    if (!selectedFile) return;
    const files = (skeleton.files || []).map((f) =>
      f.path === selectedFile.path ? { ...f, content: draft } : f,
    );
    await updateSkeletonFiles(projectId, files);
    setSkeleton((s) => ({ ...s, files }));
    setEditing(false);
    message.success('文件已保存');
  };

  if (loading && !skeleton && !project) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;
  }

  // 未初始化：选择技术栈与模式
  if (!skeleton) {
    return (
      <div className="skeleton-init">
        <h2 className="skeleton-init-title">初始化自动化测试骨架</h2>
        <p className="skeleton-init-desc">
          为「{project?.name}」生成一套可直接运行的接口测试目录。支持模板生成与 AI 驱动定制。
        </p>
        <div className="skeleton-options">
          {options.map((opt) => {
            const active = genForm.language === opt.language;
            return (
              <button
                key={opt.language}
                type="button"
                className={`skeleton-option${active ? ' active' : ''}`}
                onClick={() => setGenForm((f) => ({ ...f, language: opt.language }))}
              >
                <div className="skeleton-option-icon"><CodeOutlined /></div>
                <div className="skeleton-option-name">{opt.language}</div>
                <div className="skeleton-option-fw">{opt.framework}</div>
                <div className="skeleton-option-blurb">{opt.blurb}</div>
              </button>
            );
          })}
        </div>

        <div className="skeleton-mode">
          <span className="skeleton-mode-label">生成方式：</span>
          <Segmented
            value={genForm.mode}
            onChange={(v) => setGenForm((f) => ({ ...f, mode: v }))}
            options={[
              { label: (<span><FileTextOutlined /> 静态模板</span>), value: 'template' },
              { label: (<span><RobotOutlined /> AI 驱动定制</span>), value: 'ai' },
            ]}
          />
        </div>

        <div className="skeleton-baseurl">
          <span className="skeleton-mode-label">被测服务地址（用于骨架配置）：</span>
          <input
            className="skeleton-baseurl-input"
            value={genForm.base_url}
            onChange={(e) => setGenForm((f) => ({ ...f, base_url: e.target.value }))}
            placeholder="https://api.example.com"
          />
        </div>

        <div style={{ marginTop: 20 }}>
          <Button type="primary" size="large" icon={<ThunderboltOutlined />} onClick={runGenerate}>
            {genForm.mode === 'ai' ? 'AI 生成骨架' : '初始化骨架'}
          </Button>
        </div>
      </div>
    );
  }

  // 已初始化：文件树 + 内容
  return (
    <div className="skeleton-page">
      <aside className="skeleton-side">
        <div className="skeleton-side-header">
          <div className="skeleton-side-title">
            <CheckCircleOutlined style={{ color: '#0F766E' }} />
            <span>测试骨架</span>
          </div>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => setGenOpen(true)}>
            重新生成
          </Button>
        </div>
        <div className="skeleton-side-meta">
          <Tag color="geekblue">{skeleton.language}</Tag>
          <Tag>{skeleton.framework}</Tag>
          {skeleton.mode === 'ai' && <Tag color="green">AI 定制</Tag>}
        </div>
        <div className="skeleton-side-files">
          {skeleton.files.map((f) => (
            <button
              key={f.path}
              type="button"
              className={`skeleton-file${selectedFile?.path === f.path ? ' active' : ''}`}
              onClick={() => { setSelectedPath(f.path); setEditing(false); }}
            >
              <FileTextOutlined />
              <span>{f.path}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className="skeleton-main">
        {!selectedFile ? (
          <Empty description="从左侧选择一个文件" />
        ) : editing ? (
          <div className="skeleton-edit">
            <div className="skeleton-edit-bar">
              <span className="skeleton-edit-path">{selectedFile.path}</span>
              <div>
                <Button size="small" onClick={() => setEditing(false)}>取消</Button>
                <Button size="small" type="primary" icon={<SaveOutlined />} onClick={saveEdit} style={{ marginLeft: 8 }}>
                  保存
                </Button>
              </div>
            </div>
            <textarea
              className="skeleton-textarea"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
            />
          </div>
        ) : (
          <div className="skeleton-view">
            <div className="skeleton-view-bar">
              <span className="skeleton-view-path">{selectedFile.path}</span>
              <Button
                size="small"
                icon={<FileTextOutlined />}
                onClick={() => { setDraft(selectedFile.content); setEditing(true); }}
              >
                编辑
              </Button>
            </div>
            <pre className="skeleton-code"><code>{selectedFile.content}</code></pre>
          </div>
        )}
      </main>

      <Modal
        title="重新生成测试骨架"
        open={genOpen}
        onOk={runGenerate}
        onCancel={() => setGenOpen(false)}
        okText="生成"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 6, fontWeight: 500 }}>语言 / 框架</div>
          <Radio.Group
            value={genForm.language}
            onChange={(e) => setGenForm((f) => ({ ...f, language: e.target.value }))}
            options={options.map((o) => ({ label: `${o.language} · ${o.framework}`, value: o.language }))}
          />
        </div>
        <div style={{ marginBottom: 6, fontWeight: 500 }}>生成方式</div>
        <Segmented
          value={genForm.mode}
          onChange={(v) => setGenForm((f) => ({ ...f, mode: v }))}
          options={[
            { label: '静态模板', value: 'template' },
            { label: 'AI 驱动定制', value: 'ai' },
          ]}
        />
        {genForm.mode === 'ai' && (
          <div style={{ marginTop: 10, color: '#64748B', fontSize: 12 }}>
            AI 会基于项目信息与知识生成定制骨架与测试说明。
          </div>
        )}
      </Modal>
    </div>
  );
}
