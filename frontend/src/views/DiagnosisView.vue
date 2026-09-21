<script setup lang="ts">
import { ref } from 'vue'

const issues = ref([
  {
    id: 1,
    title: '登录失败：错误提示未出现',
    level: 'P0',
    evidence: ['截图 2026-09-21 12:41:29', '接口 /api/v1/login 返回 401'],
    reason: '后端状态码正常，但前端错误提示没有被渲染，可能是条件判断缺失。',
    suggestion: '在 catch 分支中补充错误消息映射，并确认状态码与提示文案的一致性。',
    confirmed: true,
  },
  {
    id: 2,
    title: '页面元素定位变更',
    level: 'P1',
    evidence: ['DOM 快照比对', 'button[data-testid="submit"] 缺失'],
    reason: '定位器依赖旧的 data-testid，元素已改成类名选择器。',
    suggestion: '采用更稳定的语义化定位器，优先使用 role/name 或 data-testid。',
    confirmed: false,
  },
])
</script>

<template>
  <div class="diagnosis-grid">
    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>失败归因</h3>
          <el-tag type="success">AI 诊断已生成</el-tag>
        </div>
      </template>

      <div v-for="item in issues" :key="item.id" class="issue-card">
        <div class="issue-head">
          <div>
            <h4>{{ item.title }}</h4>
            <div class="issue-meta">{{ item.level }} · {{ item.confirmed ? '已确认' : '待人工确认' }}</div>
          </div>
          <el-tag :type="item.level === 'P0' ? 'danger' : 'warning'">{{ item.level }}</el-tag>
        </div>

        <div class="section">
          <div class="section-title">证据链</div>
          <ul>
            <li v-for="(e, idx) in item.evidence" :key="idx">{{ e }}</li>
          </ul>
        </div>

        <div class="section">
          <div class="section-title">原因分析</div>
          <p>{{ item.reason }}</p>
        </div>

        <div class="section">
          <div class="section-title">建议修复</div>
          <p>{{ item.suggestion }}</p>
        </div>
      </div>
    </el-card>

    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>证据时间线</h3>
        </div>
      </template>

      <el-timeline>
        <el-timeline-item timestamp="12:41:08" type="primary">页面加载完成</el-timeline-item>
        <el-timeline-item timestamp="12:41:15" type="warning">输入异常密码</el-timeline-item>
        <el-timeline-item timestamp="12:41:22" type="danger">接口返回 401</el-timeline-item>
        <el-timeline-item timestamp="12:41:29" type="success">AI 归因生成</el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<style scoped>
.diagnosis-grid {
  display: grid;
  grid-template-columns: 1.5fr 0.9fr;
  gap: 20px;
}

.panel {
  background: rgba(255, 255, 255, 0.75);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-header h3 {
  margin: 0;
}

.issue-card {
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  padding: 18px;
  margin-bottom: 16px;
}

.issue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}

.issue-head h4 {
  margin: 0 0 4px;
  font-size: 18px;
}

.issue-meta {
  font-size: 12px;
  color: #64748b;
}

.section {
  margin-top: 12px;
}

.section-title {
  font-size: 12px;
  color: #6366f1;
  margin-bottom: 6px;
  font-weight: 600;
}

.section ul {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  line-height: 1.8;
}

.section p {
  margin: 0;
  color: #475569;
  line-height: 1.7;
}
</style>
