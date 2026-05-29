import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from auth.main import app

client = TestClient(app)

@pytest.fixture
def mock_get_user():
    with patch("auth.router.get_user", new_callable=AsyncMock) as mock:
        yield mock

def test_login_success(mock_get_user):
    # Given
    mock_get_user.return_value = {
        "operator_id": "test-op",
        "password_hash": "$2b$12$rzG/cD8ip1VsLPw0A2s9YOzjmzMXexMxXWhLH2cTtNP11Yn6ERdl.", # "test"
        "role": "OPERATOR",
        "active": True
    }
    
    # When
    response = client.post("/auth/login", json={"operatorId": "test-op", "password": "test"})
    
    # Then
    assert response.status_code == 200
    assert "token" in response.json()
    assert response.json()["role"] == "OPERATOR"

def test_login_invalid_password(mock_get_user):
    # Given
    mock_get_user.return_value = {
        "operator_id": "test-op",
        "password_hash": "$2b$12$rzG/cD8ip1VsLPw0A2s9YOzjmzMXexMxXWhLH2cTtNP11Yn6ERdl.", # "test"
        "role": "OPERATOR",
        "active": True
    }
    
    # When
    response = client.post("/auth/login", json={"operatorId": "test-op", "password": "wrong"})
    
    # Then
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"

def test_login_inactive_user(mock_get_user):
    # Given
    mock_get_user.return_value = {
        "operator_id": "test-op",
        "password_hash": "$2b$12$rzG/cD8ip1VsLPw0A2s9YOzjmzMXexMxXWhLH2cTtNP11Yn6ERdl.", # "test"
        "role": "OPERATOR",
        "active": False
    }
    
    # When
    response = client.post("/auth/login", json={"operatorId": "test-op", "password": "test"})
    
    # Then
    assert response.status_code == 401
    assert response.json()["detail"] == "Account is inactive"

def test_verify_token(mock_get_user):
    # Given: Login to get a token
    mock_get_user.return_value = {
        "operator_id": "test-op",
        "password_hash": "$2b$12$rzG/cD8ip1VsLPw0A2s9YOzjmzMXexMxXWhLH2cTtNP11Yn6ERdl.", # "test"
        "role": "OPERATOR",
        "active": True
    }
    login_response = client.post("/auth/login", json={"operatorId": "test-op", "password": "test"})
    token = login_response.json()["token"]
    
    # When
    response = client.get("/auth/verify", headers={"Authorization": f"Bearer {token}"})
    
    # Then
    assert response.status_code == 200
    assert response.json()["operatorId"] == "test-op"
    assert response.json()["role"] == "OPERATOR"
