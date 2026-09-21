from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_cases_list() -> None:
    response = client.get('/api/v1/cases')
    assert response.status_code == 200
    data = response.json()
    assert data['total'] >= 1
    assert 'items' in data


def test_execute_summary() -> None:
    response = client.get('/api/v1/execute/summary')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'running'


def test_report_summary() -> None:
    response = client.get('/api/v1/reports/summary')
    assert response.status_code == 200
    data = response.json()
    assert data['pass_rate'] > 0
