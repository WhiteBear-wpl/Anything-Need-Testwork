<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const menu = [
  { label: '用例管理', path: '/cases', icon: 'Document' },
  { label: '执行控制台', path: '/execute', icon: 'VideoPlay' },
  { label: '诊断中心', path: '/diagnosis', icon: 'Cpu' },
  { label: '报告分析', path: '/reports', icon: 'DataLine' },
]

const activeMenu = computed(() => {
  const index = menu.findIndex((item) => item.path === route.path)
  return index >= 0 ? index : 0
})

const navMeta = computed(() => {
  const current = menu[activeMenu.value]
  return {
    title: current?.label ?? '用例管理',
    summary: current?.path === '/cases' ? '48 个用例 · 12 个待执行' : current?.path === '/execute' ? '3 个任务正在运行' : current?.path === '/diagnosis' ? '2 个失败已归因' : '本周稳定性 96.8%',
  }
})

const go = (path: string) => router.push(path)
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="260px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">AI</div>
        <div>
          <div class="brand-title">智能测试平台</div>
          <div class="brand-subtitle">workbench</div>
        </div>
      </div>

      <el-menu
        :default-active="String(activeMenu)"
        class="sidebar-menu"
        :router="false"
        @select="(_index: string, key: string) => go(menu[Number(key)].path)"
      >
        <el-menu-item v-for="(item, index) in menu" :key="item.path" :index="String(index)">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div class="status-pill">
          <span class="dot"></span>
          运行正常
        </div>
        <div class="footer-meta">Last sync 12:44:02</div>
      </div>
    </el-aside>

    <el-container class="main-panel">
      <el-header class="topbar">
        <div>
          <div class="eyebrow">控制台</div>
          <h1>{{ navMeta.title }}</h1>
        </div>
        <div class="top-actions">
          <el-button type="primary" plain>生成用例</el-button>
          <el-button type="primary">立即执行</el-button>
        </div>
      </el-header>

      <el-main class="main-body">
        <div class="summary-strip">
          <div class="summary-card">
            <span class="label">今日执行</span>
            <strong>128</strong>
            <small>+18% vs yesterday</small>
          </div>
          <div class="summary-card">
            <span class="label">成功率</span>
            <strong>96.8%</strong>
            <small>稳定性提升</small>
          </div>
          <div class="summary-card">
            <span class="label">AI 诊断</span>
            <strong>19</strong>
            <small>2 条待确认</small>
          </div>
          <div class="summary-card">
            <span class="label">缺陷数</span>
            <strong>7</strong>
            <small>3 个严重级别</small>
          </div>
        </div>

        <div class="page-intro">
          <span class="intro-badge">{{ navMeta.title }}</span>
          <span>{{ navMeta.summary }}</span>
        </div>

        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  height: 100vh;
  background: linear-gradient(180deg, #f5f7ff 0%, #eef3ff 100%);
  color: #1f2937;
}

.sidebar {
  background: rgba(15, 23, 42, 0.96);
  color: white;
  padding: 24px 18px;
  border-right: 1px solid rgba(148, 163, 184, 0.14);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px 22px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #60a5fa, #8b5cf6);
  color: white;
  font-weight: 700;
}

.brand-title {
  font-weight: 700;
}

.brand-subtitle {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.65);
}

.sidebar-menu {
  border: none;
  background: transparent;
}

.sidebar-menu :deep(.el-menu-item) {
  border-radius: 12px;
  margin: 6px 0;
  color: rgba(255, 255, 255, 0.82);
  height: 48px;
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(96, 165, 250, 0.25), rgba(139, 92, 246, 0.2));
  color: white;
}

.sidebar-footer {
  position: absolute;
  left: 18px;
  right: 18px;
  bottom: 18px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(16, 185, 129, 0.12);
  color: #a7f3d0;
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 12px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #34d399;
  display: inline-block;
}

.footer-meta {
  margin-top: 10px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.58);
}

.main-panel {
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 22px 28px;
  background: rgba(255, 255, 255, 0.6);
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  backdrop-filter: blur(12px);
}

.eyebrow {
  color: #6366f1;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}

.topbar h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 700;
}

.top-actions {
  display: flex;
  gap: 12px;
}

.main-body {
  padding: 22px 28px 28px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

.summary-card {
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 18px;
  padding: 18px 18px 14px;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.04);
}

.summary-card .label {
  display: block;
  color: #64748b;
  font-size: 13px;
  margin-bottom: 8px;
}

.summary-card strong {
  display: block;
  font-size: 30px;
  margin-bottom: 6px;
  color: #0f172a;
}

.summary-card small {
  color: #475569;
}

.page-intro {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #475569;
  margin-bottom: 18px;
}

.intro-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
  font-weight: 600;
}
</style>
