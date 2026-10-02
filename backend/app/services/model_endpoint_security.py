"""模型接口地址白名单，避免用户配置被用于访问服务器内网。"""

from urllib.parse import urlsplit

from app.config import settings


DEFAULT_ALLOWED_HOSTS = {
    "api.deepseek.com",
    "open.bigmodel.cn",
    "dashscope.aliyuncs.com",
    "api.moonshot.cn",
    "ark.cn-beijing.volces.com",
    "api.hunyuan.cloud.tencent.com",
    "qianfan.baidubce.com",
    "spark-api-open.xf-yun.com",
    "api.minimax.chat",
    "api.minimaxi.com",
    "api.stepfun.com",
    "api.lingyiwanwu.com",
    "api.baichuan-ai.com",
    "api.siliconflow.cn",
    "openrouter.ai",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.x.ai",
    "api.groq.com",
    "api.mistral.ai",
    "api.jina.ai",
}


class ModelEndpointError(RuntimeError):
    pass


def _allowed_hosts() -> set[str]:
    extra = {
        host.strip().lower().rstrip(".")
        for host in settings.model_api_extra_hosts.split(",")
        if host.strip()
    }
    return DEFAULT_ALLOWED_HOSTS | extra


def validate_model_base_url(value: str) -> str:
    """只允许管理员预先认可的 HTTPS 模型域名。空值用于评测模型整体回退。"""
    url = (value or "").strip().rstrip("/")
    if not url:
        return ""

    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ModelEndpointError("模型 API 地址格式不正确") from exc

    if parsed.scheme.lower() != "https":
        raise ModelEndpointError("模型 API 地址必须使用 HTTPS")
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelEndpointError("模型 API 地址格式不正确")
    if port not in (None, 443):
        raise ModelEndpointError("模型 API 地址仅允许使用 HTTPS 443 端口")
    if host not in _allowed_hosts():
        raise ModelEndpointError(
            "该模型 API 域名未被服务器允许，请使用页面预设服务商或联系管理员放行"
        )
    return url
