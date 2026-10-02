import { CheckCircleFilled } from '@ant-design/icons';
import { Button, Card, Dropdown, Space } from 'antd';
import { Link } from 'react-router-dom';

export default function StepDone({ task, projectId, exporting, onExport, onNewTask }) {
  const stats = task.review_stats || {};
  const adopted = stats.adopted ?? 0;
  const rejected = stats.rejected ?? 0;
  const total = stats.total ?? (task.drafts?.length || 0);

  return (
    <Card className="surface-card">
      <div style={{ textAlign: 'center', padding: '32px 0 8px' }}>
        <CheckCircleFilled style={{ fontSize: 56, color: adopted > 0 ? '#16a34a' : '#94a3b8' }} />
        <h2 style={{ margin: '16px 0 8px', fontSize: 22 }}>
          {adopted > 0 ? `已采纳 ${adopted} 条用例入库` : '本次评审完成'}
        </h2>
      </div>

      <div className="quality-stats" style={{ maxWidth: 560, margin: '24px auto' }}>
        <div className="quality-stat"><div className="quality-stat-value">{total}</div><div className="quality-stat-label">总生成</div></div>
        <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#16a34a' }}>{adopted}</div><div className="quality-stat-label">已采纳</div></div>
        <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#dc2626' }}>{rejected}</div><div className="quality-stat-label">已驳回</div></div>
        <div className="quality-stat"><div className="quality-stat-value" style={{ color: '#0F766E' }}>{stats.adoption_rate ?? 0}%</div><div className="quality-stat-label">采纳率</div></div>
      </div>

      <div style={{ textAlign: 'center', paddingBottom: 24 }}>
        <Space size="middle" wrap>
          <Link to={`/projects/${projectId}/testcases`}>
            <Button type="primary" size="large">查看测试用例</Button>
          </Link>
          <Dropdown
            menu={{
              items: [
                { key: 'xlsx', label: '导出用例（.xlsx）' },
                { key: 'md', label: '导出用例（.md）' },
              ],
              onClick: ({ key }) => onExport(key),
            }}
            disabled={!task.drafts?.length}
          >
            <Button size="large" loading={exporting} disabled={!task.drafts?.length}>导出用例</Button>
          </Dropdown>
          <Link to={`/projects/${projectId}/generations`}>
            <Button size="large">查看生成记录</Button>
          </Link>
          <Button size="large" onClick={onNewTask}>再生成一批</Button>
        </Space>
      </div>
    </Card>
  );
}
