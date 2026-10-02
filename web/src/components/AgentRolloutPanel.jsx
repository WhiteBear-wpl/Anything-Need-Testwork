import { useEffect, useState } from 'react';
import {
  Alert, App, Button, Card, Col, InputNumber, Progress, Row, Select, Space, Spin, Switch, Tag, Typography,
} from 'antd';
import {
  getCollaborationReport, getProjectSkillPolicies, updateProject,
  updateProjectSkillPolicies,
} from '../services/api';
import { buildPolicyRows, toSparsePolicyWrite, updatePolicyRow } from '../pages/generate/constants';

const { Text } = Typography;

const GATE_LABELS = {
  sample_complete: '已结束 30 个生成任务',
  events_present: '运行事件完整',
  system_failure_rate_ok: '系统失败率低于 2%',
  specialist_adoption_observed: '已观察到 Specialist 参与采纳',
};

function Metric({ label, value, note }) {
  return (
    <div style={{ minWidth: 130 }}>
      <Text type="secondary">{label}</Text>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>{value}</div>
      {note && <Text type="secondary" style={{ fontSize: 12 }}>{note}</Text>}
    </div>
  );
}

export default function AgentRolloutPanel({ project, onProjectChange }) {
  const { message } = App.useApp();
  const [enabled, setEnabled] = useState(Boolean(project.agent_runtime_v2_enabled));
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [catalogError, setCatalogError] = useState('');
  const [policyState, setPolicyState] = useState(null);
  const [policyRows, setPolicyRows] = useState([]);

  const loadReport = async () => {
    setLoading(true);
    setLoadError('');
    try {
      setReport(await getCollaborationReport(project.id, 30));
    } catch (error) {
      setLoadError(error?.response?.data?.detail || '加载 Agent 试运行报告失败');
    } finally {
      setLoading(false);
    }
  };

  const loadPolicy = async () => {
    setCatalogError('');
    const state = await getProjectSkillPolicies(project.id);
    setPolicyState(state);
    setPolicyRows(buildPolicyRows(state));
  };

  useEffect(() => {
    setEnabled(Boolean(project.agent_runtime_v2_enabled));
  }, [project.id, project.agent_runtime_v2_enabled]);

  useEffect(() => {
    loadReport();
    loadPolicy().catch(error => setCatalogError(error?.response?.data?.detail || '加载项目 Skill 策略失败'));
  }, [project.id]);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await updateProject(project.id, {
        agent_runtime_v2_enabled: enabled,
      });
      const nextPolicy = await updateProjectSkillPolicies(
        project.id,
        toSparsePolicyWrite(policyRows, policyState?.revision_no || 0),
      );
      setPolicyState(nextPolicy);
      setPolicyRows(buildPolicyRows(nextPolicy));
      onProjectChange(updated);
      message.success('Agent 灰度配置已保存');
      await loadReport();
    } catch (error) {
      message.error(error?.response?.data?.detail || '保存 Agent 灰度配置失败');
    } finally {
      setSaving(false);
    }
  };

  const sampleSize = report?.sample_size || 0;
  const updateRow = (skillName, patch) => setPolicyRows(rows => updatePolicyRow(rows, skillName, patch));
  return (
    <Card
      className="surface-card overview-card"
      title="Agent 灰度与效果"
      extra={<Button type="primary" loading={saving} onClick={save}>保存灰度配置</Button>}
      style={{ marginBottom: 16 }}
    >
      <Row gutter={[24, 20]}>
        <Col xs={24} xl={9}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Space>
              <Switch checked={enabled} onChange={setEnabled} />
              <Text strong>项目启用 Runtime V2</Text>
            </Space>
            <div>
              <div style={{ marginBottom: 8 }}><Text strong>允许参与的 Specialist</Text></div>
              <Text type="secondary">策略独立于 Runtime V2 开关；保存后只影响新创建的生成任务。</Text>
              <Space direction="vertical" size={10} style={{ width: '100%', marginTop: 12 }}>
                {policyRows.map(row => {
                  const override = row.override || {};
                  const value = (field, defaultKey) => override[field] ?? row.defaults[defaultKey];
                  const isEnabled = override.enabled ?? false;
                  const source = (field) => override[field] != null ? '项目' : 'Manifest';
                  return (
                    <Card key={row.key} size="small" style={{ background: '#fafafa' }}>
                      <Space direction="vertical" size={8} style={{ width: '100%' }}>
                        <Space wrap>
                          <Switch checked={isEnabled} onChange={(checked) => updateRow(row.key, { enabled: checked })} />
                          <Text strong>{row.key}</Text>
                          <Tag color={isEnabled ? 'success' : 'default'}>{isEnabled ? '启用' : '禁用'}</Tag>
                          <Tag>{`执行顺序：${source('execution_order')}`}</Tag>
                          <Button
                            size="small"
                            onClick={() => updateRow(row.key, {
                              timeout_seconds: null, max_cases: null,
                              execution_order: null, prompt_version: null,
                            })}
                          >
                            使用 Manifest 默认值
                          </Button>
                        </Space>
                        <Space wrap>
                          <label>超时（秒）<InputNumber min={30} max={row.defaults.timeoutSeconds} value={value('timeout_seconds', 'timeoutSeconds')} onChange={(timeout_seconds) => updateRow(row.key, { timeout_seconds })} /></label>
                          <label>最大用例数<InputNumber min={1} max={row.defaults.maxCases} value={value('max_cases', 'maxCases')} onChange={(max_cases) => updateRow(row.key, { max_cases })} /></label>
                          <label>执行顺序<InputNumber min={0} max={10000} value={value('execution_order', 'executionOrder')} onChange={(execution_order) => updateRow(row.key, { execution_order })} /></label>
                          <label>提示词版本<Select style={{ minWidth: 90 }} value={value('prompt_version', 'promptVersion')} options={row.defaults.promptVersions.map(version => ({ label: version, value: version }))} onChange={(prompt_version) => updateRow(row.key, { prompt_version })} /></label>
                        </Space>
                      </Space>
                    </Card>
                  );
                })}
              </Space>
            </div>
            {catalogError && (
              <Alert
                type="warning"
                showIcon
                message={catalogError}
                description="已保留当前 Specialist 配置；Catalog 恢复前不可修改该列表。"
                action={<Button size="small" onClick={() => loadPolicy().catch(error => setCatalogError(error?.response?.data?.detail || '加载项目 Skill 策略失败'))}>重试</Button>}
              />
            )}
            <Alert
              type="info"
              showIcon
              message="建议按 Specialist 顺序逐个开放并观察。全局 Runtime V2 开关仍需在环境配置中启用。"
            />
          </Space>
        </Col>
        <Col xs={24} xl={15}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
          ) : loadError ? (
            <Alert type="warning" showIcon message={loadError} action={<Button size="small" onClick={loadReport}>重试</Button>} />
          ) : report && (
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <div>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Text strong>最近 30 个已结束生成任务</Text>
                  <Text type="secondary">{sampleSize} / {report.target_sample_size}</Text>
                </Space>
                <Progress percent={Math.min(100, Math.round(sampleSize / report.target_sample_size * 100))} showInfo={false} />
              </div>
              <Space size={28} wrap>
                <Metric label="系统失败率" value={`${report.system_failure_rate}%`} note={`${report.failed_runs} 次失败`} />
                <Metric label="平均运行时长" value={report.average_duration_ms == null ? '—' : `${(report.average_duration_ms / 1000).toFixed(1)}s`} note="暂无历史可靠基线" />
                <Metric label="Agent Warning" value={report.agent_warning_count} />
                <Metric label="候选去向" value={`${report.selected_count} / ${report.merged_duplicate_count}`} note="选中 / 合并重复" />
                <Metric label="Specialist 参与采纳" value={report.specialist_influenced_adopted_count} note="相关归因，非因果提升" />
              </Space>
              <Space wrap>
                {Object.entries(report.gates || {}).map(([key, passed]) => (
                  <Tag key={key} color={passed ? 'success' : 'default'}>
                    {passed ? '通过' : '待满足'} · {GATE_LABELS[key] || key}
                  </Tag>
                ))}
              </Space>
            </Space>
          )}
        </Col>
      </Row>
    </Card>
  );
}
