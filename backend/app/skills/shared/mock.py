def mock_cases(feature: str, count: int, case_types: list[str], skill_name: str, smoke: bool = False) -> list[dict]:
    cases = []
    for i in range(count):
        case_type = case_types[i % len(case_types)]
        prefix = {"functional": "功能", "boundary": "边界", "exception": "异常"}.get(case_type, "")
        cases.append({
            "title": f"{prefix}-{feature}-用例{i + 1}",
            "priority": "P0" if i == 0 else "P1",
            "case_type": case_type,
            # quick 模式全部为冒烟；完整模式仅首条（P0 正常流程）为冒烟
            "is_smoke": True if smoke else (i == 0),
            "precondition": f"用户已进入{feature}相关页面",
            "steps": ["执行相关操作", "观察系统响应"],
            "expected_result": "系统按预期响应",
            "skill_name": skill_name,
        })
    return cases


MOCK_REQUIREMENT_ITEMS = [
    {
        "module": "用户登录",
        "feature": "账号密码登录",
        "description": "用户使用账号和密码登录系统",
        "acceptance_criteria": "正确账号密码可登录\n错误密码提示失败\n空账号或密码不可提交",
        "constraints": "密码长度 6-20 位",
        "priority": "P0",
    },
    {
        "module": "用户登录",
        "feature": "手机号验证码登录",
        "description": "用户使用手机号和短信验证码登录",
        "acceptance_criteria": "正确验证码可登录\n验证码 60 秒有效\n错误 5 次锁定 30 分钟",
        "constraints": "验证码 6 位数字",
        "priority": "P1",
    },
]
