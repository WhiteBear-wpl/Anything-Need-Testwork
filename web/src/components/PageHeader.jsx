import { InfoCircleOutlined } from '@ant-design/icons';
import { Tooltip } from 'antd';

export default function PageHeader({ title, description, extra }) {
  return (
    <div className="page-header">
      <div className="page-header-row">
        <div className="page-title-row">
          <h1 className="page-title">{title}</h1>
          {description && (
            <Tooltip title={description} placement="right">
              <InfoCircleOutlined className="page-title-hint" />
            </Tooltip>
          )}
        </div>
        {extra && <div>{extra}</div>}
      </div>
    </div>
  );
}
