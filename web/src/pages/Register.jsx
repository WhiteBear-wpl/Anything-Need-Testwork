import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Button, Form, Input, message } from 'antd';
import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { register, setAuth } from '../services/api';

const usernameRules = [
  {
    validator: (_, value) => {
      const username = value?.trim() || '';
      if (!username) return Promise.reject(new Error('请输入用户名'));
      if (username.length < 3 || username.length > 32) {
        return Promise.reject(new Error('用户名需为 3 至 32 位'));
      }
      if (!/^[\p{L}\p{N}_-]+$/u.test(username)) {
        return Promise.reject(new Error('用户名仅支持文字、字母、数字、下划线和短横线'));
      }
      return Promise.resolve();
    },
  },
];

export default function Register() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const handleSubmit = async (values) => {
    setLoading(true);
    try {
      const data = await register(values.username.trim(), values.password);
      setAuth(data);
      message.success('注册成功，欢迎使用');
      navigate(location.state?.from || '/', { replace: true });
    } catch (err) {
      const detail = err.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '注册失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page register-page">
      <div className="login-backdrop" aria-hidden="true">
        <div className="login-aurora">
          <div className="login-blob login-blob-1" />
          <div className="login-blob login-blob-2" />
          <div className="login-blob login-blob-3" />
        </div>
        <div className="login-liquid-orb login-liquid-orb-left" />
        <div className="login-liquid-orb login-liquid-orb-right" />
      </div>
      <div className="login-grain" />

      <main className="login-card register-card" aria-label="注册 WhiteBear-Test 账号">
        <div className="login-brand register-brand">
          <div className="login-brand-icon" aria-hidden="true">WB</div>
          <div className="login-brand-title">创建账号</div>
          <div className="login-brand-sub">WHITEBEAR-TEST</div>
        </div>

        <Form layout="vertical" colon={false} onFinish={handleSubmit} requiredMark={false} className="login-form">
          <Form.Item label="用户名" name="username" rules={usernameRules} validateTrigger="onBlur">
            <Input
              size="large"
              prefix={<UserOutlined />}
              placeholder="请输入 3 至 32 位用户名"
              autoComplete="username"
              maxLength={32}
              autoFocus
            />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 8, message: '密码至少需要 8 位' },
              { max: 128, message: '密码不能超过 128 位' },
            ]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="请输入至少 8 位密码"
              autoComplete="new-password"
              maxLength={128}
            />
          </Form.Item>
          <Form.Item
            label="确认密码"
            name="confirmPassword"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入密码' },
              ({ getFieldValue }) => ({
                validator: (_, value) => (
                  !value || getFieldValue('password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致'))
                ),
              }),
            ]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="再次输入密码"
              autoComplete="new-password"
              maxLength={128}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={loading} className="login-submit">
            注册
          </Button>
        </Form>

        <div className="login-switch">
          已有账号？
          <Link to="/login" state={location.state}>返回登录</Link>
        </div>
      </main>

      <div className="login-footer">AI 驱动的测试用例生成与管理</div>
    </div>
  );
}
