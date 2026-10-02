import {
  DeleteOutlined, EllipsisOutlined, FileTextOutlined, InfoCircleOutlined, SearchOutlined, UploadOutlined,
} from '@ant-design/icons';
import {
  Alert, App, Button, Card, Drawer, Dropdown, Empty, Input, List, Space, Spin, Tag, Tooltip, Upload,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  deleteKnowledgeDoc,
  getKnowledgeChunks,
  getKnowledgeDocs,
  searchKnowledge,
  uploadKnowledgeDoc,
} from '../services/api';

const SOURCE_LABEL = { doc: '业务文档', case: '历史用例', defect: '缺陷记录' };
const MATCH_META = {
  both: { color: 'purple', label: '语义 + 关键词', hint: '向量与 BM25 两路检索都命中，相关性最可靠' },
  vector: { color: 'blue', label: '语义', hint: '向量检索命中（语义相近）' },
  keyword: { color: 'cyan', label: '关键词', hint: 'BM25 关键词检索命中（精确词匹配）' },
};
const STATUS_META = {
  ready: { color: 'green', label: '已入库' },
  processing: { color: 'blue', label: '处理中' },
  failed: { color: 'red', label: '失败' },
};

export default function KnowledgePanel({ projectId }) {
  const { message, modal } = App.useApp();
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  const [chunkDrawer, setChunkDrawer] = useState({ open: false, doc: null, chunks: [], loading: false });

  const [docKeyword, setDocKeyword] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState(null);
  const [searching, setSearching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDocs(await getKnowledgeDocs(projectId));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const filteredDocs = useMemo(() => {
    const kw = docKeyword.trim().toLowerCase();
    if (!kw) return docs;
    return docs.filter((d) => d.title?.toLowerCase().includes(kw));
  }, [docs, docKeyword]);

  const handleUpload = async (file) => {
    setUploading(true);
    try {
      await uploadKnowledgeDoc(projectId, file);
      message.success(`「${file.name}」已入库`);
      load();
    } catch (err) {
      message.error(err.response?.data?.detail || '入库失败，请检查 Embedding 模型配置');
    } finally {
      setUploading(false);
    }
    return false;
  };

  const handleDelete = async (doc) => {
    await deleteKnowledgeDoc(projectId, doc.id);
    message.success('已删除');
    load();
  };

  const openChunks = async (doc) => {
    setChunkDrawer({ open: true, doc, chunks: [], loading: true });
    try {
      const chunks = await getKnowledgeChunks(projectId, doc.id);
      setChunkDrawer((prev) => ({ ...prev, chunks, loading: false }));
    } catch {
      setChunkDrawer((prev) => ({ ...prev, loading: false }));
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      setSearchHits(await searchKnowledge(projectId, searchQuery.trim()));
    } catch (err) {
      message.error(err.response?.data?.detail || '检索失败');
    } finally {
      setSearching(false);
    }
  };

  const docMenu = (doc) => ({
    items: [
      {
        key: 'chunks',
        icon: <FileTextOutlined />,
        label: '查看分块',
        onClick: () => openChunks(doc),
      },
      { type: 'divider' },
      {
        key: 'delete',
        icon: <DeleteOutlined />,
        label: '删除',
        danger: true,
        onClick: () => {
          modal.confirm({
            title: `删除「${doc.title}」？`,
            content: '该知识文档及其向量将一并删除，AI 生成不再引用。',
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: () => handleDelete(doc),
          });
        },
      },
    ],
  });

  return (
    <div>
      <Card
        className="surface-card"
        title="知识文档"
        style={{ marginBottom: 16 }}
        extra={(
          <Space>
            {docs.length > 0 && (
              <Input.Search
                placeholder="搜索文档标题"
                allowClear
                value={docKeyword}
                onChange={(e) => setDocKeyword(e.target.value)}
                style={{ width: 200 }}
              />
            )}
            <Upload
              accept=".md,.txt,.docx"
              showUploadList={false}
              disabled={uploading}
              beforeUpload={handleUpload}
            >
              <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
                {uploading ? '向量化入库中' : '上传文档'}
              </Button>
            </Upload>
            <Tooltip title="支持 Markdown / Word / 文本，上传后按标题层级自动分块并向量化，AI 生成用例时可引用">
              <InfoCircleOutlined className="page-title-hint" />
            </Tooltip>
          </Space>
        )}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : docs.length === 0 ? (
          <Empty description="暂无知识文档，上传后 AI 生成可引用" />
        ) : filteredDocs.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的文档" />
        ) : (
          <div className="knowledge-grid">
            {filteredDocs.map((doc) => {
              const meta = STATUS_META[doc.status] || { color: 'default', label: doc.status };
              return (
                <Card
                  key={doc.id}
                  className="knowledge-card"
                  hoverable
                  onClick={() => openChunks(doc)}
                >
                  <div className="knowledge-card-header">
                    <div className="knowledge-card-icon"><FileTextOutlined /></div>
                    <div className="knowledge-card-title" title={doc.title}>{doc.title}</div>
                    <span onClick={(e) => e.stopPropagation()}>
                      <Dropdown menu={docMenu(doc)} trigger={['click']}>
                        <Button type="text" size="small" icon={<EllipsisOutlined />} />
                      </Dropdown>
                    </span>
                  </div>
                  <div className="knowledge-card-tags">
                    <Tag color={meta.color} title={doc.error_message || ''}>{meta.label}</Tag>
                    <Tag>{SOURCE_LABEL[doc.source_type] || doc.source_type}</Tag>
                  </div>
                  <div className="knowledge-card-meta">
                    {doc.chunk_count} 个分块 · {doc.created_at ? new Date(doc.created_at).toLocaleDateString('zh-CN') : '—'} 入库
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </Card>

      <Card
        className="surface-card"
        style={{ marginBottom: 16 }}
        title={(
          <span className="page-title-row">
            检索测试
            <Tooltip title="输入问题模拟 AI 生成时的知识召回，验证能否命中正确的知识内容">
              <InfoCircleOutlined className="page-title-hint" />
            </Tooltip>
          </span>
        )}
      >
        <Space.Compact style={{ width: '100%', maxWidth: 480, marginBottom: searchHits !== null ? 16 : 0 }}>
          <Input
            placeholder="输入问题测试检索效果，例如：订单退款的边界规则"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onPressEnter={handleSearch}
            allowClear
          />
          <Button icon={<SearchOutlined />} loading={searching} onClick={handleSearch}>检索</Button>
        </Space.Compact>
        {searchHits !== null && (
          searchHits.length === 0 ? (
            <Alert type="warning" showIcon description="没有命中相关知识（语义相似度低于阈值且无关键词命中）" />
          ) : (
            <List
              size="small"
              bordered
              dataSource={searchHits}
              renderItem={(hit) => {
                const match = MATCH_META[hit.match] || MATCH_META.vector;
                return (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <Space style={{ marginBottom: 4 }}>
                        <Tooltip title={match.hint}>
                          <Tag color={match.color}>{match.label}</Tag>
                        </Tooltip>
                        {hit.score > 0 && <Tag color="blue">相关度 {(hit.score * 100).toFixed(0)}%</Tag>}
                        <span style={{ fontWeight: 600 }}>
                          《{hit.title}》{hit.heading ? ` · ${hit.heading}` : ''}
                        </span>
                      </Space>
                      <div style={{ color: 'var(--muted)', fontSize: 13 }}>{hit.content}</div>
                    </div>
                  </List.Item>
                );
              }}
            />
          )
        )}
      </Card>

      <Drawer
        title={chunkDrawer.doc ? `分块预览：${chunkDrawer.doc.title}` : '分块预览'}
        open={chunkDrawer.open}
        width={560}
        onClose={() => setChunkDrawer({ open: false, doc: null, chunks: [], loading: false })}
      >
        <List
          size="small"
          loading={chunkDrawer.loading}
          dataSource={chunkDrawer.chunks}
          renderItem={(chunk, idx) => (
            <List.Item>
              <div style={{ width: '100%' }}>
                <div style={{ marginBottom: 4, fontWeight: 600, fontSize: 13 }}>
                  #{idx + 1}
                  {chunk.heading && <Tag style={{ marginLeft: 8 }}>{chunk.heading}</Tag>}
                </div>
                <div style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{chunk.content}</div>
              </div>
            </List.Item>
          )}
        />
      </Drawer>
    </div>
  );
}
