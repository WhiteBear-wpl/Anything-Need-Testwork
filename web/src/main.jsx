import React from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './styles/global.css';

const theme = {
  token: {
    colorPrimary: '#0F766E',
    colorInfo: '#0F766E',
    colorSuccess: '#16A34A',
    colorWarning: '#D97706',
    colorError: '#DC2626',
    borderRadius: 8,
    fontFamily: "'Plus Jakarta Sans', 'JetBrains Mono', -apple-system, BlinkMacSystemFont, 'PingFang SC', 'HarmonyOS Sans SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Segoe UI', sans-serif",
  },
  components: {
    Button: {
      primaryShadow: '0 2px 6px rgba(15, 118, 110, 0.22)',
    },
    Card: {
      paddingLG: 20,
    },
    Table: {
      headerBg: '#F6F8FA',
    },
  },
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
