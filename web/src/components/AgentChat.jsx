import {
  CheckCircleOutlined, CloseCircleOutlined, FileMarkdownOutlined, FileWordOutlined,
  FileTextOutlined, LoadingOutlined, PaperClipOutlined, RightOutlined, SendOutlined, ToolOutlined,
} from '@ant-design/icons';
import { App, Button, Empty, Input, Progress, Spin, Tag, Upload } from 'antd';
import {
  forwardRef, useEffect, useImperativeHandle, useRef, useState,
} from 'react';
import { Link } from 'react-router-dom';
import {
  cancelAgentRun, clearAgentMessages, getAgentMessages, getAgentRun, getAgentRunChildren,
  getAgentRunEvents, getAgentRuns,
  getGeneration, streamAgentChat, streamAgentRun, uploadRequirementFile,
  getAgentState, resumeAgentChat,
} from '../services/api';
import {
  reduceRuntimeEvent, restoreRuntimeChildren, restoreThreadRunChildren, runStatusPresentation,
} from '../utils/agentRuntime';

const TOOL_LABEL = {
  search_knowledge: '检索知识库',
  list_testcases: '查询用例列表',
  get_testcase_detail: '查询用例详情',
  get_coverage_summary: '统计需求覆盖',
  get_test_task_stats: '查询测试进度',
  list_defects: '查询缺陷记录',
  parse_requirement_document: '解析需求文档',
  confirm_features: '确认功能点',
  start_generation: '启动用例生成',
  get_generation_status: '查询生成进度',
  review_generated_drafts: '评审生成用例',
};

const toolLabel = (name) => TOOL_LABEL[name] || name;

const TASK_RUNNING_STATUSES = ['pending', 'structuring', 'confirmed', 'generating', 'reviewing'];

/** 生成任务进度卡片：轮询任务状态，完成后展示草稿数并链接到评审页。 */
function GenerationTaskCard({ projectId, taskId, runId }) {
  const [task, setTask] = useState(null);
  const [run, setRun] = useState(null);

  useEffect(() => {
    let stopped = false;
    let timer = null;
    const poll = async () => {
      try {
        const [data, runData] = await Promise.all([
          taskId ? getGeneration(projectId, taskId) : Promise.resolve(null),
          runId ? getAgentRun(projectId, runId) : Promise.resolve(null),
        ]);
        if (stopped) return;
        setTask(data);
        setRun(runData);
        if (TASK_RUNNING_STATUSES.includes(data?.status) || ['queued', 'running', 'waiting_human'].includes(runData?.status)) {
          timer = setTimeout(poll, 1500);
        }
      } catch {
        // 任务查询失败（如已删除），停止轮询
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [projectId, taskId, runId]);

  const running = task && TASK_RUNNING_STATUSES.includes(task.status);
  const completed = task?.status === 'completed';
  const failed = task?.status === 'failed';
  const runView = run ? runStatusPresentation(run.status, run.stop_reason) : null;
  return (
    <div
      style={{
        marginTop: 6,
        padding: '10px 12px',
        border: '1px solid #e5e7eb',
        borderRadius: 10,
        background: '#fff',
        fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: running ? 6 : 0 }}>
        {completed && <CheckCircleOutlined style={{ color: '#16a34a' }} />}
        {failed && <CloseCircleOutlined style={{ color: '#dc2626' }} />}
        {running && <LoadingOutlined style={{ color: '#4f46e5' }} />}
        <span style={{ fontWeight: 600 }}>生成任务 #{taskId || '-'}</span>
        {runView && <Tag color={runView.color}>{runView.label}</Tag>}
        <span style={{ color: '#888', flex: 1 }}>
          {!task && '加载中…'}
          {running && (task.stage || '排队中…')}
          {completed && `已生成 ${task.drafts?.length ?? 0} 条候选用例`}
          {failed && (task.error_message || '任务失败')}
        </span>
        {taskId && (
          <Link to={`/projects/${projectId}/generate?task=${taskId}`} style={{ whiteSpace: 'nowrap' }}>
            去评审 <RightOutlined style={{ fontSize: 10 }} />
          </Link>
        )}
        {runId && ['queued', 'running', 'waiting_human'].includes(run?.status) && (
          <Button size="small" danger onClick={() => cancelAgentRun(projectId, runId)}>
            取消后台任务
          </Button>
        )}
      </div>
      {running && <Progress percent={task.progress ?? 0} size="small" showInfo={false} />}
    </div>
  );
}

const SOURCE_TYPE_LABEL = { markdown: 'Markdown', docx: 'Word', text: '文本' };

const attachmentIcon = (sourceType) => {
  if (sourceType === 'docx') return <FileWordOutlined style={{ fontSize: 22 }} />;
  if (sourceType === 'markdown') return <FileMarkdownOutlined style={{ fontSize: 22 }} />;
  return <FileTextOutlined style={{ fontSize: 22 }} />;
};

/** 消息内的文件引用卡片。用户侧气泡为主题色深底，用半透明白底适配。 */
function AttachmentCard({ attachment, onDark }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 12px',
        borderRadius: 8,
        marginBottom: 8,
        maxWidth: 280,
        background: onDark ? 'rgba(255, 255, 255, 0.16)' : '#fff',
        border: onDark ? '1px solid rgba(255, 255, 255, 0.25)' : '1px solid #e5e7eb',
        color: onDark ? '#fff' : 'inherit',
      }}
    >
      {attachmentIcon(attachment.source_type)}
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontWeight: 600,
            fontSize: 13,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
          title={attachment.title}
        >
          {attachment.title}
        </div>
        <div style={{ fontSize: 12, opacity: 0.75 }}>
          需求文档{SOURCE_TYPE_LABEL[attachment.source_type] ? ` · ${SOURCE_TYPE_LABEL[attachment.source_type]}` : ''}
        </div>
      </div>
    </div>
  );
}

const approvalActionText = (action) => {
  if (action.name === 'confirm_features') {
    return `确认需求文档 #${action.args?.document_id ?? '-' } 的功能点`;
  }
  if (action.name === 'start_generation') {
    const strategy = action.args?.strategy === 'quick' ? '快速冒烟' : '完整用例';
    return `启动 ${strategy} 生成`;
  }
  if (action.name === 'review_generated_drafts') {
    const verb = action.args?.action === 'reject' ? '驳回' : '采纳';
    return `${verb}生成任务 #${action.args?.task_id ?? '-'} 的候选用例`;
  }
  return toolLabel(action.name);
};

function ApprovalCard({ approval, loading, onDecision }) {
  return (
    <div
      style={{
        marginTop: 8,
        padding: '12px 14px',
        border: '1px solid #e5e7eb',
        borderRadius: 10,
        background: '#fff',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{approval.title}</div>
      <div style={{ color: '#666', fontSize: 12, lineHeight: 1.6 }}>
        {approval.description}
      </div>
      <div style={{ margin: '8px 0', color: '#333', fontSize: 12 }}>
        {(approval.actions || []).map((action, index) => (
          <div key={`${action.name}-${index}`}>· {approvalActionText(action)}</div>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button size="small" disabled={loading} onClick={() => onDecision(false)}>
          取消
        </Button>
        <Button
          size="small"
          type="primary"
          danger={approval.danger}
          loading={loading}
          onClick={() => onDecision(true)}
        >
          确认执行
        </Button>
      </div>
    </div>
  );
}

function MessageBubble({
  msg, projectId, onApproval, approvalLoading, onCancelRun,
}) {
  const isUser = msg.role === 'user';
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
      <div style={{ maxWidth: '85%' }}>
        {!isUser && msg.toolCalls?.length > 0 && (
          <div style={{ marginBottom: 4 }}>
            {msg.toolCalls.map((name, i) => (
              <Tag key={`${name}-${i}`} icon={<ToolOutlined />} style={{ marginBottom: 2 }}>
                {toolLabel(name)}
              </Tag>
            ))}
          </div>
        )}
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 10,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontSize: 13,
            lineHeight: 1.7,
            background: isUser ? 'var(--ant-color-primary, #4f46e5)' : '#f5f5f7',
            color: isUser ? '#fff' : 'inherit',
          }}
        >
          {msg.attachment && <AttachmentCard attachment={msg.attachment} onDark={isUser} />}
          {msg.content || (msg.streaming || msg.approval ? '' : '（无回答内容）')}
          {msg.streaming && (
            <span style={{ color: '#888', fontSize: 12 }}>
              <LoadingOutlined style={{ marginRight: 6 }} />
              {msg.activity || '思考中…'}
            </span>
          )}
        </div>
        {!isUser && msg.runtimeNotice && (
          <div style={{ color: '#b45309', fontSize: 12, marginTop: 4 }}>{msg.runtimeNotice}</div>
        )}
        {!isUser && msg.approval && (
          <ApprovalCard
            approval={msg.approval}
            loading={approvalLoading}
            onDecision={onApproval}
          />
        )}
        {!isUser && msg.taskId && !(msg.childRuns || []).length && (
          <GenerationTaskCard projectId={projectId} taskId={msg.taskId} />
        )}
        {!isUser && (msg.childRuns || []).map(child => (
          <GenerationTaskCard
            key={child.runId}
            projectId={projectId}
            taskId={child.taskId}
            runId={child.runId}
          />
        ))}
        {!isUser && msg.runId && (msg.streaming || msg.approval) && (
          <Button size="small" danger style={{ marginTop: 6 }} onClick={() => onCancelRun(msg.runId)}>
            停止本轮回答
          </Button>
        )}
        {msg.error && (
          <div style={{ color: '#dc2626', fontSize: 12, marginTop: 4 }}>{msg.error}</div>
        )}
      </div>
    </div>
  );
}

/**
 * 测试助手对话核心：消息列表 + 输入框 + SSE 流式渲染。
 * 悬浮抽屉与全局页面共用；active 为 false 时暂不加载历史（如抽屉未打开）。
 * ref 暴露 clear()；onMetaChange 上报 { hasMessages, streaming } 供外部按钮联动。
 */
const AgentChat = forwardRef(function AgentChat({
  projectId, active = true, onMetaChange, style,
}, ref) {
  const { message, modal } = App.useApp();
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pendingDoc, setPendingDoc] = useState(null); // 已上传待发送的需求文档附件 {id, title}
  const listRef = useRef(null);
  const abortRef = useRef(null);
  const hasPendingApproval = messages.some((item) => item.approval);

  // 切换项目时重置状态并中断在途请求，避免组件复用导致短暂展示上一个项目的对话
  useEffect(() => {
    abortRef.current?.abort();
    setLoaded(false);
    setMessages([]);
    setInput('');
    setStreaming(false);
    setApprovalLoading(false);
    setPendingDoc(null);
  }, [projectId]);

  useEffect(() => {
    if (!active || loaded || !projectId) return;
    (async () => {
      setLoading(true);
      try {
        const [rows, state] = await Promise.all([
          getAgentMessages(projectId),
          getAgentState(projectId),
        ]);
        const loadedMessages = rows.map((r) => ({
          id: r.id,
          role: r.role,
          content: r.content,
          toolCalls: (r.tool_calls || []).map((t) => t.name),
          taskId: (r.tool_calls || []).find((t) => t.task_id)?.task_id || null,
          attachment: r.attachment || null,
        }));
        const recentRuns = await getAgentRuns(projectId, state.thread_id, 20);
        const chatRuns = recentRuns.filter(run => run.run_kind === 'chat');
        const runChildren = await Promise.all(chatRuns.map(async run => ({
          run,
          children: await getAgentRunChildren(projectId, run.id),
        })));
        const restoredMessages = restoreThreadRunChildren(loadedMessages, runChildren);
        loadedMessages.splice(0, loadedMessages.length, ...restoredMessages);
        const latest = chatRuns[0];
        const children = runChildren.find(group => group.run.id === latest?.id)?.children || [];
        let reconnect = null;
        if (latest && ['queued', 'running', 'waiting_human'].includes(latest.status)) {
          const runtimeEvents = await getAgentRunEvents(projectId, latest.id, 0);
          let runtimeMessage = {
            role: 'assistant',
            content: '',
            toolCalls: [],
            childRuns: [],
            runId: latest.id,
            streaming: latest.status !== 'waiting_human',
            activity: latest.status === 'queued' ? '排队中…' : '思考中…',
          };
          runtimeEvents.forEach((event) => {
            let payload = {};
            try { payload = JSON.parse(event.payload_summary || '{}'); } catch { /* ignore */ }
            runtimeMessage = reduceRuntimeEvent(runtimeMessage, { ...event, payload });
          });
          runtimeMessage = restoreRuntimeChildren(runtimeMessage, children);
          if (state.pending_approval) runtimeMessage.approval = state.pending_approval;
          loadedMessages.push(runtimeMessage);
          if (latest.status !== 'waiting_human') {
            reconnect = { runId: latest.id, afterSequence: runtimeMessage.lastSequence || 0 };
          }
        } else if (state.pending_approval) {
          loadedMessages.push({
            role: 'assistant', content: '', toolCalls: [], approval: state.pending_approval,
          });
        }
        setMessages(loadedMessages);
        setLoaded(true);
        if (reconnect) {
          setStreaming(true);
          const handle = streamAgentRun(
            projectId,
            reconnect.runId,
            handleAgentEvent,
            reconnect.afterSequence,
          );
          abortRef.current = handle;
          handle.promise
            .catch((err) => {
              if (err.name !== 'AbortError') message.error(err.message || '恢复运行订阅失败');
            })
            .finally(() => setStreaming(false));
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [active, loaded, projectId]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => {
    onMetaChange?.({ hasMessages: messages.length > 0, streaming });
  }, [messages.length, streaming]); // eslint-disable-line react-hooks/exhaustive-deps

  // 组件卸载时中断进行中的流式请求
  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = (patch) => {
    setMessages((prev) => {
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], ...(
        typeof patch === 'function' ? patch(next[next.length - 1]) : patch
      ) };
      return next;
    });
  };

  const handleAgentEvent = (event) => {
    if (event.event_type) {
      patchLast((current) => reduceRuntimeEvent(
        { ...current, runId: event.run_id || current.runId },
        event,
      ));
      if ([
        'assistant_completed', 'assistant_failed', 'run_completed', 'run_failed',
        'run_cancelled', 'run_budget_exhausted', 'run_interrupted', 'approval_required',
      ].includes(event.event_type)) setStreaming(false);
    } else if (event.type === 'tool_start') {
      patchLast((m) => ({
        activity: `正在${toolLabel(event.name)}…`,
        toolCalls: [...(m.toolCalls || []), event.name],
      }));
    } else if (event.type === 'tool_end') {
      const patch = { activity: '思考中…' };
      if (event.name === 'start_generation' && event.output) {
        try {
          const out = JSON.parse(event.output);
          if (out.task_id) patch.taskId = out.task_id;
        } catch { /* 输出不是 JSON 时忽略 */ }
      }
      patchLast(patch);
    } else if (event.type === 'token') {
      patchLast((m) => ({ content: (m.content || '') + event.content }));
    } else if (event.type === 'approval_required') {
      patchLast({
        streaming: false,
        activity: '',
        approval: event.approval,
      });
    } else if (event.type === 'done') {
      patchLast({ streaming: false, activity: '', approval: null });
    } else if (event.type === 'error') {
      patchLast({ streaming: false, activity: '', error: event.message });
    }
  };

  const cancelParentRun = async (runId) => {
    try {
      await cancelAgentRun(projectId, runId);
      patchLast({
        streaming: false,
        approval: null,
        runStatus: 'cancelled',
        runtimeNotice: '本轮回答已停止，已完成内容已保留。',
      });
      setStreaming(false);
    } catch (err) {
      message.error(err?.response?.data?.detail || '停止本轮回答失败');
    }
  };

  const sendMessage = async (question, attachment = null) => {
    if (!question || streaming || hasPendingApproval || !projectId) return;
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question, attachment },
      { role: 'assistant', content: '', toolCalls: [], streaming: true, activity: '思考中…' },
    ]);

    const handle = streamAgentChat(
      projectId,
      question,
      handleAgentEvent,
      attachment?.document_id ?? null,
    );
    abortRef.current = handle;
    try {
      await handle.promise;
    } catch (err) {
      if (err.name !== 'AbortError') {
        patchLast({ streaming: false, activity: '', error: err.message || '请求失败，请稍后重试' });
      }
    } finally {
      setStreaming(false);
      patchLast((m) => (m.streaming ? { streaming: false, activity: '' } : {}));
    }
  };

  const decideApproval = async (approved) => {
    const approval = messages[messages.length - 1]?.approval;
    if (!approval?.checkpoint_thread_id || streaming || approvalLoading) return;
    setStreaming(true);
    setApprovalLoading(true);
    patchLast({ streaming: true, activity: approved ? '正在恢复并执行…' : '正在取消…', error: '' });
    const handle = resumeAgentChat(
      projectId,
      approval.checkpoint_thread_id,
      approved,
      handleAgentEvent,
      messages[messages.length - 1]?.lastSequence || 0,
    );
    abortRef.current = handle;
    try {
      await handle.promise;
    } catch (err) {
      if (err.name !== 'AbortError') {
        patchLast({
          streaming: false,
          activity: '',
          error: err.message || '确认操作失败，请稍后重试',
        });
      }
    } finally {
      setApprovalLoading(false);
      setStreaming(false);
      patchLast((m) => (m.streaming ? { streaming: false, activity: '' } : {}));
    }
  };

  const send = () => {
    const question = input.trim();
    if (!question && !pendingDoc) return;
    setInput('');
    if (pendingDoc) {
      const attachment = pendingDoc;
      setPendingDoc(null);
      // 附件消息：用户没写内容时用默认解析请求
      sendMessage(question || '请解析这份需求文档，给出功能点清单。', attachment);
    } else {
      sendMessage(question);
    }
  };

  // 上传只挂附件，不自动发消息；说什么、何时发由用户决定
  const attachDocument = async (file) => {
    if (streaming || hasPendingApproval || uploading || !projectId) return false;
    setUploading(true);
    try {
      const doc = await uploadRequirementFile(projectId, file);
      setPendingDoc({ document_id: doc.id, title: doc.title, source_type: doc.source_type });
    } catch (err) {
      message.error(err.response?.data?.detail || err.message || '文档上传失败');
    } finally {
      setUploading(false);
    }
    return false; // 阻止 antd Upload 默认上传行为
  };

  const clear = () => {
    modal.confirm({
      title: '清空对话记录？',
      content: '将删除该项目下测试助手的全部历史对话，不影响其他数据。',
      okText: '清空',
      okButtonProps: { danger: true },
      onOk: async () => {
        await clearAgentMessages(projectId);
        setMessages([]);
        message.success('已清空对话');
      },
    });
  };

  useImperativeHandle(ref, () => ({ clear }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1, ...style }}>
      <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '16px 16px 8px' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : messages.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={(
              <span style={{ fontSize: 13, color: '#888' }}>
                可以问我项目里的用例、需求覆盖、测试进度、缺陷或业务规则，
                <br />
                例如「这轮测试通过率怎么样？」「退款规则是什么？」
                <br />
                也可以直接上传需求文档（.md / .docx），确认功能点后一键生成用例。
              </span>
            )}
            style={{ marginTop: 60 }}
          />
        ) : (
          messages.map((m, i) => (
            <MessageBubble
              key={i}
              msg={m}
              projectId={projectId}
              onApproval={decideApproval}
              approvalLoading={approvalLoading}
              onCancelRun={cancelParentRun}
            />
          ))
        )}
      </div>
      {pendingDoc && (
        <div style={{ padding: '8px 12px 0', borderTop: '1px solid #f0f0f0' }}>
          <Tag
            icon={<PaperClipOutlined />}
            closable
            onClose={() => setPendingDoc(null)}
            style={{ maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}
          >
            {pendingDoc.title}
          </Tag>
          <span style={{ fontSize: 12, color: '#888' }}>输入想说的话后发送，或直接发送让我解析</span>
        </div>
      )}
      <div style={{ padding: 12, borderTop: pendingDoc ? 'none' : '1px solid #f0f0f0', display: 'flex', gap: 8 }}>
        <Upload
          accept=".md,.markdown,.docx"
          showUploadList={false}
          beforeUpload={attachDocument}
          disabled={streaming || hasPendingApproval || uploading || !projectId}
        >
          <Button
            icon={uploading ? <LoadingOutlined /> : <PaperClipOutlined />}
            disabled={streaming || hasPendingApproval || uploading || !projectId}
            title="上传需求文档（.md / .docx）作为附件，随下一条消息发送"
          />
        </Upload>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="问我项目用例、测试进度或业务规则…（Enter 发送）"
          autoSize={{ minRows: 1, maxRows: 4 }}
          maxLength={2000}
          disabled={streaming || hasPendingApproval || !projectId}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={send}
          loading={streaming}
          disabled={hasPendingApproval || (!input.trim() && !pendingDoc) || !projectId}
        />
      </div>
    </div>
  );
});

export default AgentChat;
