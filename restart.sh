#!/bin/bash
# 一键杀死旧进程 + 启动后端和前端
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  AI Testcase Studio — 一键重启"
echo "=========================================="

# 1. 杀死已占用的端口进程
echo ""
echo "[1/3] 清理旧进程..."
lsof -ti tcp:8000 2>/dev/null | xargs kill -9 2>/dev/null && echo "  ✔ 后端 :8000 已停止" || echo "  ✔ 后端 :8000 无占用"
lsof -ti tcp:5173 2>/dev/null | xargs kill -9 2>/dev/null && echo "  ✔ 前端 :5173 已停止" || echo "  ✔ 前端 :5173 无占用"
sleep 1

# 2. 启动后端
echo ""
echo "[2/3] 启动后端 (uvicorn app.main:app --port 8000)..."
cd "$ROOT_DIR/backend"
# 直接用 venv 内的 python 启动（复制来的 venv 的 activate/uvicorn 脚本硬编码了旧项目路径，不可靠）
nohup venv/bin/python -m uvicorn app.main:app --reload --port 8000 > /tmp/altc-backend.log 2>&1 &
BACKEND_PID=$!
echo "  ✔ 后端已启动 (PID: $BACKEND_PID)  日志: /tmp/altc-backend.log"

# 3. 启动前端
echo ""
echo "[3/3] 启动前端 (vite dev --port 5173)..."
cd "$ROOT_DIR/web"
# stdin 重定向到 /dev/null，避免非交互环境下 Vite 因 stdin 关闭而退出
nohup npm run dev < /dev/null > /tmp/altc-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "  ✔ 前端已启动 (PID: $FRONTEND_PID)  日志: /tmp/altc-frontend.log"

echo ""
echo "=========================================="
echo "  ✅ 启动完成！"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:8000"
echo "  API 文档: http://localhost:8000/docs"
echo "=========================================="
