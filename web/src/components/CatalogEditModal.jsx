import { Form, Input, Modal } from 'antd';
import { useEffect } from 'react';

export default function CatalogEditModal({
  open,
  target,
  saving,
  onCancel,
  onSave,
}) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open || !target) return;
    form.setFieldsValue({ name: target.type === 'module' ? target.module : target.feature });
  }, [open, target, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    await onSave(values.name.trim());
  };

  return (
    <Modal
      title={target?.type === 'module' ? '重命名模块' : '重命名功能点'}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label={target?.type === 'module' ? '模块名称' : '功能点名称'}
          rules={[{ required: true, message: '请输入名称' }]}
        >
          <Input maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
