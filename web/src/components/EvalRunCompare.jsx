import { Alert, Drawer, Table, Tag, Typography } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import { useMemo } from 'react';

const { Text } = Typography;

const STRATEGY_LABEL = { full: '完整用例', quick: '快速冒烟' };

// better: 'up' 越高越好 / 'down' 越低越好 / 'neutral' 不判优劣
const METRIC_ROWS = [
  { key: 'strategy', label: '生成策略', better: 'neutral' },
  { key: 'sample_count', label: '样本数', better: 'neutral' },
  { key: 'total_cases', label: '生成用例数', better: 'neutral' },
  { key: 'success_rate', label: '生成成功率', pct: true, better: 'up' },
  { key: 'usable_rate', label: '可用率（评分 ≥4）', pct: true, better: 'up' },
  { key: 'recall', label: '场景召回率', pct: true, better: 'up' },
  { key: 'avg_judge_score', label: 'AI 均分', better: 'up' },
  { key: 'duplicate_rate', label: '重复率', pct: true, better: 'down' },
  { key: 'hallucination_count', label: '疑似幻觉数', better: 'down' },
  { key: 'total_tokens', label: 'Token 消耗', better: 'down' },
];

function cellValue(run, key) {
  if (key === 'strategy') return STRATEGY_LABEL[run.config?.strategy] || run.config?.strategy || '—';
  return run.metrics?.[key];
}

function fmt(value, row) {
  if (value === null || value === undefined) return '—';
  if (row.key === 'strategy') return value;
  if (row.pct) return `${value}%`;
  if (row.key === 'total_tokens') return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
  return String(value);
}

function DeltaBadge({ delta, better, pct }) {
  if (delta === null) return null;
  const rounded = Math.round(delta * 10) / 10;
  if (rounded === 0) return <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>持平</Text>;
  const improved = better === 'up' ? rounded > 0 : rounded < 0;
  const color = better === 'neutral' ? '#64748b' : improved ? '#16a34a' : '#dc2626';
  const Icon = rounded > 0 ? ArrowUpOutlined : ArrowDownOutlined;
  return (
    <span style={{ color, fontSize: 12, marginLeft: 6, whiteSpace: 'nowrap' }}>
      <Icon /> {Math.abs(rounded)}{pct ? '%' : ''}
    </span>
  );
}

function sampleIdsOf(run) {
  return (run.results || []).map(r => r.sample_id).sort((a, b) => a - b).join(',');
}

export default function EvalRunCompare({ runs, open, onClose }) {
  // 按时间升序：最早的一列作为基准
  const ordered = useMemo(
    () => [...(runs || [])].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)),
    [runs],
  );
  const baseline = ordered[0];

  const sameSampleSet = useMemo(() => {
    if (ordered.length < 2) return true;
    const base = sampleIdsOf(ordered[0]);
    return ordered.every(r => sampleIdsOf(r) === base);
  }, [ordered]);

  const columns = [
    { title: '指标', dataIndex: 'label', width: 170, fixed: 'left', render: v => <Text strong>{v}</Text> },
    ...ordered.map((run, idx) => ({
      title: (
        <span>
          {run.label}
          {idx === 0 && <Tag style={{ marginLeft: 6 }}>基准</Tag>}
          <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>
            {new Date(run.created_at).toLocaleString()}
          </div>
        </span>
      ),
      key: run.id,
      render: (_, row) => {
        const value = cellValue(run, row.key);
        const baseValue = cellValue(baseline, row.key);
        const numeric = typeof value === 'number' && typeof baseValue === 'number';
        const delta = idx > 0 && sameSampleSet && numeric ? value - baseValue : null;
        return (
          <span>
            {fmt(value, row)}
            {idx > 0 && <DeltaBadge delta={delta} better={row.better} pct={row.pct} />}
          </span>
        );
      },
    })),
  ];

  // 按样本下钻：可用率 / 召回率
  const sampleRows = useMemo(() => {
    const map = new Map();
    ordered.forEach(run => {
      (run.results || []).forEach(r => {
        if (!map.has(r.sample_id)) map.set(r.sample_id, { sample_id: r.sample_id, sample_title: r.sample_title });
        map.get(r.sample_id)[`run_${run.id}`] = r.metrics;
      });
    });
    return [...map.values()];
  }, [ordered]);

  const sampleColumns = [
    { title: '样本', dataIndex: 'sample_title', width: 200, fixed: 'left', ellipsis: true },
    ...ordered.map(run => ({
      title: run.label,
      key: run.id,
      render: (_, row) => {
        const m = row[`run_${run.id}`];
        if (!m) return <Text type="secondary">未参与</Text>;
        return (
          <span style={{ fontSize: 12 }}>
            可用 {m.usable_rate ?? '—'}% · 召回 {m.recall ?? '—'}%
            {m.hallucination_count > 0 && <Tag color="red" style={{ marginLeft: 6 }}>幻觉 {m.hallucination_count}</Tag>}
          </span>
        );
      },
    })),
  ];

  return (
    <Drawer
      title={`运行对比（${ordered.length} 次，以最早的「${baseline?.label || ''}」为基准）`}
      open={open}
      onClose={onClose}
      width={Math.min(420 + ordered.length * 240, 1100)}
    >
      {!sameSampleSet && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="所选运行的样本集不一致，指标不具备严格可比性，结论仅供参考"
        />
      )}
      <Table
        rowKey="key"
        size="small"
        dataSource={METRIC_ROWS}
        columns={columns}
        pagination={false}
        style={{ marginBottom: 24 }}
      />
      <div style={{ fontWeight: 600, marginBottom: 8 }}>按样本对比</div>
      <Table
        rowKey="sample_id"
        size="small"
        dataSource={sampleRows}
        columns={sampleColumns}
        pagination={false}
      />
      <div style={{ marginTop: 12, fontSize: 12, color: '#94a3b8' }}>
        绿色 = 相比基准变好，红色 = 变差（重复率 / 幻觉 / Token 为越低越好）。
      </div>
    </Drawer>
  );
}
