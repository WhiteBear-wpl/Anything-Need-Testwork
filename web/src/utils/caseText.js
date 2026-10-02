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

export function stepsToText(steps) {
  if (!steps) return '';
  try {
    const parsed = JSON.parse(steps);
    if (Array.isArray(parsed)) return parsed.map((s, i) => `${i + 1}. ${s}`).join('\n');
  } catch { /* keep raw */ }
  return steps;
}

export function textToSteps(text) {
  const lines = (text || '')
    .split('\n')
    .map((line) => line.replace(/^\d+[.、)]\s*/, '').trim())
    .filter(Boolean);
  return JSON.stringify(lines);
}
