"""Build benchmark chunks with the same Markdown splitter as production ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.knowledge_service import chunk_markdown


@dataclass(frozen=True)
class CorpusChunk:
    chunk_id: str
    document: str
    heading: str
    content: str


def build_corpus(knowledge_dir: Path) -> list[CorpusChunk]:
    """Read the fixed benchmark sources and assign IDs after production splitting."""
    chunks: list[CorpusChunk] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        for index, block in enumerate(
            chunk_markdown(path.read_text(encoding="utf-8")), start=1
        ):
            chunks.append(
                CorpusChunk(
                    chunk_id=f"{path.stem}#{index:02d}",
                    document=path.stem,
                    heading=block["heading"],
                    content=block["content"],
                )
            )
    return chunks
