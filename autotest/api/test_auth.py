"""服务端鉴权回归测试。"""

import requests


def test_health_is_public(api_base_url):
    response = requests.get(f"{api_base_url}/health", timeout=10)
    assert response.status_code == 200


def test_business_api_rejects_missing_or_invalid_token(api_base_url):
    missing = requests.get(f"{api_base_url}/projects", timeout=10)
    invalid = requests.get(
        f"{api_base_url}/projects",
        headers={"Authorization": "Bearer invalid-token"},
        timeout=10,
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_login_and_logout_revoke_token(api_base_url, auth_credentials):
    username, password = auth_credentials
    login = requests.post(
        f"{api_base_url}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    assert login.status_code == 200

    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert requests.get(f"{api_base_url}/projects", headers=headers, timeout=10).status_code == 200
    assert requests.post(
        f"{api_base_url}/auth/logout",
        json={"token": token},
        headers=headers,
        timeout=10,
    ).status_code == 204
    assert requests.get(f"{api_base_url}/projects", headers=headers, timeout=10).status_code == 401

