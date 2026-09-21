<script setup lang="ts">
import { ref } from 'vue'

const reportData = ref({
  pass: 96.8,
  fail: 3.2,
  coverage: 87,
  avgTime: '2.4 min',
})

const chartBars = [58, 70, 66, 82, 88, 93, 96]
</script>

<template>
  <div class="reports-grid">
    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>执行总览</h3>
          <el-button type="primary" plain>导出报告</el-button>
        </div>
      </template>

      <div class="stats-grid">
        <div class="stat-box">
          <span>成功率</span>
          <strong>{{ reportData.pass }}%</strong>
        </div>
        <div class="stat-box">
          <span>失败率</span>
          <strong>{{ reportData.fail }}%</strong>
        </div>
        <div class="stat-box">
          <span>覆盖率</span>
          <strong>{{ reportData.coverage }}%</strong>
        </div>
        <div class="stat-box">
          <span>平均耗时</span>
          <strong>{{ reportData.avgTime }}</strong>
        </div>
      </div>

      <div class="bars">
        <div v-for="(value, idx) in chartBars" :key="idx" class="bar-group">
          <div class="bar" :style="{ height: `${value}%` }"></div>
          <span>{{ ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][idx] }}</span>
        </div>
      </div>
    </el-card>

    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>风险概览</h3>
        </div>
      </template>

      <div class="risk-list">
        <div class="risk-item">
          <span class="dot red"></span>
          <div>
            <strong>支付链路</strong>
            <small>3 个高优先级问题</small>
          </div>
        </div>
        <div class="risk-item">
          <span class="dot orange"></span>
          <div>
            <strong>登录流程</strong>
            <small>1 个待确认缺陷</small>
          </div>
        </div>
        <div class="risk-item">
          <span class="dot green"></span>
          <div>
            <strong>权限校验</strong>
            <small>无新增问题</small>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.reports-grid {
  display: grid;
  grid-template-columns: 1.5fr 0.9fr;
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.stat-box {
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  padding: 16px;
}

.stat-box span {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-bottom: 8px;
}

.stat-box strong {
  font-size: 28px;
}

.bars {
  display: flex;
  align-items: end;
  gap: 12px;
  height: 200px;
  margin-top: 22px;
}

.bar-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: end;
  flex: 1;
  gap: 8px;
  height: 100%;
}

.bar {
  width: 100%;
  max-width: 38px;
  min-height: 18px;
  border-radius: 10px 10px 0 0;
  background: linear-gradient(180deg, #60a5fa, #8b5cf6);
}

.bar-group span {
  font-size: 12px;
  color: #64748b;
}

.risk-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 12px;
}

.risk-item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  padding: 14px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.red { background: #ef4444; }
.orange { background: #f59e0b; }
.green { background: #10b981; }

.risk-item strong {
  display: block;
}

.risk-item small {
  color: #64748b;
}
</style>
