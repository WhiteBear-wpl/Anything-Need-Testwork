<script setup lang="ts">
import { ref } from 'vue'

const cases = ref([
  {
    id: 101,
    title: '登录页 - 正常登录',
    type: 'UI',
    owner: 'alice',
    status: '待执行',
    priority: 'P0',
    duration: '2.1 min',
    summary: '验证登录成功后跳转到首页，并展示用户头像。',
    passRate: 92,
  },
  {
    id: 102,
    title: '用户列表 - 查询过滤',
    type: 'API',
    owner: 'bob',
    status: '执行中',
    priority: 'P1',
    duration: '1.4 min',
    summary: '校验过滤参数和返回字段结构一致。',
    passRate: 88,
  },
  {
    id: 103,
    title: '订单创建 - 存量数据',
    type: 'DATA',
    owner: 'carmen',
    status: '已通过',
    priority: 'P0',
    duration: '3.2 min',
    summary: '覆盖 corner cases，验证重复订单被拦截。',
    passRate: 97,
  },
  {
    id: 104,
    title: '支付校验 - 大额订单',
    type: 'RULE',
    owner: 'dora',
    status: '已失败',
    priority: 'P1',
    duration: '0.9 min',
    summary: '规则输出不符合业务阈值，需人工确认。',
    passRate: 61,
  },
])

const filters = ref(['全部', 'UI', 'API', 'DATA', 'RULE'])
const activeFilter = ref('全部')

const filteredCases = () => {
  if (activeFilter.value === '全部') return cases.value
  return cases.value.filter((item) => item.type === activeFilter.value)
}

const statusColors: Record<string, string> = {
  待执行: '#8b5cf6',
  执行中: '#f59e0b',
  已通过: '#10b981',
  已失败: '#ef4444',
}
</script>

<template>
  <div class="page-grid">
    <el-card class="panel">
      <template #header>
        <div class="panel-header">
          <h3>用例列表</h3>
          <el-button type="primary">新建用例</el-button>
        </div>
      </template>

      <div class="toolbar">
        <el-segmented v-model="activeFilter" :options="filters" />
        <el-input placeholder="搜索用例/ID" style="width: 220px" />
      </div>

      <el-table :data="filteredCases()" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="title" label="用例名称" min-width="210" />
        <el-table-column prop="type" label="类型" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.type === 'UI' ? 'primary' : scope.row.type === 'API' ? 'success' : scope.row.type === 'DATA' ? 'warning' : 'danger'">
              {{ scope.row.type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="owner" label="负责人" width="100" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="scope">
            <el-tag :style="{ background: `${statusColors[scope.row.status]}20`, color: statusColors[scope.row.status], borderColor: `${statusColors[scope.row.status]}60` }">
              {{ scope.row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="90" />
        <el-table-column prop="duration" label="耗时" width="100" />
        <el-table-column prop="passRate" label="通过率" width="110">
          <template #default="scope">
            <div class="rate-wrap">
              <span>{{ scope.row.passRate }}%</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="panel side-panel">
      <template #header>
        <div class="panel-header">
          <h3>生成结果</h3>
        </div>
      </template>

      <div class="prompt-box">
        <div class="prompt-title">自然语言输入</div>
        <p>“登录页输入错误密码后，应当展示‘密码错误’提示，不允许进入系统。”</p>
      </div>

      <div class="plan-box">
        <div class="plan-header">
          <span>生成计划</span>
          <el-tag type="success">已生成</el-tag>
        </div>
        <ul>
          <li>步骤 1：打开登录页</li>
          <li>步骤 2：输入错误密码</li>
          <li>步骤 3：点击登录按钮</li>
          <li>步骤 4：断言提示文案</li>
        </ul>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.page-grid {
  display: grid;
  grid-template-columns: 1.8fr 0.9fr;
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

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}

.rate-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(90deg, rgba(16, 185, 129, 0.12), rgba(59, 130, 246, 0.08));
}

.prompt-box,
.plan-box {
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  padding: 16px;
  margin-bottom: 16px;
}

.prompt-title {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  font-weight: 600;
}

.plan-box ul {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  line-height: 2;
}
</style>
