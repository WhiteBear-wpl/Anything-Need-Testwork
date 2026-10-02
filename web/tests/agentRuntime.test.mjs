import assert from 'node:assert/strict';
import test from 'node:test';

import {
  reduceRuntimeEvent, restoreRuntimeChildren, restoreThreadRunChildren, runStatusPresentation,
} from '../src/utils/agentRuntime.js';


test('budget warning does not terminate the assistant message', () => {
  const next = reduceRuntimeEvent({ content: '', streaming: true }, {
    sequence: 4,
    event_type: 'budget_warning',
    payload: { dimension: 'tokens', percent: 80 },
  });
  assert.equal(next.streaming, true);
  assert.match(next.runtimeNotice, /80%/);
});

test('child event creates and terminal events update a durable task card', () => {
  const created = reduceRuntimeEvent({}, {
    sequence: 7,
    event_type: 'child_run_created',
    payload: { child_run_id: 12, task_id: 34, run_kind: 'generation' },
  });
  assert.deepEqual(created.childRuns, [{ runId: 12, taskId: 34, kind: 'generation', status: 'queued' }]);
  const completed = reduceRuntimeEvent(created, {
    sequence: 8,
    event_type: 'child_run_completed',
    payload: { child_run_id: 12, status: 'completed' },
  });
  assert.equal(completed.childRuns[0].status, 'completed');
  const failed = reduceRuntimeEvent(completed, {
    sequence: 9,
    event_type: 'child_run_failed',
    payload: { child_run_id: 12, status: 'failed' },
  });
  assert.equal(failed.childRuns[0].status, 'failed');
});

test('replayed sequence is idempotent', () => {
  const once = reduceRuntimeEvent({ lastSequence: 5, content: '已完成' }, {
    sequence: 5,
    event_type: 'assistant_output_delta',
    payload: { content: '重复' },
  });
  assert.equal(once.content, '已完成');
});

test('budget exhausted and interrupted preserve content with distinct copy', () => {
  const exhausted = reduceRuntimeEvent({ content: '已有内容', streaming: true }, {
    sequence: 2,
    event_type: 'run_budget_exhausted',
    payload: {},
  });
  assert.equal(exhausted.content, '已有内容');
  assert.equal(exhausted.streaming, false);
  assert.match(exhausted.runtimeNotice, /预算已用尽/);
  const interrupted = reduceRuntimeEvent({ content: '部分回答', streaming: true }, {
    sequence: 3,
    event_type: 'run_interrupted',
    payload: {},
  });
  assert.match(interrupted.runtimeNotice, /服务中断/);
});

test('run status presentation distinguishes expected budget stop from failure', () => {
  assert.deepEqual(runStatusPresentation('budget_exhausted'), {
    color: 'gold', label: '预算已用尽', terminal: true,
  });
  assert.equal(runStatusPresentation('interrupted').terminal, true);
  assert.equal(runStatusPresentation('waiting_human').terminal, false);
  assert.equal(runStatusPresentation('failed').color, 'error');
});

test('controlled terminal status cannot be overwritten by a later generic assistant failure', () => {
  const stopped = reduceRuntimeEvent({}, {
    sequence: 10,
    event_type: 'run_budget_exhausted',
    payload: {},
  });
  const replayed = reduceRuntimeEvent(stopped, {
    sequence: 11,
    event_type: 'assistant_failed',
    payload: { message: 'generic failure' },
  });
  assert.equal(replayed.runStatus, 'budget_exhausted');
  assert.equal(replayed.error, undefined);
});

test('completed parent restores active child cards from children endpoint', () => {
  const restored = restoreRuntimeChildren({}, [{
    id: 22,
    generation_task_id: 33,
    run_kind: 'generation',
    status: 'running',
  }]);
  assert.deepEqual(restored.childRuns, [{
    runId: 22, taskId: 33, kind: 'generation', status: 'running',
  }]);
});

test('older completed parent keeps its active child after a newer childless chat', () => {
  const messages = [
    { id: 1, role: 'user', content: '启动生成' },
    { id: 2, role: 'assistant', content: '已启动' },
    { id: 3, role: 'user', content: '现在几点' },
    { id: 4, role: 'assistant', content: '稍后回答' },
  ];
  const restored = restoreThreadRunChildren(messages, [{
    run: { id: 10, message_id: 1, status: 'completed' },
    children: [{
      id: 20, generation_task_id: 30, run_kind: 'generation', status: 'running',
    }],
  }, {
    run: { id: 11, message_id: 3, status: 'completed' },
    children: [],
  }]);
  assert.equal(restored[1].childRuns[0].runId, 20);
  assert.equal(restored[1].runId, 10);
  assert.equal(restored[3].childRuns, undefined);
});
