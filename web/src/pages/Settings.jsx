import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  ExperimentOutlined,
  InfoCircleOutlined,
  NodeIndexOutlined,
  OrderedListOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useEffect, useState } from 'react';
import {
  App, Button, Card, Form, Input, Select, Space, Switch, Tabs, Tag, Tooltip,
} from 'antd';
import PageHeader from '../components/PageHeader';
import { getSettings, testModelConnection, updateSettings } from '../services/api';

const PRESETS = [
  {
    label: 'DeepSeek',
    llm_base_url: 'https://api.deepseek.com/v1',
    llm_model: 'deepseek-chat',
  },
  {
    label: '智谱 GLM',
    llm_base_url: 'https://open.bigmodel.cn/api/paas/v4',
    llm_model: 'glm-4-plus',
  },
  {
    label: '通义千问',
    llm_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    llm_model: 'qwen-plus',
  },
  {
    label: '月之暗面 Kimi',
    llm_base_url: 'https://api.moonshot.cn/v1',
    llm_model: 'kimi-latest',
  },
  {
    label: '豆包（火山方舟）',
    llm_base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    llm_model: 'doubao-1-5-pro-32k-250115',
  },
  {
    label: '腾讯混元',
    llm_base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
    llm_model: 'hunyuan-turbos-latest',
  },
  {
    label: '百度千帆',
    llm_base_url: 'https://qianfan.baidubce.com/v2',
    llm_model: 'ernie-4.0-turbo-8k',
  },
  {
    label: '讯飞星火',
    llm_base_url: 'https://spark-api-open.xf-yun.com/v1',
    llm_model: 'generalv3.5',
  },
  {
    label: 'MiniMax',
    llm_base_url: 'https://api.minimax.chat/v1',
    llm_model: 'MiniMax-Text-01',
  },
  {
    label: '阶跃星辰',
    llm_base_url: 'https://api.stepfun.com/v1',
    llm_model: 'step-2-16k',
  },
  {
    label: '零一万物',
    llm_base_url: 'https://api.lingyiwanwu.com/v1',
    llm_model: 'yi-lightning',
  },
  {
    label: '百川智能',
    llm_base_url: 'https://api.baichuan-ai.com/v1',
    llm_model: 'Baichuan4-Turbo',
  },
  {
    label: '硅基流动 SiliconFlow',
    llm_base_url: 'https://api.siliconflow.cn/v1',
    llm_model: 'deepseek-ai/DeepSeek-V3',
  },
  {
    label: 'OpenRouter',
    llm_base_url: 'https://openrouter.ai/api/v1',
    llm_model: 'deepseek/deepseek-chat-v3-0324',
  },
  {
    label: 'OpenAI',
    llm_base_url: 'https://api.openai.com/v1',
    llm_model: 'gpt-4o-mini',
  },
  {
    label: 'Anthropic Claude',
    llm_base_url: 'https://api.anthropic.com/v1',
    llm_model: 'claude-sonnet-4-5',
  },
  {
    label: 'Google Gemini',
    llm_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
    llm_model: 'gemini-2.5-flash',
  },
  {
    label: 'xAI Grok',
    llm_base_url: 'https://api.x.ai/v1',
    llm_model: 'grok-4',
  },
  {
    label: 'Groq',
    llm_base_url: 'https://api.groq.com/openai/v1',
    llm_model: 'llama-3.3-70b-versatile',
  },
  {
    label: 'Mistral',
    llm_base_url: 'https://api.mistral.ai/v1',
    llm_model: 'mistral-large-latest',
  },
];

const EMBEDDING_PRESETS = [
  {
    label: '智谱 GLM',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'embedding-3',
  },
  {
    label: '通义千问',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'text-embedding-v3',
  },
  {
    label: '硅基流动 SiliconFlow',
    base_url: 'https://api.siliconflow.cn/v1',
    model: 'BAAI/bge-m3',
  },
  {
    label: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    model: 'text-embedding-3-small',
  },
  {
    label: 'Jina AI',
    base_url: 'https://api.jina.ai/v1',
    model: 'jina-embeddings-v3',
  },
  {
    label: 'Mistral',
    base_url: 'https://api.mistral.ai/v1',
    model: 'mistral-embed',
  },
];

const RERANK_PRESETS = [
  {
    label: '硅基流动 SiliconFlow',
    base_url: 'https://api.siliconflow.cn/v1',
    model: 'BAAI/bge-reranker-v2-m3',
  },
  {
    label: 'Jina AI',
    base_url: 'https://api.jina.ai/v1',
    model: 'jina-reranker-v3',
  },
];

// 各页签保存时提交的字段，避免误提交其他页签内容
const TAB_FIELDS = {
  generation: ['llm_base_url', 'llm_model', 'llm_api_key', 'llm_mock_mode'],
  eval: ['eval_llm_base_url', 'eval_llm_model', 'eval_llm_api_key'],
  embedding: ['embedding_base_url', 'embedding_model', 'embedding_api_key'],
  rerank: ['rerank_base_url', 'rerank_model', 'rerank_api_key'],
};

function ConnectionStatus({ result }) {
  if (!result) return null;
  if (result.ok) {
    return <Tag icon={<CheckCircleOutlined />} color="success">{result.message || '连接成功'}</Tag>;
  }
  return <Tag icon={<CloseCircleOutlined />} color="error">{result.message || '连接失败'}</Tag>;
}

export default function Settings() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState('');
  const [status, setStatus] = useState({ use_mock_llm: true, llm_api_key_set: false, llm_api_key_masked: '' });
  const [testResults, setTestResults] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const data = await getSettings();
      setStatus(data);
      form.setFieldsValue({
        llm_base_url: data.llm_base_url,
        llm_model: data.llm_model,
        llm_mock_mode: data.llm_mock_mode,
        llm_api_key: '',
        eval_llm_base_url: data.eval_llm_base_url,
        eval_llm_model: data.eval_llm_model,
        eval_llm_api_key: '',
        embedding_base_url: data.embedding_base_url,
        embedding_model: data.embedding_model,
        embedding_api_key: '',
        rerank_base_url: data.rerank_base_url,
        rerank_model: data.rerank_model,
        rerank_api_key: '',
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // 根据当前 API 地址反查匹配的服务商预设，用于下拉框回显
  const llmBaseUrl = Form.useWatch('llm_base_url', form);
  const evalBaseUrl = Form.useWatch('eval_llm_base_url', form);
  const embeddingBaseUrl = Form.useWatch('embedding_base_url', form);
  const rerankBaseUrl = Form.useWatch('rerank_base_url', form);
  const matchedPreset = PRESETS.find(p => p.llm_base_url === llmBaseUrl)?.label;
  const matchedEvalPreset = PRESETS.find(p => p.llm_base_url === evalBaseUrl)?.label;
  const matchedEmbeddingPreset = EMBEDDING_PRESETS.find(p => p.base_url === embeddingBaseUrl)?.label;
  const matchedRerankPreset = RERANK_PRESETS.find(p => p.base_url === rerankBaseUrl)?.label;

  const keyPlaceholder = (keySet, keyMasked) => (
    keySet ? `已配置 ${keyMasked}，输入新值可覆盖` : '输入 API Key'
  );

  const applyPresetFields = (label, urlField, modelField, presets = PRESETS) => {
    const preset = presets.find(p => p.label === label);
    if (!preset) return;
    form.setFieldsValue({
      [urlField]: preset.llm_base_url ?? preset.base_url,
      [modelField]: preset.llm_model ?? preset.model,
    });
  };

  const buildPayload = (tab) => {
    const values = form.getFieldsValue(TAB_FIELDS[tab]);
    const payload = {};
    if (tab === 'generation') {
      payload.llm_base_url = values.llm_base_url ?? '';
      payload.llm_model = values.llm_model ?? '';
      payload.llm_mock_mode = !!values.llm_mock_mode;
      if (values.llm_api_key?.trim()) payload.llm_api_key = values.llm_api_key.trim();
    } else if (tab === 'eval') {
      payload.eval_llm_base_url = values.eval_llm_base_url ?? '';
      payload.eval_llm_model = values.eval_llm_model ?? '';
      if (values.eval_llm_api_key?.trim()) payload.eval_llm_api_key = values.eval_llm_api_key.trim();
    } else if (tab === 'embedding') {
      payload.embedding_base_url = values.embedding_base_url ?? '';
      payload.embedding_model = values.embedding_model ?? '';
      if (values.embedding_api_key?.trim()) payload.embedding_api_key = values.embedding_api_key.trim();
    } else {
      payload.rerank_base_url = values.rerank_base_url ?? '';
      payload.rerank_model = values.rerank_model ?? '';
      if (values.rerank_api_key?.trim()) payload.rerank_api_key = values.rerank_api_key.trim();
    }
    return payload;
  };

  const saveTab = async (tab) => {
    if (tab === 'generation') {
      await form.validateFields(['llm_base_url', 'llm_model']);
    }
    setSaving(true);
    try {
      const data = await updateSettings(buildPayload(tab));
      setStatus(data);
      form.setFieldsValue({
        llm_api_key: '',
        eval_llm_api_key: '',
        embedding_api_key: '',
        rerank_api_key: '',
      });
      message.success('配置已保存');
      return true;
    } catch (err) {
      message.error(err.response?.data?.detail || '保存失败');
      return false;
    } finally {
      setSaving(false);
    }
  };

  const saveAndTest = async (tab) => {
    const saved = await saveTab(tab);
    if (!saved) return;
    setTesting(tab);
    try {
      const result = await testModelConnection(tab);
      setTestResults((prev) => ({ ...prev, [tab]: result }));
      if (result.ok) message.success(result.message || '连接成功');
      else message.error(result.message || '连接失败');
    } catch (err) {
      const msg = err.response?.data?.detail || '测试请求失败';
      setTestResults((prev) => ({ ...prev, [tab]: { ok: false, message: msg } }));
      message.error(msg);
    } finally {
      setTesting('');
    }
  };

  const clearConfig = async (tab) => {
    setSaving(true);
    try {
      let payload;
      if (tab === 'generation') payload = { llm_api_key: '' };
      else if (tab === 'eval') payload = { eval_llm_api_key: '', eval_llm_base_url: '', eval_llm_model: '' };
      else if (tab === 'rerank') payload = { rerank_api_key: '', rerank_base_url: '', rerank_model: '' };
      else payload = { embedding_api_key: '' };
      const data = await updateSettings(payload);
      setStatus(data);
      if (tab === 'eval') {
        form.setFieldsValue({ eval_llm_api_key: '', eval_llm_base_url: '', eval_llm_model: '' });
        message.success('评测专用配置已清除，将复用生成模型');
      } else if (tab === 'rerank') {
        form.setFieldsValue({ rerank_api_key: '', rerank_base_url: '', rerank_model: '' });
        message.success('Rerank 配置已清除，知识检索将只做混合检索融合排序');
      } else {
        form.setFieldValue(tab === 'generation' ? 'llm_api_key' : 'embedding_api_key', '');
        message.success('API Key 已清除');
      }
      setTestResults((prev) => ({ ...prev, [tab]: null }));
    } finally {
      setSaving(false);
    }
  };

  const tabActions = (tab, keySet, clearLabel) => (
    <Space style={{ marginTop: 4 }}>
      <Button
        type="primary"
        loading={saving || testing === tab}
        onClick={() => saveAndTest(tab)}
      >
        保存并测试连接
      </Button>
      {keySet && (
        <Button danger loading={saving} onClick={() => clearConfig(tab)}>
          {clearLabel}
        </Button>
      )}
    </Space>
  );

  // 三个页签共用的「预设 + 地址 + 模型 + Key」四个表单项
  const modelFields = ({
    matched, urlField, modelField, keyField, presets = PRESETS,
    urlPlaceholder, modelPlaceholder, keyPlaceholder: keyHint, required = false,
  }) => (
    <>
      <Form.Item label="服务商预设">
        <Select
          placeholder="选择常用服务商，自动填充地址和模型"
          allowClear
          value={matched}
          onChange={(label) => applyPresetFields(label, urlField, modelField, presets)}
          options={presets.map(p => ({ label: p.label, value: p.label }))}
        />
      </Form.Item>
      <Form.Item
        name={urlField}
        label="API 地址"
        rules={required ? [{ required: true, message: '请输入 API 地址' }] : undefined}
      >
        <Input placeholder={urlPlaceholder} />
      </Form.Item>
      <Form.Item
        name={modelField}
        label="模型名称"
        rules={required ? [{ required: true, message: '请输入模型名称' }] : undefined}
      >
        <Input placeholder={modelPlaceholder} />
      </Form.Item>
      <Form.Item name={keyField} label="API Key">
        <Input.Password placeholder={keyHint} autoComplete="off" />
      </Form.Item>
    </>
  );

  const generationTab = (
    <Card className="surface-card" loading={loading}>
      <div className="settings-status-bar">
        <Tooltip
          title={
            status.use_mock_llm
              ? '未配置 API Key 或已开启 Mock 模式，生成结果为本地示例数据，不消耗 token'
              : 'AI 生成将调用下方配置的模型接口'
          }
        >
          <Tag color={status.use_mock_llm ? 'orange' : 'green'}>
            {status.use_mock_llm ? 'Mock 模式' : '真实 LLM'}
          </Tag>
        </Tooltip>
        <ConnectionStatus result={testResults.generation} />
      </div>
      <div>
        {modelFields({
          matched: matchedPreset,
          urlField: 'llm_base_url',
          modelField: 'llm_model',
          keyField: 'llm_api_key',
          urlPlaceholder: 'https://api.deepseek.com/v1',
          modelPlaceholder: 'deepseek-chat',
          keyPlaceholder: keyPlaceholder(status.llm_api_key_set, status.llm_api_key_masked),
          required: true,
        })}

        <Form.Item
          name="llm_mock_mode"
          valuePropName="checked"
          label={(
            <span>
              Mock 模式
              <Tooltip title="开启后即使配置了 Key 也使用本地示例数据，不消耗 token">
                <InfoCircleOutlined className="tab-label-hint" />
              </Tooltip>
            </span>
          )}
        >
          <Switch checkedChildren="开" unCheckedChildren="关" />
        </Form.Item>

        {tabActions('generation', status.llm_api_key_set, '清除 API Key')}
      </div>
    </Card>
  );

  const evalTab = (
    <Card className="surface-card" loading={loading}>
      {testResults.eval && (
        <div className="settings-status-bar">
          <ConnectionStatus result={testResults.eval} />
        </div>
      )}
      <div>
        {modelFields({
          matched: matchedEvalPreset,
          urlField: 'eval_llm_base_url',
          modelField: 'eval_llm_model',
          keyField: 'eval_llm_api_key',
          urlPlaceholder: '三项全部留空时复用生成模型',
          modelPlaceholder: '如 deepseek-reasoner / gpt-4o',
          keyPlaceholder: keyPlaceholder(status.eval_llm_api_key_set, status.eval_llm_api_key_masked),
        })}

        {tabActions('eval', status.eval_llm_api_key_set, '清除评测配置')}
      </div>
    </Card>
  );

  const embeddingTab = (
    <Card className="surface-card" loading={loading}>
      {testResults.embedding && (
        <div className="settings-status-bar">
          <ConnectionStatus result={testResults.embedding} />
        </div>
      )}
      <div>
        {modelFields({
          matched: matchedEmbeddingPreset,
          urlField: 'embedding_base_url',
          modelField: 'embedding_model',
          keyField: 'embedding_api_key',
          presets: EMBEDDING_PRESETS,
          urlPlaceholder: 'https://open.bigmodel.cn/api/paas/v4',
          modelPlaceholder: '如 embedding-3 / BAAI/bge-m3',
          keyPlaceholder: keyPlaceholder(status.embedding_api_key_set, status.embedding_api_key_masked),
        })}

        {tabActions('embedding', status.embedding_api_key_set, '清除 Embedding Key')}
      </div>
    </Card>
  );

  const rerankTab = (
    <Card className="surface-card" loading={loading}>
      {testResults.rerank && (
        <div className="settings-status-bar">
          <ConnectionStatus result={testResults.rerank} />
        </div>
      )}
      <div>
        {modelFields({
          matched: matchedRerankPreset,
          urlField: 'rerank_base_url',
          modelField: 'rerank_model',
          keyField: 'rerank_api_key',
          presets: RERANK_PRESETS,
          urlPlaceholder: '三项全部留空时不启用精排，只做混合检索融合排序',
          modelPlaceholder: '如 BAAI/bge-reranker-v2-m3',
          keyPlaceholder: keyPlaceholder(status.rerank_api_key_set, status.rerank_api_key_masked),
        })}

        {tabActions('rerank', status.rerank_api_key_set, '清除 Rerank 配置')}
      </div>
    </Card>
  );

  return (
    <div className="settings-page">
      <PageHeader
        title="个人模型配置"
        description="为当前账号配置用例生成、AI 评测、知识库检索（Embedding）与检索精排（Rerank）模型接口，配置互相独立、按页签保存"
      />

      <Form form={form} layout="vertical">
        <Tabs
          defaultActiveKey="generation"
          items={[
            {
              key: 'generation',
              label: (
                <span>
                  <ThunderboltOutlined /> 生成模型
                  <Tooltip title="该配置同时用于 AI 用例生成和 AI 小助手；修改后两处都会切换到新的模型配置。">
                    <ExclamationCircleOutlined className="tab-label-hint" />
                  </Tooltip>
                </span>
              ),
              children: generationTab,
            },
            {
              key: 'eval',
              label: (
                <span>
                  <ExperimentOutlined /> 评测模型
                  <Tooltip title="评测模型与生成模型分开，可避免“自己给自己打高分”的偏置。全部留空则复用生成模型配置。">
                    <InfoCircleOutlined className="tab-label-hint" />
                  </Tooltip>
                </span>
              ),
              children: evalTab,
            },
            {
              key: 'embedding',
              label: (
                <span>
                  <NodeIndexOutlined /> Embedding
                  <Tooltip title="知识库向量化和检索使用的模型，走 /embeddings 接口，与 Chat 模型类型不同，需单独配置。不配置则知识库（RAG）功能不可用。">
                    <InfoCircleOutlined className="tab-label-hint" />
                  </Tooltip>
                </span>
              ),
              children: embeddingTab,
            },
            {
              key: 'rerank',
              label: (
                <span>
                  <OrderedListOutlined /> Rerank
                  <Tooltip title="知识库检索精排模型（可选），走 /rerank 接口，对混合检索的候选结果做精细相关性排序。留空则只做 BM25 + 向量的融合排序。">
                    <InfoCircleOutlined className="tab-label-hint" />
                  </Tooltip>
                </span>
              ),
              children: rerankTab,
            },
          ]}
        />
      </Form>
    </div>
  );
}
