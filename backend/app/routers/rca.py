from fastapi import APIRouter

from app.models.schemas import DiagnosisItem

router = APIRouter()


@router.get('/rca', response_model=list[DiagnosisItem])
def get_rca() -> list[DiagnosisItem]:
    return [
        DiagnosisItem(
            id=1,
            title='登录失败：错误提示未出现',
            level='P0',
            evidence=['截图 2026-09-21 12:41:29', '接口 /api/v1/login 返回 401'],
            reason='后端状态码正常，但前端错误提示没有被渲染，可能是条件判断缺失。',
            suggestion='在 catch 分支中补充错误消息映射，并确认状态码与提示文案的一致性。',
            confirmed=True,
        ),
        DiagnosisItem(
            id=2,
            title='页面元素定位变更',
            level='P1',
            evidence=['DOM 快照比对', 'button[data-testid="submit"] 缺失'],
            reason='定位器依赖旧的 data-testid，元素已改成类名选择器。',
            suggestion='采用更稳定的语义化定位器，优先使用 role/name 或 data-testid。',
            confirmed=False,
        ),
    ]
