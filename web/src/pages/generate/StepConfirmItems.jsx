import { Button, Card, Dropdown, Input, Popconfirm, Space, Table, Tag, Typography } from 'antd';
import { ItemDetail, priorityTag } from './DetailPanels';
import FlowActionBar from './FlowActionBar';

const { Text } = Typography;

export default function StepConfirmItems({
  document,
  selectedItems,
  setSelectedItems,
  scopeForm,
  setScopeForm,
  scopeLoading,
  scopeSaving,
  flExporting,
  loading,
  onGenerateScope,
  onSaveScope,
  onExportFeatureList,
  onAddItem,
  onEditItem,
  onRemoveItem,
  onBack,
  onConfirm,
}) {
  const itemColumns = [
    { title: '模块', dataIndex: 'module', width: 100, ellipsis: true },
    { title: '功能点', dataIndex: 'feature', width: 140, ellipsis: true, className: 'key-text-cell' },
    { title: '优先级', dataIndex: 'priority', width: 72, render: priorityTag },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: v => v || '—' },
    { title: '验收标准', dataIndex: 'acceptance_criteria', ellipsis: true, render: v => v || '—' },
    { title: '约束/边界', dataIndex: 'constraints', width: 140, ellipsis: true, render: v => v || '—' },
    {
      title: '操作',
      width: 110,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => onEditItem(record)}>编辑</Button>
          <Popconfirm title="确定删除此功能点？" onConfirm={() => onRemoveItem(record.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
    <Card
      className="surface-card"
      title="确认功能点"
      extra={
        <Space>
          <Text type="secondary">共 {document.items.length} 个功能点</Text>
          {document.status !== 'confirmed' && (
            <Tag color="orange">待确认</Tag>
          )}
          <Dropdown
            menu={{
              items: [
                { key: 'xlsx', label: '导出 Excel（.xlsx）' },
                { key: 'md', label: '导出 Markdown（.md）' },
              ],
              onClick: ({ key }) => onExportFeatureList(key),
            }}
          >
            <Button size="small" loading={flExporting}>导出清单</Button>
          </Dropdown>
          <Button type="primary" size="small" onClick={onAddItem}>新增功能点</Button>
        </Space>
      }
    >
      <Card size="small" className="scope-card" style={{ marginBottom: 16 }}>
        <div className="scope-card-head">
          <div>
            <span className="scope-card-title">测试边界与风险</span>
            <span className="scope-card-sub">生成时会读取本卡片：「不测范围」跳过、「风险」优先补测（每行一条）</span>
          </div>
          <Space>
            <Button size="small" loading={scopeLoading} onClick={onGenerateScope}>AI 生成</Button>
            <Button size="small" type="primary" loading={scopeSaving} onClick={onSaveScope}>保存</Button>
          </Space>
        </div>
        <div className="scope-card-grid scope-card-grid-two">
          <div className="scope-field">
            <div className="scope-field-label scope-label-out">不测范围</div>
            <Input.TextArea
              rows={4}
              value={scopeForm.out_scope}
              onChange={(e) => setScopeForm((p) => ({ ...p, out_scope: e.target.value }))}
              placeholder={'第三方登录\n性能压测\nUI 走查'}
            />
          </div>
          <div className="scope-field">
            <div className="scope-field-label scope-label-risk">风险 / 待澄清</div>
            <Input.TextArea
              rows={4}
              value={scopeForm.risks}
              onChange={(e) => setScopeForm((p) => ({ ...p, risks: e.target.value }))}
              placeholder={'验证码通道稳定性\n锁定阈值需确认'}
            />
          </div>
        </div>
      </Card>
      <Table
        rowKey="id"
        dataSource={document.items}
        columns={itemColumns}
        rowSelection={{ selectedRowKeys: selectedItems, onChange: setSelectedItems }}
        pagination={false}
        expandable={{ expandedRowRender: (r) => <ItemDetail record={r} /> }}
      />
    </Card>
    <FlowActionBar
      meta={<span>已选 <strong>{selectedItems.length}</strong> / {document.items.length} 个功能点</span>}
    >
      <Button onClick={onBack}>上一步</Button>
      <Button
        type="primary"
        loading={loading}
        disabled={!selectedItems.length}
        onClick={onConfirm}
      >
        确认并继续
      </Button>
    </FlowActionBar>
    </>
  );
}
