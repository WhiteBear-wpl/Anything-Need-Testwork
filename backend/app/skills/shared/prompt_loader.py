from pathlib import Path

from app.skills.registry import get_registry


def load_prompt(skill_dir: Path, relative_path: str) -> str:
    path = skill_dir / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_versioned_prompt(skill_name: str, skill_dir: Path, prompt_version: str) -> str:
    """Load the exact deployed Prompt version recorded in an immutable task snapshot."""
    path = get_registry().prompt_path(skill_name, prompt_version)
    if path.parent != skill_dir.resolve() and skill_dir.resolve() not in path.parents:
        # Registry already guards this boundary; keep the package contract explicit here too.
        raise FileNotFoundError(f"Prompt is outside Skill package: {path}")
    return path.read_text(encoding="utf-8").strip()
