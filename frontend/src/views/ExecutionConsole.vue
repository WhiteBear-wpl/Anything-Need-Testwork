<script setup lang="ts">
import { ref } from 'vue'

type LogStatus = 'success' | 'running' | 'warning' | 'error'

const logs = ref<Array<{
  id: number
  step: string
  status: LogStatus
  message: string
  timestamp: string
}>>([
  { id: 1, step: 'Step 1', status: 'success', message: '打开目标页面成功', timestamp: '12:41:10' },
  { id: 2, step: 'Step 2', status: 'running', message: '正在输入账号和密码', timestamp: '12:41:15' },
  { id: 3, step: 'Step 3', status: 'warning', message: '发现登录按钮在移动端被遮挡', timestamp: '12:41:22' },
  { id: 4, step: 'Step 4', status: 'error', message: '断言失败：未出现成功提示文案', timestamp: '12:41:30' },
])

const statusMap: Record<LogStatus, 'success' | 'primary' | 'warning' | 'danger'> = {
  success: 'success',
  running: 'primary',
  warning: 'warning',
  error: 'danger',
}
</script>

<template>
  <div class="console-grid">
    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>执行流水线</h3>
          <el-button type="primary">开始执行</el-button>
        </div>
      </template>

      <div class="run-card">
        <div class="run-head">
          <div>
            <div class="label">当前任务</div>
            <h4>API创建用户 → UI登录验证</h4>
          </div>
          <el-tag type="warning">执行中</el-tag>
        </div>

        <div class="run-metrics">
          <div>
            <span>总步骤</span>
            <strong>12</strong>
          </div>
          <div>
            <span>已完成</span>
            <strong>8</strong>
          </div>
          <div>
            <span>失败</span>
            <strong>1</strong>
          </div>
        </div>
      </div>

      <el-timeline style="margin-top: 18px;">
        <el-timeline-item
          v-for="item in logs"
          :key="item.id"
          :type="statusMap[item.status]"
          :timestamp="item.timestamp"
        >
          <div class="event-title">{{ item.step }}</div>
          <div class="event-text">{{ item.message }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-card>

    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>执行参数</h3>
        </div>
      </template>

      <el-form label-position="top" class="param-form">
        <el-form-item label="环境">
          <el-select value="staging" style="width: 100%">
            <el-option label="staging" value="staging" />
            <el-option label="prod" value="prod" />
          </el-select>
        </el-form-item>

        <el-form-item label="浏览器">
          <el-select value="chromium" style="width: 100%">
            <el-option label="chromium" value="chromium" />
            <el-option label="firefox" value="firefox" />
          </el-select>
        </el-form-item>

        <el-form-item label="重试策略">
          <el-input value="1 次重试" />
        </el-form-item>

        <el-form-item label="说明">
          <el-input type="textarea" :rows="5" value="执行前先校验数据库数据，随后执行登录与创建订单流程。" />
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.console-grid {
  display: grid;
  grid-template-columns: 1.6fr 0.9fr;
  gap: 20px;
}

.panel {
  background: rgba(255, 255, 255, 0.75);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h3 {
  margin: 0;
}

.run-card {
  background: linear-gradient(135deg, rgba(96, 165, 250, 0.08), rgba(139, 92, 246, 0.08));
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  padding: 18px;
}

.run-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}

.run-head h4 {
  margin: 0;
  font-size: 20px;
}

.run-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-top: 18px;
}

.run-metrics > div {
  background: rgba(255, 255, 255, 0.65);
  border-radius: 12px;
  padding: 12px;
}

.run-metrics span {
  display: block;
  font-size: 12px;
  color: #64748b;
}

.run-metrics strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
}

.event-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.event-text {
  color: #475569;
}

.param-form {
  margin-top: 8px;
}
</style>
