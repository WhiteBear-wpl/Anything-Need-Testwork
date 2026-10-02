import { Form, Input, Modal, Select, Space } from 'antd';
import { useEffect } from 'react';
import { CASE_TYPE_OPTIONS, PRIORITY_OPTIONS, stepsToText } from '../utils/caseText';

export default function TestCaseEditModal({
  open,
  testcase,
  saving,
  onCancel,
  onSave,
}) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open || !testcase) return;
    form.setFieldsValue({
      title: testcase.title,
      priority: testcase.priority,
      case_type: testcase.case_type,
      precondition: testcase.precondition,
      steps_text: stepsToText(testcase.steps),
      expected_result: testcase.expected_result,
      module: testcase.module || '',
      feature: testcase.feature || '',
    });
  }, [open, testcase, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    await onSave(values);
  };

  return (
    <Modal
      title="编辑测试用例"
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      width={640}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="title" label="用例标题" rules={[{ required: true, message: '请输入用例标题' }]}>
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
        <Space style={{ width: '100%' }} size="large">
          <Form.Item name="module" label="模块" style={{ flex: 1 }}>
            <Input placeholder="例如：用户登录" />
          </Form.Item>
          <Form.Item name="feature" label="功能点" style={{ flex: 1 }}>
            <Input placeholder="例如：账号密码登录" />
          </Form.Item>
        </Space>
        <Form.Item name="precondition" label="前置条件">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item
          name="steps_text"
          label="操作步骤"
          extra="每行一个步骤"
          rules={[{ required: true, message: '请输入操作步骤' }]}
        >
          <Input.TextArea rows={5} placeholder={'打开登录页\n输入账号密码\n点击登录'} />
        </Form.Item>
        <Form.Item name="expected_result" label="预期结果" rules={[{ required: true, message: '请输入预期结果' }]}>
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
