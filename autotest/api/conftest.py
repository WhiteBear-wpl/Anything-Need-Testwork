import uuid

import pytest

from api.client import ApiClient


@pytest.fixture(scope="session")
def client(api_base_url, auth_credentials) -> ApiClient:
    return ApiClient(api_base_url, *auth_credentials)


@pytest.fixture
def project(client):
    """函数级临时项目：每个用例独享，用完即删，保证数据隔离。"""
    data = client.create_project(f"AT-{uuid.uuid4().hex[:8]}", "接口自动化临时项目")
    yield data
    client.delete_project(data["id"])


@pytest.fixture
def confirmed_doc(client, project):
    """已确认功能点的需求文档（文本导入 → 结构化 → 全量确认）。"""
    return client.prepare_confirmed_document(project["id"])


@pytest.fixture
def completed_task(client, project, confirmed_doc):
    """一个已完成的快速冒烟生成任务。"""
    return client.run_generation(project["id"], confirmed_doc["id"], strategy="quick")
