import { InboxOutlined } from '@ant-design/icons';
import { Button, Card, Form, Input, Tabs, Upload } from 'antd';

export default function StepImport({
  form,
  importMode,
  setImportMode,
  selectedFile,
  setSelectedFile,
  flImportFile,
  setFlImportFile,
  loading,
  flImporting,
  onUpload,
  onImportFeatureList,
  onFileSelect,
  message,
}) {
  return (
    <Card className="surface-card" title="导入需求文档">
      <Tabs
        activeKey={importMode}
        onChange={(key) => { setImportMode(key); setSelectedFile(null); setFlImportFile(null); }}
        items={[
          { key: 'text', label: '粘贴文本' },
          { key: 'file', label: '上传文件' },
          { key: 'featurelist', label: '导入功能清单' },
        ]}
        style={{ marginBottom: 16 }}
      />
      {importMode === 'featurelist' ? (
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="清单标题">
            <Input placeholder="例如：用户登录模块 功能清单（留空则用文件名）" size="large" />
          </Form.Item>
          <Form.Item label="FeatureList 文件" required>
            <Upload.Dragger
              accept=".md,.markdown,.xlsx"
              maxCount={1}
              beforeUpload={(file) => {
                const ok = /\.(md|markdown|xlsx)$/i.test(file.name);
                if (!ok) {
                  message.error('仅支持 .xlsx / .md 格式');
                  return Upload.LIST_IGNORE;
                }
                setFlImportFile(file);
                return false;
              }}
              onRemove={() => setFlImportFile(null)}
              fileList={flImportFile ? [{ uid: '-1', name: flImportFile.name, status: 'done' }] : []}
              className="requirement-upload"
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽 FeatureList（.xlsx / .md）到此处</p>
              <p className="ant-upload-hint">列：模块 / 功能点 / 优先级 / 功能描述 / 验收标准 / 约束边界（可用「导出清单」得到模板）</p>
            </Upload.Dragger>
          </Form.Item>
          <Button type="primary" size="large" loading={flImporting} onClick={onImportFeatureList}>
            导入并进入确认
          </Button>
        </Form>
      ) : (
        <>
          <Form form={form} layout="vertical">
            <Form.Item name="title" label="需求标题" rules={[{ required: true, message: '请输入需求标题' }]}>
              <Input placeholder="例如：用户登录模块 PRD" size="large" />
            </Form.Item>
            {importMode === 'text' ? (
              <Form.Item name="content" label="需求内容" rules={[{ required: true, message: '请输入需求内容' }]}>
                <Input.TextArea rows={14} placeholder="粘贴 PRD 内容..." style={{ lineHeight: 1.7 }} />
              </Form.Item>
            ) : (
              <Form.Item label="需求文件" required>
                <Upload.Dragger
                  accept=".docx,.md,.markdown"
                  maxCount={1}
                  beforeUpload={onFileSelect}
                  onRemove={() => setSelectedFile(null)}
                  fileList={selectedFile ? [{ uid: '-1', name: selectedFile.name, status: 'done' }] : []}
                  className="requirement-upload"
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
                  <p className="ant-upload-hint">支持 Word（.docx）和 Markdown（.md）</p>
                </Upload.Dragger>
              </Form.Item>
            )}
          </Form>
          <Button type="primary" size="large" loading={loading} onClick={onUpload}>解析功能点</Button>
        </>
      )}
    </Card>
  );
}
