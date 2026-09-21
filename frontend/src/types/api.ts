export type CaseStatus = '待执行' | '执行中' | '已通过' | '已失败'
export type Priority = 'P0' | 'P1' | 'P2'
export type StepType = 'UI' | 'API' | 'DATA' | 'RULE'

export interface TestCaseItem {
  id: number
  title: string
  type: StepType
  owner: string
  status: CaseStatus
  priority: Priority
  duration: string
  summary: string
  passRate: number
}

export interface ExecutionLog {
  id: number
  step: string
  status: 'success' | 'warning' | 'error' | 'running'
  message: string
  timestamp: string
}

export interface DiagnosisItem {
  id: number
  title: string
  level: 'P0' | 'P1' | 'P2'
  evidence: string[]
  reason: string
  suggestion: string
  confirmed: boolean
}
