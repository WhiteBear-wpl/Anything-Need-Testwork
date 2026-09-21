from fastapi import APIRouter

from app.models.schemas import ExecutionRequest, ExecutionResponse, RunSummary

router = APIRouter()


@router.get('/execute/summary')
def get_execute_summary() -> RunSummary:
    return RunSummary(
        total_steps=12,
        completed_steps=8,
        failed_steps=1,
        status='running',
        current_task='API创建用户 → UI登录验证',
        logs=[
            {'id': 1, 'step': 'Step 1', 'status': 'success', 'message': '打开目标页面成功', 'timestamp': '12:41:10'},
            {'id': 2, 'step': 'Step 2', 'status': 'running', 'message': '正在输入账号和密码', 'timestamp': '12:41:15'},
            {'id': 3, 'step': 'Step 3', 'status': 'warning', 'message': '发现登录按钮在移动端被遮挡', 'timestamp': '12:41:22'},
            {'id': 4, 'step': 'Step 4', 'status': 'error', 'message': '断言失败：未出现成功提示文案', 'timestamp': '12:41:30'},
        ],
    )


@router.post('/execute', response_model=ExecutionResponse)
def execute_case(request: ExecutionRequest) -> ExecutionResponse:
    return ExecutionResponse(
        run_id='run-20260921-001',
        status='queued',
        message=f'已接收 {len(request.case_ids)} 个用例，环境={request.environment}, 浏览器={request.browser}',
    )
