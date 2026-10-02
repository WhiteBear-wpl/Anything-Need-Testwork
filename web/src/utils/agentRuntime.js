const STATUS = {
  queued: { color: 'default', label: '排队中', terminal: false },
  running: { color: 'processing', label: '运行中', terminal: false },
  waiting_human: { color: 'orange', label: '等待确认', terminal: false },
  completed: { color: 'success', label: '已完成', terminal: true },
  failed: { color: 'error', label: '系统失败', terminal: true },
  cancelled: { color: 'warning', label: '已取消', terminal: true },
  budget_exhausted: { color: 'gold', label: '预算已用尽', terminal: true },
  interrupted: { color: 'volcano', label: '服务中断', terminal: true },
};

export function runStatusPresentation(status, stopReason = '') {
  return STATUS[status] || {
    color: 'default',
    label: stopReason || status || '未知',
    terminal: false,
  };
}

function upsertChild(children, payload, status = null) {
  const runId = payload.child_run_id ?? payload.agent_run_id;
  if (!runId) return children;
  const existing = children.find(child => child.runId === runId);
  const next = {
    runId,
    taskId: payload.task_id ?? payload.generation_task_id ?? existing?.taskId ?? null,
    kind: payload.run_kind || existing?.kind || 'generation',
    status: status || payload.status || existing?.status || 'queued',
  };
  return existing
    ? children.map(child => (child.runId === runId ? { ...child, ...next } : child))
    : [...children, next];
}

export function restoreRuntimeChildren(message = {}, children = []) {
  return {
    ...message,
    childRuns: children.reduce((current, child) => upsertChild(current, {
      child_run_id: child.id,
      generation_task_id: child.generation_task_id,
      run_kind: child.run_kind,
      status: child.status,
    }), message.childRuns || []),
  };
}

export function restoreThreadRunChildren(messages = [], groups = []) {
  const restored = messages.map(message => ({ ...message }));
  groups.forEach(({ run, children }) => {
    if (!run?.message_id || !children?.length) return;
    const userIndex = restored.findIndex(
      message => message.role === 'user' && message.id === run.message_id,
    );
    if (userIndex < 0) return;
    const assistantIndex = restored.findIndex(
      (message, index) => index > userIndex && message.role === 'assistant',
    );
    if (assistantIndex < 0) return;
    const nextUserIndex = restored.findIndex(
      (message, index) => index > userIndex && message.role === 'user',
    );
    if (nextUserIndex >= 0 && assistantIndex > nextUserIndex) return;
    restored[assistantIndex] = restoreRuntimeChildren({
      ...restored[assistantIndex],
      runId: run.id,
      runStatus: run.status,
    }, children);
  });
  return restored;
}

export function reduceRuntimeEvent(message = {}, event = {}) {
  const sequence = Number(event.sequence || 0);
  if (sequence && sequence <= Number(message.lastSequence || 0)) return message;
  const payload = event.payload || {};
  const type = event.event_type || event.type || '';
  const next = {
    ...message,
    lastSequence: sequence || message.lastSequence || 0,
  };

  if (type === 'assistant_output_delta') {
    next.content = `${message.content || ''}${payload.content || ''}`;
  } else if (type === 'tool_call_started') {
    next.activity = `正在执行 ${payload.name || '工具'}…`;
    next.toolCalls = [...(message.toolCalls || []), payload.name].filter(Boolean);
  } else if (type === 'tool_call_completed') {
    next.activity = '思考中…';
    if (payload.task_id) next.taskId = payload.task_id;
    if (payload.agent_run_id) {
      next.childRuns = upsertChild(message.childRuns || [], {
        child_run_id: payload.agent_run_id,
        task_id: payload.task_id,
      });
    }
  } else if (type === 'approval_required') {
    next.streaming = false;
    next.activity = '';
    next.approval = payload;
  } else if (type === 'assistant_completed' || type === 'run_completed') {
    next.streaming = false;
    next.activity = '';
    next.approval = null;
    next.runStatus = 'completed';
  } else if (type === 'assistant_failed' || type === 'run_failed') {
    if (['budget_exhausted', 'cancelled', 'interrupted'].includes(message.runStatus)) {
      return next;
    }
    next.streaming = false;
    next.activity = '';
    next.error = payload.message || '本轮运行失败';
    next.runStatus = 'failed';
  } else if (type === 'budget_warning') {
    const percent = payload.percent ?? payload.used_percent ?? '';
    next.runtimeNotice = `本轮运行预算已使用 ${percent}%，将保留已完成结果。`;
  } else if (type === 'run_budget_exhausted' || type === 'budget_exhausted') {
    next.streaming = false;
    next.activity = '';
    next.runStatus = 'budget_exhausted';
    next.runtimeNotice = '本轮预算已用尽，已保留完成内容；后台生成可从检查点续跑。';
  } else if (type === 'run_interrupted' || type === 'interrupted') {
    next.streaming = false;
    next.activity = '';
    next.runStatus = 'interrupted';
    next.runtimeNotice = '服务中断了本轮回答，已输出内容已保留。';
  } else if (type === 'run_cancelled') {
    next.streaming = false;
    next.activity = '';
    next.runStatus = 'cancelled';
  } else if (type === 'child_run_created') {
    next.childRuns = upsertChild(message.childRuns || [], payload, 'queued');
  } else if (type.startsWith('child_run_')) {
    next.childRuns = upsertChild(
      message.childRuns || [],
      payload,
      type.slice('child_run_'.length),
    );
  }
  return next;
}
