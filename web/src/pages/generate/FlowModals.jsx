import { Divider, Form, Input, Modal, Select, Space } from 'antd';
import { CASE_TYPE_OPTIONS, PRIORITY_OPTIONS, SKILL_LABEL, STRATEGY_LABEL } from './constants';

export function GenerateConfirmModal({
  open,
  loading,
  strategies,
  selectedPreset,
  specialistSkills,
  specialistOptions,
  estimate,
  moduleGroups,
  onOk,
  onCancel,
}) {
  return (
    <Modal
      title="确认生成配置"
      open={open}
      onOk={onOk}
      onCancel={onCancel}
      okText="开始生成"
      cancelText="返回修改"
      confirmLoading={loading}
      width={520}
    >
      <div className="confirm-generate-body">
        <p>即将按以下配置生成测试用例，确认后开始调用 AI：</p>
        <div className="confirm-generate-row">
          <span>用例策略</span>
          <strong>{strategies.find(s => s.key === selectedPreset)?.title || STRATEGY_LABEL[selectedPreset] || selectedPreset}</strong>
        </div>
        <div className="confirm-generate-row">
          <span>专项 Skill</span>
          <strong>
            {specialistSkills.length
              ? specialistSkills.map(k => specialistOptions.find(s => s.key === k)?.label || SKILL_LABEL[k] || k).filter(Boolean).join('、')
              : '无'}
          </strong>
        </div>
        <div className="confirm-generate-row">
          <span>功能点</span>
          <strong>{estimate.featureCount} 个</strong>
        </div>
        <div className="confirm-generate-row">
          <span>Skill 调用</span>
          <strong>{estimate.skillCalls} 次</strong>
        </div>
        <div className="confirm-generate-row">
          <span>预估用例</span>
          <strong>{estimate.minCases}～{estimate.maxCases} 条</strong>
        </div>
        <Divider style={{ margin: '12px 0' }} />
        <div className="confirm-module-list">
          {Object.entries(moduleGroups).map(([mod, items]) => (
            <div key={mod} className="confirm-module-item">
              <span>{mod}</span>
              <span>{items.length} 个功能点</span>
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

export function ItemEditModal({ open, form, editingItem, loading, onOk, onCancel }) {
  return (
    <Modal
      title={editingItem ? '编辑功能点' : '新增功能点'}
      open={open}
      onOk={onOk}
      onCancel={onCancel}
      confirmLoading={loading}
      okText="保存"
      cancelText="取消"
      width={560}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="module" label="模块"><Input placeholder="例如：用户登录" /></Form.Item>
        <Form.Item name="feature" label="功能点" rules={[{ required: true, message: '请输入功能点名称' }]}>
          <Input placeholder="例如：账号密码登录" />
        </Form.Item>
        <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
          <Select options={PRIORITY_OPTIONS} />
        </Form.Item>
        <Form.Item name="description" label="功能描述"><Input.TextArea rows={3} /></Form.Item>
        <Form.Item name="acceptance_criteria" label="验收标准"><Input.TextArea rows={3} placeholder="多条标准可换行分隔" /></Form.Item>
        <Form.Item name="constraints" label="约束/边界"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  );
}

export function DraftEditModal({ open, form, loading, onOk, onCancel }) {
  return (
    <Modal
      title="编辑测试用例"
      open={open}
      onOk={onOk}
      onCancel={onCancel}
      confirmLoading={loading}
      okText="保存"
      cancelText="取消"
      width={640}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="title" label="用例标题" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Space style={{ width: '100%' }} size="large">
          <Form.Item name="priority" label="优先级" rules={[{ required: true }]} style={{ width: 120 }}>
            <Select options={PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="case_type" label="类型" rules={[{ required: true }]} style={{ width: 140 }}>
            <Select options={CASE_TYPE_OPTIONS} />
          </Form.Item>
        </Space>
        <Form.Item name="precondition" label="前置条件"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="steps_text" label="操作步骤" extra="每行一个步骤" rules={[{ required: true }]}>
          <Input.TextArea rows={5} placeholder={'打开登录页\n输入账号密码\n点击登录'} />
        </Form.Item>
        <Form.Item name="expected_result" label="预期结果" rules={[{ required: true }]}>
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
