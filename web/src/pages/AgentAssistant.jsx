import { ClearOutlined, RobotOutlined } from '@ant-design/icons';
import { Button, Card, Empty, Select, Space, Spin } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import AgentChat from '../components/AgentChat';
import PageHeader from '../components/PageHeader';
import { getHomeOverview } from '../services/api';

const LAST_PROJECT_KEY = 'wb_agent_last_project';

export default function AgentAssistant() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [projectId, setProjectId] = useState(null);
  const [meta, setMeta] = useState({ hasMessages: false, streaming: false });
  const chatRef = useRef(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const overview = await getHomeOverview();
        const list = overview?.projects || [];
        setProjects(list);
        if (!list.length) return;
        const saved = Number(localStorage.getItem(LAST_PROJECT_KEY));
        const candidates = [saved, overview?.latest_active_project_id, list[0].id];
        const initial = candidates.find((id) => list.some((p) => p.id === id));
        setProjectId(initial ?? list[0].id);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSelect = (id) => {
    setProjectId(id);
    try {
      localStorage.setItem(LAST_PROJECT_KEY, String(id));
    } catch { /* 记忆失败不影响使用 */ }
  };

  return (
    <div>
      <PageHeader
        title="AI小助手"
        description="基于所选项目的真实数据回答问题：用例、需求覆盖、测试进度、缺陷与业务规则。"
        extra={(
          <Space>
            <Select
              value={projectId}
              onChange={handleSelect}
              placeholder="选择项目"
              style={{ minWidth: 220 }}
              showSearch
              optionFilterProp="label"
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
              disabled={meta.streaming}
            />
            <Button
              icon={<ClearOutlined />}
              disabled={!meta.hasMessages || meta.streaming}
              onClick={() => chatRef.current?.clear()}
            >
              清空对话
            </Button>
          </Space>
        )}
      />

      <Card
        className="surface-card"
        styles={{ body: { padding: 0, height: 'calc(100vh - 200px)', minHeight: 420, display: 'flex', flexDirection: 'column' } }}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
        ) : !projects.length ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ marginTop: 100 }}
            description={(
              <span>
                还没有项目。测试助手需要基于项目数据回答问题，
                <Link to="/">先去创建一个项目</Link>
              </span>
            )}
          />
        ) : (
          <AgentChat ref={chatRef} projectId={projectId} onMetaChange={setMeta} />
        )}
      </Card>

      <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
        <RobotOutlined style={{ marginRight: 6 }} />
        对话按项目保存，与项目页右下角的悬浮助手共享同一份历史。
      </div>
    </div>
  );
}
