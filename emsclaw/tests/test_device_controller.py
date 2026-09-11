"""DeviceController — HTTP 入口测试。

FastAPI TestClient + dependency override require_user,
业务层注入 sqlite in-memory session。
"""
import pytest
from fastapi.testclient import TestClient

from emsclaw_backend.controller.device_controller import router
from emsclaw_backend.user.dependencies import require_user
from emsclaw_backend.user.dependencies import User


@pytest.fixture
def device_client(sqlite_device_db):
    """构造只挂 device router 的 TestClient,override 鉴权为匿名 user。"""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    fake_user = User(id="tester", username="tester", role="user")
    app.dependency_overrides[require_user] = lambda: fake_user
    return TestClient(app)


def test_list_empty(device_client):
    r = device_client.get("/api/v1/devices")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"] == []


def test_create_then_get_then_list(device_client):
    # 创建
    r = device_client.post("/api/v1/devices", json={"name": "BESS_01", "device_type": "battery"})
    assert r.status_code == 201
    created = r.json()["data"]
    assert created["id"].startswith("DEV-")
    assert created["status"] == "offline"

    # 详情
    r = device_client.get(f"/api/v1/devices/{created['id']}")
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "BESS_01"

    # 列表
    r = device_client.get("/api/v1/devices")
    assert len(r.json()["data"]) == 1


def test_create_rejects_invalid_type(device_client):
    r = device_client.post("/api/v1/devices", json={"name": "X", "device_type": "unknown"})
    assert r.status_code == 400
    assert "设备类型" in r.json()["detail"]


def test_create_rejects_duplicate_name(device_client):
    device_client.post("/api/v1/devices", json={"name": "DUP", "device_type": "battery"})
    r = device_client.post("/api/v1/devices", json={"name": "DUP", "device_type": "meter"})
    assert r.status_code == 400
    assert "已存在" in r.json()["detail"]


def test_get_404_when_missing(device_client):
    r = device_client.get("/api/v1/devices/DEV-NOPE")
    assert r.status_code == 404


def test_list_with_filter(device_client):
    device_client.post("/api/v1/devices", json={"name": "b1", "device_type": "battery"})
    device_client.post("/api/v1/devices", json={"name": "m1", "device_type": "meter"})
    r = device_client.get("/api/v1/devices", params={"device_type": "meter"})
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["device_type"] == "meter"


def test_configure_network_success(device_client):
    created = device_client.post(
        "/api/v1/devices", json={"name": "N1", "device_type": "battery"},
    ).json()["data"]
    r = device_client.post(
        f"/api/v1/devices/{created['id']}/network",
        json={"ip_address": "10.0.0.5", "protocol": "ModbusTCP", "port": 502},
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "pending_online"
    assert body["network_config"]["ip_address"] == "10.0.0.5"
    assert body["network_config"]["port"] == 502


def test_configure_network_bad_ip(device_client):
    created = device_client.post(
        "/api/v1/devices", json={"name": "N2", "device_type": "battery"},
    ).json()["data"]
    r = device_client.post(
        f"/api/v1/devices/{created['id']}/network",
        json={"ip_address": "999.0.0.1", "protocol": "ModbusTCP"},
    )
    assert r.status_code == 400


def test_configure_network_missing_device(device_client):
    r = device_client.post(
        "/api/v1/devices/DEV-NOPE/network",
        json={"ip_address": "10.0.0.1", "protocol": "MQTT"},
    )
    assert r.status_code == 400