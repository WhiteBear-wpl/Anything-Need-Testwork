from __future__ import annotations


class RCAService:
    def diagnose(self, failure: dict[str, object]) -> dict[str, object]:
        return {
            'title': '登录失败：错误提示未出现',
            'level': 'P0',
            'reason': '前端没有正确处理错误状态，导致错误提示未展示。',
            'suggestion': '在错误分支补充用户提示，并确认网络状态码与页面细节一致。',
            'evidence': failure.get('evidence', ['接口返回 401']),
        }
