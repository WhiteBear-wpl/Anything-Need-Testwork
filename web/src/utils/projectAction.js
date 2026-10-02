export const GEN_STATUS_LABEL = {
  pending: '等待中',
  generating: '生成中',
  completed: '已完成',
  failed: '失败',
};

export function formatRelativeTime(dateStr) {
  if (!dateStr) return '尚未生成';
  const date = new Date(dateStr);
  const diffMs = Date.now() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return '今天';
  if (diffDays === 1) return '昨天';
  if (diffDays < 7) return `${diffDays} 天前`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} 周前`;
  return date.toLocaleDateString();
}

export function getGenerationStatusClass(status) {
  if (status === 'completed') return 'status-success';
  if (status === 'failed') return 'status-error';
  if (status === 'generating' || status === 'pending') return 'status-info';
  return 'status-muted';
}

/** 项目阶段元信息：与后端 ProjectStageOut.stage 一一对应 */
export const STAGE_META = [
  { key: 'import', label: '需求导入', desc: '上传或粘贴需求文档，AI 解析为功能点' },
  { key: 'confirm', label: '功能清单', desc: '核对 AI 解析的功能点，补充边界与风险' },
  { key: 'generate', label: 'AI 生成', desc: '选择策略与专项 Skill，批量生成候选用例' },
  { key: 'review', label: '人工评审', desc: '逐条评审候选用例，采纳或驳回' },
  { key: 'done', label: '用例入库', desc: '已采纳用例进入用例库，可开始新一轮生成' },
];

export function getStageIndex(stageKey) {
  const idx = STAGE_META.findIndex((s) => s.key === stageKey);
  return idx === -1 ? 0 : idx;
}

/** 把后端 ProjectStageOut 转成「唯一下一步」操作 */
export function getStageAction(projectId, stage) {
  if (!stage) return null;
  const base = `/projects/${projectId}`;
  switch (stage.stage) {
    case 'import':
      return { label: '导入需求', path: `${base}/generate`, kind: 'generate' };
    case 'confirm':
      return {
        label: '继续确认功能点',
        path: `${base}/generate?doc=${stage.document_id}`,
        kind: 'generate',
        hint: stage.item_count ? `${stage.item_count} 个功能点待确认` : '',
      };
    case 'generate':
      return {
        label: stage.failed ? '重新生成' : '开始 AI 生成',
        path: `${base}/generate?doc=${stage.document_id}`,
        kind: 'generate',
        hint: stage.failed ? '上次生成失败' : '',
      };
    case 'review':
      if (stage.generating) {
        return { label: '查看生成进度', path: `${base}/generate?task=${stage.task_id}`, kind: 'generate' };
      }
      return {
        label: `继续评审（${stage.pending_drafts} 条待处理）`,
        path: `${base}/generate?task=${stage.task_id}`,
        kind: 'generate',
        hint: `${stage.pending_drafts} 条候选用例待评审`,
      };
    case 'done':
    default:
      return {
        label: '查看用例库',
        path: `${base}/testcases`,
        kind: 'view',
        hint: stage.testcase_count ? `已入库 ${stage.testcase_count} 条用例` : '',
      };
  }
}

/** 继续工作 / AI 生成类操作（青绿） */
export function getProjectWorkAction(project) {
  const id = project.id;
  const status = project.last_generation_status;

  if (project.generation_count === 0) {
    return { label: '开始 AI 生成', path: `/projects/${id}/generate`, kind: 'generate' };
  }
  if (status === 'generating' || status === 'pending') {
    return { label: '查看进度', path: `/projects/${id}/generate`, kind: 'generate' };
  }
  if (status === 'failed') {
    return { label: '重新生成', path: `/projects/${id}/generate`, kind: 'generate' };
  }
  return { label: '继续生成', path: `/projects/${id}/generate`, kind: 'generate' };
}

/** 查看类操作（蓝色描边） */
export function getProjectViewAction(project) {
  const id = project.id;
  if (project.testcase_count > 0) {
    return { label: '查看用例', path: `/testcases?project=${id}`, kind: 'view' };
  }
  return { label: '项目概览', path: `/projects/${id}`, kind: 'view' };
}

export function getProjectPrimaryAction(project) {
  return getProjectWorkAction(project);
}

export function getProjectSecondaryAction(project) {
  return getProjectViewAction(project);
}

export function getProjectMetaLine(project) {
  const parts = [];
  if (project.last_generation_at) {
    parts.push(`${formatRelativeTime(project.last_generation_at)} 生成`);
    if (project.last_generation_status) {
      parts.push(GEN_STATUS_LABEL[project.last_generation_status] || project.last_generation_status);
    }
  } else {
    parts.push('尚未开始生成');
  }
  parts.push(`${project.testcase_count} 条用例`);
  return parts.join(' · ');
}
