from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api import agent, agent_runs, auth, evaluations, generations, knowledge, projects, requirements, settings as settings_api, skills, test_tasks, testcases, wiki, skeleton
from app.config import settings
from app.database import init_db
from app.services.llm import LLMCallError


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.debug:
        weak_passwords = {"", "nini123456", "admin", "password", "123456"}
        if settings.auth_password in weak_passwords or len(settings.auth_password) < 16:
            raise RuntimeError("生产环境必须通过 AUTH_PASSWORD 配置至少 16 位的非默认密码")
    init_db()
    from datetime import datetime
    from app.agent_runtime.repository import AgentRunRepository
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        AgentRunRepository(db).reconcile_stale_inline(datetime.now())
    finally:
        db.close()
    yield


app = FastAPI(
    title="WhiteBear-Test",
    description="AI 接口自动化测试工作台",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

@app.exception_handler(LLMCallError)
async def llm_error_handler(request: Request, exc: LLMCallError):
    """LLM/Embedding 调用失败（Key 过期、限流、网络等）统一返回中文提示，前端直接展示 detail。"""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


class ApiAuthMiddleware(BaseHTTPMiddleware):
    """保护除登录与健康检查外的全部业务 API。"""

    public_paths = {"/api/auth/login", "/api/auth/register", "/api/health"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if request.method == "OPTIONS" or not path.startswith("/api/") or path in self.public_paths:
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        session = auth.get_session(token) if scheme.lower() == "bearer" and token else None
        if session is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "登录已失效，请重新登录"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.auth_token = token
        request.state.auth_session = session
        return await call_next(request)


# 先注册鉴权，再注册 CORS，使跨域响应（包括 401）也带正确的 CORS 头。
app.add_middleware(ApiAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(requirements.router, prefix="/api")
app.include_router(generations.router, prefix="/api")
app.include_router(testcases.router, prefix="/api")
app.include_router(testcases.project_router, prefix="/api")
app.include_router(test_tasks.router, prefix="/api")
app.include_router(evaluations.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(agent_runs.router, prefix="/api")
app.include_router(wiki.router, prefix="/api")
app.include_router(skeleton.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
