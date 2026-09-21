from fastapi import APIRouter

from app.models.schemas import CaseListResponse, ExecutionRequest, TestCase

router = APIRouter()


@router.get('/cases', response_model=CaseListResponse)
def list_cases() -> CaseListResponse:
    items = [
        TestCase(
            id=101,
            title='登录页 - 正常登录',
            type='UI',
            owner='alice',
            status='待执行',
            priority='P0',
            duration='2.1 min',
            summary='验证登录成功后跳转到首页，并展示用户头像。',
            pass_rate=92,
        ),
        TestCase(
            id=102,
            title='用户列表 - 查询过滤',
            type='API',
            owner='bob',
            status='执行中',
            priority='P1',
            duration='1.4 min',
            summary='校验过滤参数和返回字段结构一致。',
            pass_rate=88,
        ),
        TestCase(
            id=103,
            title='订单创建 - 存量数据',
            type='DATA',
            owner='carmen',
            status='已通过',
            priority='P0',
            duration='3.2 min',
            summary='覆盖 corner cases，验证重复订单被拦截。',
            pass_rate=97,
        ),
        TestCase(
            id=104,
            title='支付校验 - 大额订单',
            type='RULE',
            owner='dora',
            status='已失败',
            priority='P1',
            duration='0.9 min',
            summary='规则输出不符合业务阈值，需人工确认。',
            pass_rate=61,
        ),
    ]
    return CaseListResponse(items=items, total=len(items))


@router.post('/cases/generate')
def generate_case(payload: dict[str, str]) -> dict[str, object]:
    return {
        'message': '用例已生成',
        'plan': [
            '打开登录页',
            '输入错误密码',
            '点击登录按钮',
            '断言提示文案',
        ],
        'prompt': payload.get('prompt', '未提供输入'),
    }
