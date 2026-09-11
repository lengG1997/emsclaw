"""PcsController — 端点契约测试。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from emsclaw_backend.controller.pcs_controller import router
from emsclaw_backend.user.dependencies import require_user, User


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # status/snapshots/mode 用 require_user;测试里 override 为匿名 user
    fake_user = User(id="tester", username="tester", role="user")
    app.dependency_overrides[require_user] = lambda: fake_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_tick_requires_api_key_when_set(client, monkeypatch):
    # 默认未设 TASK_SERVICE_API_KEY → 敞开;设了则要头
    from emsclaw_backend.config import settings
    monkeypatch.setattr(settings, "task_service_api_key", "secret")
    r = client.post("/api/v1/pcs/sim/tick")
    assert r.status_code == 401


def test_tick_ok_without_key(client, sqlite_pcs_db, monkeypatch):
    # 确保 task_service_api_key 未设 → 敞开调用
    from emsclaw_backend.config import settings
    monkeypatch.setattr(settings, "task_service_api_key", "")
    # tick 端点内部 StationSimService() 默认 StationMapper 走真实 Postgres;
    # 测试环境无 Postgres,须把 station mapper 也指到 sqlite(表缺失时 tick 内部防御吞掉)。
    import emsclaw_backend.mapper.station_mapper as stn_m
    monkeypatch.setattr(stn_m, "SyncSessionLocal", sqlite_pcs_db)
    # 表空时 tick_all 返回 ticked=0
    r = client.post("/api/v1/pcs/sim/tick")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["ticked"] == 0


def test_status_not_found(client, sqlite_pcs_db):
    r = client.get("/api/v1/pcs/PCS-NOPE/status")
    assert r.status_code == 404


def test_snapshots_empty(client, sqlite_pcs_db):
    r = client.get("/api/v1/pcs/PCS-1/snapshots?from=0&to=9999")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_set_mode_expires_at_zero_means_inactive(client, sqlite_pcs_db):
    """expires_at=0 → 立即过期,override 不生效;大值 → 生效。"""
    import time
    from emsclaw_backend.service.pcs_service import PcsService

    svc = PcsService()
    svc.ensure_seeded()
    pairs = svc._mapper.find_online_pcs_with_battery()
    assert pairs, "ensure_seeded 后应至少有一台 PCS"
    pcs_id = pairs[0][0].id

    # 1) expires_at=0 → override 未激活
    r = client.post(f"/api/v1/pcs/{pcs_id}/mode", json={
        "mode": "discharge", "power_kw": 400.0, "expires_at": 0,
    })
    assert r.status_code == 200
    now = int(time.time())
    refreshed = svc._mapper.find_pcs_by_id(pcs_id)
    # override_expires_at=0 ≤ now → 不应被 decide 视为激活
    assert not (refreshed.override_mode
                and refreshed.override_expires_at
                and refreshed.override_expires_at > now), \
        "expires_at=0 应表示立即过期,override 不应激活"

    # 2) expires_at=99999999999 → override 激活
    r = client.post(f"/api/v1/pcs/{pcs_id}/mode", json={
        "mode": "charge", "power_kw": 300.0, "expires_at": 99999999999,
    })
    assert r.status_code == 200
    refreshed = svc._mapper.find_pcs_by_id(pcs_id)
    assert refreshed.override_mode == "charge"
    assert refreshed.override_power_kw == 300.0
    assert refreshed.override_expires_at > now


def test_list_pcs_empty(client, sqlite_pcs_db):
    from emsclaw_backend.config import settings
    # ensure no api key gating
    import emsclaw_backend.config as cfg
    # tick endpoint isn't used here; list_pcs uses require_user (overridden in app fixture)
    r = client.get("/api/v1/pcs")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_list_pcs_with_seeded(client, sqlite_pcs_db):
    from emsclaw_backend.service.pcs_service import PcsService
    svc = PcsService()
    svc.ensure_seeded()
    svc.tick_all(now_ts=1000)
    r = client.get("/api/v1/pcs")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    assert data[0]["pcs"]["id"].startswith("PCS-")
    assert data[0]["battery"] is not None
    assert data[0]["latest_pcs_snapshot"] is not None
