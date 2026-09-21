import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/cases' },
  {
    path: '/cases',
    name: 'cases',
    component: () => import('@/views/CaseManagement.vue'),
  },
  {
    path: '/execute',
    name: 'execute',
    component: () => import('@/views/ExecutionConsole.vue'),
  },
  {
    path: '/diagnosis',
    name: 'diagnosis',
    component: () => import('@/views/DiagnosisView.vue'),
  },
  {
    path: '/reports',
    name: 'reports',
    component: () => import('@/views/ReportView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
