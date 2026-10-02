from typing import TypedDict


class GenerationState(TypedDict, total=False):
    """用例生成 Graph 的可持久化状态；只保存 ID 和普通数据。"""

    task_id: int
    project_id: int
    document_id: int
    feature_ids: list[int]
    feature_index: int
    current_feature_id: int | None
    current_feature: dict | None

    strategy: str
    specialist_skills: list[str]
    specialist_policy: dict[str, dict]
    use_knowledge: bool
    retrieval: dict
    scope: dict | None

    retrieval_query: str
    knowledge: list[dict]
    knowledge_refs: dict[str, list[dict]]
    current_cases: list[dict]
    core_cases: list[dict]
    specialist_cases: dict[str, list[dict]]
    specialist_warnings: list[dict]

    retry_count: int
    generation_error: str
    case_writer_attempt_count: int
    retry_directive: str
    failure_decision: dict
    has_failure_candidates: bool
    duplicate_count: int
