import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildPolicyRows, enabledSpecialistOptions, toSparsePolicyWrite, updatePolicyRow,
} from '../src/pages/generate/constants.js';

const state = {
  revision_no: 3,
  specialists: [
    {
      skill_name: 'security',
      overrides: { skill_name: 'security', enabled: true, timeout_seconds: 180, max_cases: null, execution_order: null, prompt_version: 'v2' },
      defaults: { timeout_seconds: 420, max_cases: 5, execution_order: 10, prompt_version: 'v1', prompt_versions: ['v1', 'v2'] },
      resolved: { enabled: true, timeout_seconds: 180, max_cases: 5, execution_order: 10, prompt_version: 'v2' },
    },
    {
      skill_name: 'api_test',
      overrides: null,
      defaults: { timeout_seconds: 420, max_cases: 5, execution_order: 20, prompt_version: 'v1', prompt_versions: ['v1'] },
      resolved: { enabled: false, timeout_seconds: 420, max_cases: 5, execution_order: 20, prompt_version: 'v1' },
    },
  ],
};

test('policy rows expose manifest versus project source and save only sparse overrides', () => {
  const rows = buildPolicyRows(state);
  const security = rows.find(row => row.key === 'security');
  assert.equal(security.sources.timeoutSeconds, 'project');
  assert.equal(security.sources.maxCases, 'manifest');
  assert.deepEqual(toSparsePolicyWrite(rows, state.revision_no), {
    base_revision: 3,
    overrides: [state.specialists[0].overrides],
  });
});

test('generation options retain only project-enabled catalog skills', () => {
  const catalog = { specialist: [
    { name: 'api_test', title: 'API', description: '', execution_order: 20 },
    { name: 'security', title: 'Security', description: '', execution_order: 10 },
    { name: 'new_skill', title: 'New', description: '', execution_order: 30 },
  ] };
  assert.deepEqual(enabledSpecialistOptions(catalog, state).map(item => item.key), ['security']);
});

test('policy editor keeps only meaningful project overrides', () => {
  const rows = buildPolicyRows(state);
  const enabled = updatePolicyRow(rows, 'api_test', { enabled: true });
  const configured = updatePolicyRow(enabled, 'api_test', { max_cases: 3, prompt_version: 'v1' });
  const api = configured.find(row => row.key === 'api_test');

  assert.deepEqual(api.override, {
    skill_name: 'api_test', enabled: true, timeout_seconds: null,
    max_cases: 3, execution_order: null, prompt_version: null,
  });

  const reset = updatePolicyRow(configured, 'api_test', { enabled: false, max_cases: 5 });
  assert.equal(reset.find(row => row.key === 'api_test').override, null);
});
