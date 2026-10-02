import assert from 'node:assert/strict';
import test from 'node:test';

import {
  presentDualTrackSummary,
  presentRuleDimensions,
  presentScorecard,
} from '../src/pages/evaluation/scorecardPresentation.js';

test('judge unavailable is neutral and preserves rule information', () => {
  const view = presentScorecard({
    rule_score: 82,
    rule_verdict: 'pass',
    judge_status: 'unavailable',
    judge_verdict: '',
    assessment_status: 'judge_unavailable',
    rule_dimensions: {},
    judge_dimensions: {},
    judge_reason: 'timeout',
  });

  assert.equal(view.status.color, 'default');
  assert.match(view.status.label, /Judge/);
  assert.equal(view.showRuleScore, true);
  assert.equal(view.showJudgeScore, false);
});

test('presentation exposes two rails without a composite total', () => {
  const view = presentDualTrackSummary({
    rule_pass_rate: 80,
    judge_pass_rate: 60,
    judge_unavailable_count: 1,
    assessment_status_counts: { dual_pass: 2 },
  });

  assert.equal(Object.hasOwn(view, 'totalScore'), false);
  assert.equal(Object.hasOwn(view, 'overallScore'), false);
  assert.equal(view.items.length, 3);
});

test('rule warning is never presented as dual pass', () => {
  const view = presentScorecard({
    rule_score: 76,
    rule_verdict: 'warning',
    judge_status: 'completed',
    judge_verdict: 'pass',
    assessment_status: 'rule_issue',
  });

  assert.match(view.status.label, /警告/);
  assert.doesNotMatch(view.status.label, /双轨通过/);
});

test('rule dimension presenter supports legacy cases and version two suite evidence', () => {
  const legacy = presentRuleDimensions({ 1: { dimensions: { completeness: { score: 100 } } } });
  const current = presentRuleDimensions({
    schema_version: '2',
    cases: { 1: { dimensions: { completeness: { score: 100 } } } },
    suite: { checkpoint_coverage: { score: 100, evidence: ['已覆盖检查点：登录'] } },
  });

  assert.equal(legacy.cases.length, 1);
  assert.equal(legacy.cases[0][0], '1');
  assert.deepEqual(legacy.suite, []);
  assert.equal(current.schemaVersion, '2');
  assert.equal(current.suite[0][0], 'checkpoint_coverage');
});
