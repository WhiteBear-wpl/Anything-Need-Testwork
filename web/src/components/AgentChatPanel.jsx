import { ClearOutlined, RobotOutlined } from '@ant-design/icons';
import { Button, Drawer, Tooltip } from 'antd';
import { useRef, useState } from 'react';
import AgentChat from './AgentChat';

const FAB_POS_KEY = 'aitc_agent_fab_pos';
const FAB_SIZE = 48;
const FAB_MARGIN = 8;
const DRAG_THRESHOLD = 5;

const clampPos = ({ right, bottom }) => ({
  right: Math.min(Math.max(right, FAB_MARGIN), Math.max(window.innerWidth - FAB_SIZE - FAB_MARGIN, FAB_MARGIN)),
  bottom: Math.min(Math.max(bottom, FAB_MARGIN), Math.max(window.innerHeight - FAB_SIZE - FAB_MARGIN, FAB_MARGIN)),
});

const loadPos = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(FAB_POS_KEY));
    if (Number.isFinite(saved?.right) && Number.isFinite(saved?.bottom)) return clampPos(saved);
  } catch { /* 无效存储值走默认位置 */ }
  return { right: 24, bottom: 24 };
};

export default function AgentChatPanel({ projectId }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(loadPos);
  const [meta, setMeta] = useState({ hasMessages: false, streaming: false });
  const chatRef = useRef(null);
  const draggedRef = useRef(false);

  const handlePointerDown = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    const start = {
      x: e.clientX, y: e.clientY, right: pos.right, bottom: pos.bottom, moved: false,
    };
    let latest = pos;

    const onMove = (ev) => {
      const dx = ev.clientX - start.x;
      const dy = ev.clientY - start.y;
      if (!start.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      start.moved = true;
      latest = clampPos({ right: start.right - dx, bottom: start.bottom - dy });
      setPos(latest);
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      draggedRef.current = start.moved;
      if (start.moved) {
        try {
          localStorage.setItem(FAB_POS_KEY, JSON.stringify(latest));
        } catch { /* 存储失败不影响本次位置 */ }
      }
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const handleClick = () => {
    // 拖动结束后触发的 click 不打开抽屉
    if (draggedRef.current) {
      draggedRef.current = false;
      return;
    }
    setOpen(true);
  };

  return (
    <>
      <Tooltip title="AI小助手（可拖动）" placement="left">
        <button
          type="button"
          className="agent-fab"
          aria-label="打开AI小助手"
          style={{ right: pos.right, bottom: pos.bottom }}
          onPointerDown={handlePointerDown}
          onClick={handleClick}
        >
          AI
        </button>
      </Tooltip>
      <Drawer
        title={(
          <span>
            <RobotOutlined style={{ marginRight: 8 }} />
            测试助手
          </span>
        )}
        placement="right"
        width={460}
        open={open}
        onClose={() => setOpen(false)}
        extra={(
          <Button
            type="text"
            size="small"
            icon={<ClearOutlined />}
            disabled={!meta.hasMessages || meta.streaming}
            onClick={() => chatRef.current?.clear()}
          >
            清空
          </Button>
        )}
        styles={{ body: { display: 'flex', flexDirection: 'column', padding: 0 } }}
      >
        <AgentChat ref={chatRef} projectId={projectId} active={open} onMetaChange={setMeta} />
      </Drawer>
    </>
  );
}
