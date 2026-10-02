// GenerateFlow 向导共享的常量与纯函数（无 React 依赖）

export const QUALITY_COLOR = { pass: 'green', warning: 'orange', fail: 'red' };
export const REVIEW_COLOR = { pending: 'default', to_confirm: 'orange', adopted: 'green', rejected: 'red', edited: 'blue' };
export const QUALITY_LABEL = { pass: '通过', warning: '警告', fail: '不合格' };
export const REVIEW_LABEL = { pending: '待评审', to_confirm: '待确认', adopted: '已采纳', rejected: '已驳回', edited: '已编辑' };
export const TYPE_LABEL = { functional: '功能', boundary: '边界', exception: '异常' };
export const STATUS_LABEL = {
  pending: '等待中', generating: '生成中', completed: '已完成', failed: '失败',
};

const STRATEGY_ICONS = { full: '📋', quick: '💨' };

const DEFAULT_STRATEGIES = [
  {
    key: 'full',
    title: '完整用例',
    description: '覆盖功能、边界与异常，并自动标记其中的冒烟用例，适合上线前回归',
    min_cases_per_feature: 5,
    max_cases_per_feature: 12,
    recommended: true,
  },
  {
    key: 'quick',
    title: '快速冒烟',
    description: '只生成核心主路径冒烟用例，每个功能点 2～4 条，省时省成本',
    min_cases_per_feature: 2,
    max_cases_per_feature: 4,
    recommended: false,
  },
];

export const STRATEGY_LABEL = {
  full: '完整用例',
  quick: '快速冒烟',
  detailed: '完整用例',
  standard: '完整用例',
  smoke: '快速冒烟',
  functional_only: '快速冒烟',
};

export const SKILL_LABEL = {
  case_writer: '综合用例',
  comprehensive: '综合用例',
  security: '安全 / 权限',
  api_test: '接口测试',
  api: '接口测试',
  requirement_parser: '需求解析',
};

export const PRIORITY_OPTIONS = [
  { label: 'P0', value: 'P0' },
  { label: 'P1', value: 'P1' },
  { label: 'P2', value: 'P2' },
];

export const CASE_TYPE_OPTIONS = [
  { label: '功能', value: 'functional' },
  { label: '边界', value: 'boundary' },
  { label: '异常', value: 'exception' },
];

export const REJECT_REASONS = ['重复场景', '步骤不可执行', '业务规则错误', '与需求无关', '其他'];

export function parseJudgeIssues(raw) {
  if (!raw) return null;
  try {
    const d = JSON.parse(raw);
    return typeof d === 'object' && d !== null ? d : null;
  } catch {
    return null;
  }
}

export function judgeScoreColor(score) {
  if (score >= 4) return 'var(--success)';
  if (score >= 3) return 'var(--warning)';
  return 'var(--error)';
}

export function mapStrategies(catalog) {
  const list = catalog?.strategies?.length ? catalog.strategies : DEFAULT_STRATEGIES;
  return list.map(s => ({
    key: s.key,
    title: s.title,
    desc: s.description,
    icon: STRATEGY_ICONS[s.key] || '⚡',
    minCasesPerFeature: s.min_cases_per_feature,
    maxCasesPerFeature: s.max_cases_per_feature,
    recommended: s.recommended,
  }));
}

export function mapSpecialists(catalog) {
  if (Array.isArray(catalog?.specialist)) {
    return catalog.specialist.map(s => ({
      key: s.name,
      label: s.title,
      desc: s.description,
      executionOrder: Number.isFinite(s.execution_order) ? s.execution_order : 100,
    })).sort((left, right) => (
      left.executionOrder - right.executionOrder || left.key.localeCompare(right.key)
    ));
  }
  return [];
}

export function buildPolicyRows(policyState) {
  return (policyState?.specialists || []).map(item => {
    const override = item.overrides || null;
    return {
      key: item.skill_name,
      override,
      defaults: {
        timeoutSeconds: item.defaults.timeout_seconds,
        maxCases: item.defaults.max_cases,
        executionOrder: item.defaults.execution_order,
        promptVersion: item.defaults.prompt_version,
        promptVersions: item.defaults.prompt_versions,
      },
      resolved: item.resolved,
      sources: {
        timeoutSeconds: override?.timeout_seconds != null ? 'project' : 'manifest',
        maxCases: override?.max_cases != null ? 'project' : 'manifest',
        executionOrder: override?.execution_order != null ? 'project' : 'manifest',
        promptVersion: override?.prompt_version != null ? 'project' : 'manifest',
      },
    };
  });
}

export function toSparsePolicyWrite(rows, baseRevision) {
  return {
    base_revision: baseRevision,
    overrides: (rows || []).filter(row => row.override).map(row => row.override),
  };
}

const POLICY_FIELDS = [
  ['timeout_seconds', 'timeoutSeconds'],
  ['max_cases', 'maxCases'],
  ['execution_order', 'executionOrder'],
  ['prompt_version', 'promptVersion'],
];

// Keep the editor state sparse: values equal to the deployed manifest default
// are represented by null, so a later manifest update can take effect naturally.
export function updatePolicyRow(rows, skillName, patch) {
  return (rows || []).map(row => {
    if (row.key !== skillName) return row;

    const prior = row.override || {};
    const changed = (field) => Object.prototype.hasOwnProperty.call(patch, field)
      ? patch[field]
      : (prior[field] ?? null);
    const override = {
      skill_name: row.key,
      enabled: patch.enabled ?? prior.enabled ?? row.resolved.enabled,
      timeout_seconds: changed('timeout_seconds'),
      max_cases: changed('max_cases'),
      execution_order: changed('execution_order'),
      prompt_version: changed('prompt_version'),
    };

    for (const [field, defaultKey] of POLICY_FIELDS) {
      if (override[field] === row.defaults[defaultKey]) override[field] = null;
    }
    const hasCustomValue = POLICY_FIELDS.some(([field]) => override[field] != null);
    return { ...row, override: override.enabled || hasCustomValue ? override : null };
  });
}

export function enabledSpecialistOptions(catalog, policyState) {
  const enabled = new Set(
    (policyState?.specialists || [])
      .filter(item => item.resolved?.enabled)
      .map(item => item.skill_name),
  );
  return mapSpecialists(catalog).filter(item => enabled.has(item.key));
}

export function mergeStoredSpecialists(options, storedNames) {
  const result = options.map(item => ({ ...item }));
  const known = new Set(result.map(item => item.key));
  for (const rawName of storedNames || []) {
    const name = String(rawName);
    if (!name || known.has(name)) continue;
    known.add(name);
    result.push({
      key: name,
      label: `${name}（当前不可用）`,
      desc: '该 Skill 已从当前部署移除，保存配置前请确认是否移除',
      executionOrder: Number.MAX_SAFE_INTEGER,
      unavailable: true,
    });
  }
  return result;
}

export function moduleLabel(module) {
  return module?.trim() || '未分类';
}

export function groupItemsByModule(items) {
  const groups = {};
  items.forEach((item) => {
    const mod = moduleLabel(item.module);
    if (!groups[mod]) groups[mod] = [];
    groups[mod].push(item);
  });
  return groups;
}

export function calcGenerationEstimate(confirmedItems, strategyKey, specialistSkills, strategies) {
  const list = strategies?.length ? strategies : mapStrategies(null);
  const strategy = list.find(s => s.key === strategyKey) || list[1] || list[0];
  const featureCount = confirmedItems.length;
  const callsPerFeature = 1 + specialistSkills.length;
  const skillCalls = featureCount * callsPerFeature;
  const minCases = featureCount * strategy.minCasesPerFeature + featureCount * specialistSkills.length * 2;
  const maxCases = featureCount * strategy.maxCasesPerFeature + featureCount * specialistSkills.length * 5;
  return {
    featureCount,
    moduleCount: new Set(confirmedItems.map(i => moduleLabel(i.module))).size,
    skillCalls,
    minCases,
    maxCases,
  };
}

export function stepsToText(steps) {
  if (!steps) return '';
  try {
    const parsed = JSON.parse(steps);
    if (Array.isArray(parsed)) return parsed.join('\n');
  } catch { /* keep raw */ }
  return steps;
}

export function textToSteps(text) {
  const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
  return JSON.stringify(lines);
}

export function parseScope(raw) {
  if (!raw) return { in_scope: [], out_scope: [], risks: [] };
  try {
    const d = JSON.parse(raw);
    return {
      in_scope: d.in_scope || [],
      out_scope: d.out_scope || [],
      risks: d.risks || [],
    };
  } catch {
    return { in_scope: [], out_scope: [], risks: [] };
  }
}

export function scopeToForm(raw) {
  const s = parseScope(raw);
  return {
    in_scope: (s.in_scope || []).join('\n'),
    out_scope: (s.out_scope || []).join('\n'),
    risks: (s.risks || []).join('\n'),
  };
}

export function formToScopeJson(form) {
  const toArr = (t) => (t || '').split('\n').map(s => s.trim()).filter(Boolean);
  return JSON.stringify({
    in_scope: toArr(form.in_scope),
    out_scope: toArr(form.out_scope),
    risks: toArr(form.risks),
  });
}
