import { useState } from 'react';
import { ApartmentOutlined, ReloadOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { App, Button, Card, Collapse, Dropdown, Input, Modal, Progress, Radio, Segmented, Space, Table, Tag, Typography } from 'antd';
import TestCaseMindmap from '../../components/TestCaseMindmap';
import {
  QUALITY_COLOR, QUALITY_LABEL, REJECT_REASONS, REVIEW_COLOR, REVIEW_LABEL, SKILL_LABEL, TYPE_LABEL,
} from './constants';
import { CaseDetail, judgeScoreCell, priorityTag } from './DetailPanels';
import FlowActionBar from './FlowActionBar';

const { Text } = Typography;

export default function StepReview({
  task,
  draftSuiteFilter,
  setDraftSuiteFilter,
  draftExporting,
  selectedDrafts,
  setSelectedDrafts,
  pendingDraftCount,
  onExportDrafts,
  onEditDraft,
  onSelectAllDrafts,
  onAdopt,
  onReject,
  onMarkConfirm,
  onReviewDraft,
  onResume,
  resumeLoading,
  onFinish,
  onBack,
}) {
  const { message } = App.useApp();
  const [viewMode, setViewMode] = useState('list');
  const generationComplete = ['completed', 'completed_with_warnings'].includes(task.status);
  // 非空表示驳回弹窗针对脑图里的单条草稿，而不是列表批量选中
  const [rejectTargetId, setRejectTargetId] = useState(null);
  const selectedPendingCount = selectedDrafts.filter(id => {
    const d = task.drafts?.find(x => x.id === id);
    return d && !['adopted', 'rejected'].includes(d.review_status);
  }).length;
  const reviewedCount = (task.drafts || []).filter(d => ['adopted', 'rejected'].includes(d.review_status)).length;

  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState(REJECT_REASONS[0]);
  const [rejectCustom, setRejectCustom] = useState('');

  const confirmReject = () => {
    const reason = rejectReason === '其他' ? (rejectCustom.trim() || '其他') : rejectReason;
    setRejectModalOpen(false);
    setRejectCustom('');
    if (rejectTargetId != null) {
      onReviewDraft(rejectTargetId, 'reject', reason);
      setRejectTargetId(null);
    } else {
      onReject(reason);
    }
  };
  const draftColumns = [
    { title: '用例标题', dataIndex: 'title', ellipsis: true, className: 'key-text-cell' },
    {
      title: '用例集',
      dataIndex: 'is_smoke',
      width: 80,
      render: v => (v ? <Tag color="green">冒烟</Tag> : <Tag>完整</Tag>),
    },
    { title: '类型', dataIndex: 'case_type', width: 80, render: v => <Tag>{TYPE_LABEL[v] || v}</Tag> },
    { title: '来源 Skill', dataIndex: 'skill_name', width: 110, ellipsis: true, render: v => <Tag>{SKILL_LABEL[v] || v || '—'}</Tag> },
    { title: '优先级', dataIndex: 'priority', width: 80, render: priorityTag },
    { title: '质量', dataIndex: 'quality_status', width: 90, render: v => <Tag color={QUALITY_COLOR[v]}>{QUALITY_LABEL[v] || v}</Tag> },
    { title: 'AI 评分', dataIndex: 'judge_score', width: 100, render: judgeScoreCell },
    { title: '状态', dataIndex: 'review_status', width: 90, render: v => <Tag color={REVIEW_COLOR[v]}>{REVIEW_LABEL[v] || v}</Tag> },
    {
      title: '操作',
      width: 80,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => onEditDraft(record)} disabled={record.review_status === 'adopted'}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <>
    <Card className="surface-card" title="生成结果与评审">
      {task.status === 'generating' && (
        <div style={{ marginBottom: 20 }}>
          <Progress percent={task.progress} status="active" strokeColor="#0F766E" />
          <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
            {task.stage || 'AI 正在按功能点生成用例...'}
          </Text>
        </div>
      )}
      {task.status === 'failed' && (
        <div style={{ marginBottom: 16, padding: 12, background: '#fef2f2', borderRadius: 8, color: '#dc2626' }}>
          <Space>
            <span>{task.error_message}</span>
            <Button size="small" icon={<ReloadOutlined />} loading={resumeLoading} onClick={onResume}>
              从检查点继续
            </Button>
          </Space>
        </div>
      )}
      {task.status === 'completed_with_warnings' && (
        <div style={{ marginBottom: 16, padding: 12, background: '#fff7ed', borderRadius: 8, color: '#c2410c' }}>
          本次生成已完成，但有 {task.failure_candidates?.length || 0} 个功能点未生成可用用例，已进入失败评测候选集。
        </div>
      )}

      {task.quality_report && (
        <div className="quality-stats-line">
          <span>总计 <b>{task.quality_report.total_cases}</b></span>
          <span style={{ color: '#16a34a' }}>通过 <b>{task.quality_report.pass_count}</b></span>
          <span style={{ color: '#ea580c' }}>警告 <b>{task.quality_report.warning_count}</b></span>
          <span style={{ color: '#dc2626' }}>不合格 <b>{task.quality_report.fail_count}</b></span>
          <span style={{ color: '#0F766E' }}>覆盖率 <b>{task.quality_report.coverage_rate}%</b></span>
          {task.quality_report.avg_judge_score != null && (
            <span style={{ color: '#22A3A6' }}>AI 均分 <b>{task.quality_report.avg_judge_score}</b></span>
          )}
          {task.quality_report.hallucination_count > 0 && (
            <span style={{ color: '#dc2626' }}>疑似幻觉 <b>{task.quality_report.hallucination_count}</b></span>
          )}
        </div>
      )}

      {(() => {
        let refs = null;
        try {
          refs = task.knowledge_refs ? JSON.parse(task.knowledge_refs) : null;
        } catch { refs = null; }
        const entries = refs ? Object.values(refs).flat() : [];
        const unique = [...new Map(entries.map(r => [`${r.title}|${r.heading}`, r])).values()];
        const panels = [];
        if (task.quality_report?.suggestions) {
          panels.push({
            key: 'suggestions',
            label: 'AI 评测建议',
            children: (
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.7, color: '#475569' }}>
                {task.quality_report.suggestions}
              </div>
            ),
          });
        }
        if (unique.length) {
          panels.push({
            key: 'refs',
            label: `本次生成引用的知识库内容（${unique.length}）`,
            children: (
              <Space wrap>
                {unique.map((r, i) => (
                  <Tag key={i} color="geekblue">
                    《{r.title}》{r.heading ? ` · ${r.heading}` : ''}
                  </Tag>
                ))}
              </Space>
            ),
          });
        }
        if (!panels.length) return null;
        return <Collapse ghost size="small" className="review-extra-collapse" items={panels} />;
      })()}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 12 }}>
        <Space size={12} wrap>
          <Segmented
            value={draftSuiteFilter}
            onChange={setDraftSuiteFilter}
            options={[
              { label: `全部 (${task.drafts?.length || 0})`, value: 'all' },
              { label: `冒烟 (${(task.drafts || []).filter(d => d.is_smoke).length})`, value: 'smoke' },
            ]}
          />
          <Segmented
            value={viewMode}
            onChange={setViewMode}
            options={[
              { label: '列表', value: 'list', icon: <UnorderedListOutlined /> },
              { label: '脑图', value: 'mindmap', icon: <ApartmentOutlined /> },
            ]}
          />
        </Space>
        <Dropdown
          menu={{
            items: [
              { key: 'xlsx', label: '导出用例（.xlsx）' },
              { key: 'md', label: '导出用例（.md）' },
            ],
            onClick: ({ key }) => onExportDrafts(key),
          }}
          disabled={!task.drafts?.length}
        >
          <Button loading={draftExporting} disabled={!task.drafts?.length}>
            导出用例{draftSuiteFilter === 'smoke' ? '（仅冒烟）' : ''}
          </Button>
        </Dropdown>
      </div>
      {viewMode === 'list' ? (
        <Table
          rowKey="id"
          dataSource={(task.drafts || []).filter(d => draftSuiteFilter === 'all' || d.is_smoke)}
          columns={draftColumns}
          rowSelection={{
            selectedRowKeys: selectedDrafts,
            onChange: setSelectedDrafts,
            getCheckboxProps: (record) => ({
              disabled: !generationComplete || record.review_status === 'adopted' || record.review_status === 'rejected',
            }),
          }}
          expandable={{ expandedRowRender: (r) => <CaseDetail record={r} /> }}
        />
      ) : (
        <TestCaseMindmap
          cases={(task.drafts || []).filter(d => draftSuiteFilter === 'all' || d.is_smoke)}
          rootLabel="本次生成用例"
          reviewMode
          showFullMapButton
          onEditCase={(draft) => {
            if (!generationComplete) {
              message.warning('生成完成后才能评审用例');
              return;
            }
            if (draft.review_status === 'adopted') {
              message.warning('已采纳的用例请到用例库中编辑');
              return;
            }
            onEditDraft(draft);
          }}
          onReviewCase={(draft, action) => {
            if (!generationComplete) {
              message.warning('生成完成后才能评审用例');
              return;
            }
            if (action === 'reject') {
              setRejectTargetId(draft.id);
              setRejectModalOpen(true);
              return;
            }
            onReviewDraft(draft.id, action);
          }}
        />
      )}
    </Card>
    <FlowActionBar
      meta={(
        <span>
          待处理 <strong>{pendingDraftCount}</strong> 条 ·
          已选 <strong>{selectedPendingCount}</strong> 条
        </span>
      )}
    >
      <Button onClick={onBack}>上一步</Button>
      <Button onClick={onSelectAllDrafts} disabled={!generationComplete || !pendingDraftCount}>
        一键全选
      </Button>
      <Button disabled={!generationComplete || !selectedPendingCount} onClick={onMarkConfirm}>
        待确认 ({selectedPendingCount})
      </Button>
      <Button danger disabled={!generationComplete || !selectedPendingCount} onClick={() => setRejectModalOpen(true)}>
        驳回 ({selectedPendingCount})
      </Button>
      <Button type="primary" disabled={!generationComplete || !selectedPendingCount} onClick={onAdopt}>
        采纳选中 ({selectedPendingCount})
      </Button>
      {reviewedCount > 0 && (
        <Button onClick={onFinish}>
          完成评审{pendingDraftCount > 0 ? `（跳过剩余 ${pendingDraftCount} 条）` : ''}
        </Button>
      )}
    </FlowActionBar>

      <Modal
        title={rejectTargetId != null ? '驳回该用例' : `驳回 ${selectedPendingCount} 条用例`}
        open={rejectModalOpen}
        onOk={confirmReject}
        onCancel={() => { setRejectModalOpen(false); setRejectTargetId(null); }}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        width={440}
      >
        <Radio.Group
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
        >
          {REJECT_REASONS.map((r) => <Radio key={r} value={r}>{r}</Radio>)}
        </Radio.Group>
        {rejectReason === '其他' && (
          <Input.TextArea
            rows={2}
            style={{ marginTop: 12 }}
            placeholder="补充说明（可选）"
            value={rejectCustom}
            onChange={(e) => setRejectCustom(e.target.value)}
            maxLength={100}
          />
        )}
      </Modal>
    </>
  );
}
