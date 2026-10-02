"""Fixed A/B inputs; supplemental knowledge deliberately excludes requirement prose."""

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ABSample:
    key: str
    title: str
    requirement: str
    checkpoints: list[dict]
    knowledge_path: Path


def load_samples() -> tuple[ABSample, ...]:
    return (
        ABSample(
            "requirement-import", "需求导入与功能点确认",
            "支持粘贴、上传和功能清单导入需求；解析成功后用户可编辑并确认功能点，未确认不得生成用例。上传只支持 docx、md、markdown，限制 10MB。",
            [{"text": "文件格式和大小校验", "keywords": ["docx", "10MB"]}, {"text": "未确认禁止生成", "keywords": ["未确认", "禁止"]}, {"text": "功能点编辑确认", "keywords": ["编辑", "确认"]}],
            ROOT / "knowledge" / "import-supplement.md",
        ),
        ABSample(
            "review-storage", "评审入库",
            "生成草稿可查看详情、采纳、驳回或编辑；采纳后进入用例库，完成页展示评审统计。",
            [{"text": "驳回原因和不可再采纳", "keywords": ["驳回", "原因", "不可"]}, {"text": "采纳后保留归属", "keywords": ["采纳", "模块", "归属"]}, {"text": "统计实时更新", "keywords": ["采纳率", "实时"]}],
            ROOT / "knowledge" / "review-supplement.md",
        ),
    )
