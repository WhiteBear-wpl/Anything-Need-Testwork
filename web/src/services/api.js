import axios from 'axios';

// ---- 登录认证 ----
const AUTH_KEY = 'aitc_auth';
const APP_BASE = import.meta.env.BASE_URL || '/';
const API_BASE = `${APP_BASE.replace(/\/$/, '')}/api`;

export const getAuth = () => {
  try {
    return JSON.parse(localStorage.getItem(AUTH_KEY)) || null;
  } catch {
    return null;
  }
};
export const setAuth = (auth) => localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
export const clearAuth = () => localStorage.removeItem(AUTH_KEY);

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = getAuth()?.token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = error.config?.url || '';
    const isPublicAuthRequest = ['/auth/login', '/auth/register']
      .some(path => requestUrl.endsWith(path));
    if (error.response?.status === 401 && !isPublicAuthRequest) {
      clearAuth();
      const loginPath = `${APP_BASE}login`;
      if (window.location.pathname !== loginPath) window.location.assign(loginPath);
    }
    return Promise.reject(error);
  },
);

export const login = (username, password) =>
  api.post('/auth/login', { username, password }).then(r => r.data);
export const register = (username, password) =>
  api.post('/auth/register', { username, password }).then(r => r.data);
export const logoutRequest = (token) => api.post(
  '/auth/logout',
  { token },
  token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
).catch(() => {});

export const getSkills = () => api.get('/skills').then(r => r.data);

export const getProjects = () => api.get('/projects').then(r => r.data);
export const getHomeOverview = () => api.get('/projects/overview').then(r => r.data);
export const createProject = (data) => api.post('/projects', data).then(r => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then(r => r.data);
export const updateProject = (id, data) => api.patch(`/projects/${id}`, data).then(r => r.data);
export const getProjectSkillPolicies = (id) =>
  api.get(`/projects/${id}/skill-policies`).then(r => r.data);
export const updateProjectSkillPolicies = (id, payload) =>
  api.put(`/projects/${id}/skill-policies`, payload).then(r => r.data);
export const getProjectStage = (id) => api.get(`/projects/${id}/stage`).then(r => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`);

export const getRequirements = (projectId) =>
  api.get(`/projects/${projectId}/requirements`).then(r => r.data);
export const createRequirement = (projectId, data) =>
  api.post(`/projects/${projectId}/requirements`, data).then(r => r.data);
export const uploadRequirementFile = (projectId, file, title) => {
  const form = new FormData();
  form.append('file', file);
  if (title?.trim()) form.append('title', title.trim());
  return api.post(`/projects/${projectId}/requirements/upload`, form).then(r => r.data);
};
export const structureRequirement = (projectId, docId) =>
  api.post(`/projects/${projectId}/requirements/${docId}/structure`).then(r => r.data);
export const updateRequirementScope = (projectId, docId, testScope) =>
  api.patch(`/projects/${projectId}/requirements/${docId}/scope`, { test_scope: testScope }).then(r => r.data);
export const generateRequirementScope = (projectId, docId) =>
  api.post(`/projects/${projectId}/requirements/${docId}/scope/generate`).then(r => r.data);
export const exportFeatureList = (projectId, docId, format = 'xlsx') =>
  api.get(`/projects/${projectId}/requirements/${docId}/featurelist/export`, { params: { format }, responseType: 'blob' });
export const importFeatureList = (projectId, file, title) => {
  const form = new FormData();
  form.append('file', file);
  if (title?.trim()) form.append('title', title.trim());
  return api.post(`/projects/${projectId}/requirements/featurelist/import`, form).then(r => r.data);
};
export const confirmRequirement = (projectId, docId, itemIds) =>
  api.post(`/projects/${projectId}/requirements/${docId}/confirm`, { item_ids: itemIds }).then(r => r.data);
export const updateRequirementItem = (projectId, docId, itemId, data) =>
  api.patch(`/projects/${projectId}/requirements/${docId}/items/${itemId}`, data).then(r => r.data);
export const createRequirementItem = (projectId, docId, data) =>
  api.post(`/projects/${projectId}/requirements/${docId}/items`, data).then(r => r.data);
export const deleteRequirementItem = (projectId, docId, itemId) =>
  api.delete(`/projects/${projectId}/requirements/${docId}/items/${itemId}`);

export const getGenerations = (projectId) =>
  api.get(`/projects/${projectId}/generations`).then(r => r.data);
export const getGenerationSummaries = (projectId) =>
  api.get(`/projects/${projectId}/generations/summary`).then(r => r.data);
export const createGeneration = (projectId, data) =>
  api.post(`/projects/${projectId}/generations`, data).then(r => r.data);
export const getGeneration = (projectId, taskId) =>
  api.get(`/projects/${projectId}/generations/${taskId}`).then(r => r.data);
export const getGenerationRun = (projectId, taskId) =>
  api.get(`/projects/${projectId}/generations/${taskId}/run`).then(r => r.data);
export const getGenerationRunEvents = (projectId, taskId, afterSequence = 0, runId = null) =>
  api.get(`/projects/${projectId}/generations/${taskId}/run/events`, {
    params: { after_sequence: afterSequence, ...(runId ? { run_id: runId } : {}) },
  }).then(r => r.data);
export const getGenerationCollaboration = (projectId, taskId, runId = null) =>
  api.get(`/projects/${projectId}/generations/${taskId}/collaboration`, {
    params: runId ? { run_id: runId } : {},
  }).then(r => r.data);
export const getCollaborationReport = (projectId, limit = 30) =>
  api.get(`/projects/${projectId}/generations/collaboration/report`, { params: { limit } })
    .then(r => r.data);
export const cancelGenerationRun = (projectId, taskId) =>
  api.post(`/projects/${projectId}/generations/${taskId}/run/cancel`).then(r => r.data);
export const retryGenerationRun = (projectId, taskId) =>
  api.post(`/projects/${projectId}/generations/${taskId}/run/retry`).then(r => r.data);
export const resumeGeneration = (projectId, taskId) =>
  api.post(`/projects/${projectId}/generations/${taskId}/resume`).then(r => r.data);
export const reviewDrafts = (projectId, taskId, data) =>
  api.post(`/projects/${projectId}/generations/${taskId}/review`, data).then(r => r.data);
export const editDraft = (projectId, taskId, draftId, data) =>
  api.patch(`/projects/${projectId}/generations/${taskId}/drafts/${draftId}`, data).then(r => r.data);
export const exportGenerationDrafts = (projectId, taskId, format = 'xlsx', smokeOnly = false) =>
  api.get(`/projects/${projectId}/generations/${taskId}/export`, {
    params: { format, smoke_only: smokeOnly },
    responseType: 'blob',
  });
export const rejudgeGeneration = (projectId, taskId) =>
  api.post(`/projects/${projectId}/generations/${taskId}/judge`).then(r => r.data);

export const getKnowledgeDocs = (projectId) =>
  api.get(`/projects/${projectId}/knowledge`).then(r => r.data);
export const createKnowledgeDoc = (projectId, data) =>
  api.post(`/projects/${projectId}/knowledge`, data).then(r => r.data);
export const uploadKnowledgeDoc = (projectId, file, title, sourceType = 'doc') => {
  const form = new FormData();
  form.append('file', file);
  if (title?.trim()) form.append('title', title.trim());
  form.append('source_type', sourceType);
  return api.post(`/projects/${projectId}/knowledge/upload`, form).then(r => r.data);
};
export const getKnowledgeChunks = (projectId, docId) =>
  api.get(`/projects/${projectId}/knowledge/${docId}/chunks`).then(r => r.data);
export const deleteKnowledgeDoc = (projectId, docId) =>
  api.delete(`/projects/${projectId}/knowledge/${docId}`);
export const searchKnowledge = (projectId, query, topK = 5) =>
  api.post(`/projects/${projectId}/knowledge/search`, { query, top_k: topK }).then(r => r.data);

export const getEvalSamples = () =>
  api.get('/evaluations/samples').then(r => r.data);
export const createEvalSample = (data) =>
  api.post('/evaluations/samples', data).then(r => r.data);
export const updateEvalSample = (sampleId, data) =>
  api.put(`/evaluations/samples/${sampleId}`, data).then(r => r.data);
export const deleteEvalSample = (sampleId) =>
  api.delete(`/evaluations/samples/${sampleId}`);
export const getFailureCandidates = () =>
  api.get('/evaluations/failure-candidates').then(r => r.data);
export const promoteFailureCandidate = (candidateId, data) =>
  api.post(`/evaluations/failure-candidates/${candidateId}/promote`, data).then(r => r.data);
export const dismissFailureCandidate = (candidateId) =>
  api.post(`/evaluations/failure-candidates/${candidateId}/dismiss`).then(r => r.data);
export const getEvalRuns = () =>
  api.get('/evaluations/runs').then(r => r.data);
export const createEvalRun = (data) =>
  api.post('/evaluations/runs', data).then(r => r.data);
export const getEvalRun = (runId) =>
  api.get(`/evaluations/runs/${runId}`).then(r => r.data);
export const setEvalRunBaseline = (runId) =>
  api.post(`/evaluations/runs/${runId}/baseline`).then(r => r.data);
export const compareEvalRuns = (runIds) =>
  api.get('/evaluations/compare', { params: { run_ids: runIds } }).then(r => r.data);
export const cancelEvalRun = (runId) =>
  api.post(`/evaluations/runs/${runId}/cancel`).then(r => r.data);
export const getEvalRunEvents = (runId, afterSequence = 0) =>
  api.get(`/evaluations/runs/${runId}/events`, { params: { after_sequence: afterSequence } }).then(r => r.data);
export const getEvalTask = (taskId) =>
  api.get(`/evaluations/tasks/${taskId}`).then(r => r.data);
export const deleteEvalRun = (runId) =>
  api.delete(`/evaluations/runs/${runId}`);

export const getTestcases = (projectId) =>
  api.get(`/projects/${projectId}/testcases`).then(r => r.data);
export const updateTestcase = (projectId, caseId, data) =>
  api.patch(`/projects/${projectId}/testcases/${caseId}`, data).then(r => r.data);
export const renameTestcaseCatalog = (projectId, data) =>
  api.patch(`/projects/${projectId}/testcases/catalog/rename`, data).then(r => r.data);
export const getAllTestcases = (projectId) =>
  api.get('/testcases', { params: projectId ? { project_id: projectId } : {} }).then(r => r.data);

export const getTestTasks = (projectId) =>
  api.get(`/projects/${projectId}/tasks`).then(r => r.data);
export const createTestTask = (projectId, data) =>
  api.post(`/projects/${projectId}/tasks`, data).then(r => r.data);
export const getTestTaskDetail = (projectId, taskId) =>
  api.get(`/projects/${projectId}/tasks/${taskId}`).then(r => r.data);
export const updateTestTask = (projectId, taskId, data) =>
  api.patch(`/projects/${projectId}/tasks/${taskId}`, data).then(r => r.data);
export const deleteTestTask = (projectId, taskId) =>
  api.delete(`/projects/${projectId}/tasks/${taskId}`);
export const getTaskDefects = (projectId, taskId, includeBlocked = false) =>
  api.get(`/projects/${projectId}/tasks/${taskId}/defects`, { params: { include_blocked: includeBlocked } }).then(r => r.data);
export const createBatch = (projectId, taskId, data) =>
  api.post(`/projects/${projectId}/tasks/${taskId}/batches`, data).then(r => r.data);
export const getBatchDetail = (projectId, taskId, batchId) =>
  api.get(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}`).then(r => r.data);
export const updateBatch = (projectId, taskId, batchId, data) =>
  api.patch(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}`, data).then(r => r.data);
export const deleteBatch = (projectId, taskId, batchId) =>
  api.delete(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}`);
export const markBatchCase = (projectId, taskId, batchId, batchCaseId, data) =>
  api.patch(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}/cases/${batchCaseId}`, data).then(r => r.data);
export const batchMarkBatchCases = (projectId, taskId, batchId, data) =>
  api.patch(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}/cases/batch`, data).then(r => r.data);
export const addBatchCases = (projectId, taskId, batchId, caseIds) =>
  api.post(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}/cases`, { case_ids: caseIds }).then(r => r.data);
export const removeBatchCase = (projectId, taskId, batchId, batchCaseId) =>
  api.delete(`/projects/${projectId}/tasks/${taskId}/batches/${batchId}/cases/${batchCaseId}`).then(r => r.data);

export const getAgentMessages = (projectId) =>
  api.get(`/projects/${projectId}/agent/messages`).then(r => r.data);
export const getAgentState = (projectId) =>
  api.get(`/projects/${projectId}/agent/state`).then(r => r.data);
export const clearAgentMessages = (projectId) =>
  api.delete(`/projects/${projectId}/agent/messages`);
export const getAgentRun = (projectId, runId) =>
  api.get(`/projects/${projectId}/agent-runs/${runId}`).then(r => r.data);
export const getAgentRunEvents = (projectId, runId, afterSequence = 0) =>
  api.get(`/projects/${projectId}/agent-runs/${runId}/events`, {
    params: { after_sequence: afterSequence },
  }).then(r => r.data);
export const getAgentRunChildren = (projectId, runId) =>
  api.get(`/projects/${projectId}/agent-runs/${runId}/children`).then(r => r.data);
export const getAgentRuns = (projectId, threadId = null, limit = 20) =>
  api.get(`/projects/${projectId}/agent-runs`, {
    params: { thread_id: threadId, limit },
  }).then(r => r.data);
export const cancelAgentRun = (projectId, runId) =>
  api.post(`/projects/${projectId}/agent-runs/${runId}/cancel`).then(r => r.data);

/**
 * Agent SSE 请求公共实现。返回可调用 abort() 的控制器。
 */
const streamAgentRequest = (url, body, onEvent) => {
  const controller = new AbortController();
  const run = async () => {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuth()?.token || ''}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!resp.ok) {
      let detail = `请求失败（${resp.status}）`;
      try {
        detail = (await resp.json()).detail || detail;
      } catch { /* 非 JSON 响应体，保留默认提示 */ }
      throw new Error(detail);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        try {
          onEvent(JSON.parse(line.slice(5)));
        } catch { /* 忽略无法解析的事件 */ }
      }
    }
  };
  return { promise: run(), abort: () => controller.abort() };
};

export const streamAgentRun = (projectId, runId, onEvent, afterSequence = 0) => {
  const controller = new AbortController();
  const run = async () => {
    const query = new URLSearchParams({ after_sequence: String(afterSequence || 0) });
    const resp = await fetch(
      `${API_BASE}/projects/${projectId}/agent-runs/${runId}/stream?${query}`,
      {
        headers: { Authorization: `Bearer ${getAuth()?.token || ''}` },
        signal: controller.signal,
      },
    );
    if (!resp.ok) throw new Error(`订阅运行失败（${resp.status}）`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        try { onEvent(JSON.parse(line.slice(5))); } catch { /* ignore malformed event */ }
      }
    }
  };
  return { promise: run(), abort: () => controller.abort() };
};

/**
 * 测试助手对话（SSE 流式）。
 * onEvent 会收到 tool_start/tool_end/token/approval_required/done/error。
 */
export const streamAgentChat = (
  projectId, question, onEvent, documentId = null, afterSequence = 0,
) =>
  streamAgentRequest(
    `${API_BASE}/projects/${projectId}/agent/chat`,
    { question, document_id: documentId, after_sequence: afterSequence },
    onEvent,
  );

/** 从 LangGraph checkpoint 恢复待确认的 Agent 操作。 */
export const resumeAgentChat = (
  projectId, checkpointThreadId, approved, onEvent, afterSequence = 0,
) =>
  streamAgentRequest(
    `${API_BASE}/projects/${projectId}/agent/resume`,
    { checkpoint_thread_id: checkpointThreadId, approved, after_sequence: afterSequence },
    onEvent,
  );

export const getSettings = () => api.get('/settings').then(r => r.data);
export const updateSettings = (data) => api.patch('/settings', data).then(r => r.data);
export const testModelConnection = (target) =>
  api.post('/settings/test', { target }).then(r => r.data);

// ---- Wiki（project_id 缺省 = 工作台总 Wiki） ----
export const getWikiPages = (projectId = null) =>
  api.get('/wiki', { params: projectId ? { project_id: projectId } : {} }).then(r => r.data);
export const createWikiPage = (data) => api.post('/wiki', data).then(r => r.data);
export const updateWikiPage = (pageId, data) => api.patch(`/wiki/${pageId}`, data).then(r => r.data);
export const deleteWikiPage = (pageId) => api.delete(`/wiki/${pageId}`);
export const copyWikiToProject = (pageId, targetProjectId) =>
  api.post(`/wiki/${pageId}/copy`, { target_project_id: targetProjectId }).then(r => r.data);

// ---- 测试骨架 ----
export const getSkeletonOptions = () => api.get('/projects/skeleton/options').then(r => r.data);
export const getSkeleton = (projectId) =>
  api.get(`/projects/${projectId}/skeleton`).then(r => r.data);
export const generateSkeleton = (projectId, data) =>
  api.post(`/projects/${projectId}/skeleton/generate`, data).then(r => r.data);
export const updateSkeletonFiles = (projectId, files) =>
  api.patch(`/projects/${projectId}/skeleton/files`, { files }).then(r => r.data);

export default api;
