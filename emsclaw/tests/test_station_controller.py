"""StationController — 预测/总览端点契约测试。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from emsclaw_backend.controller.station_controller import router
from emsclaw_backend.user.dependencies import require_user, User
from emsclaw_backend.service import station_service


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    fake_user = User(id="tester", username="tester", role="user")
    app.dependency_overrides[require_user] = lambda: fake_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def station_svc(sqlite_station_db):
    """构造测试 svc 并设为单例,使 controller 的 _svc() 复用同一实例。"""
    svc = station_service.StationSimService()
    station_service._default_service = svc
    svc.ensure_seeded()
    yield svc
    station_service._default_service = None


def test_forecast_list_ok(client, station_svc):
    r = client.get("/api/v1/station/forecast?days=7")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 7
    assert "load_kw" in data[0]
    assert "pv_kw" in data[0]
    assert len(data[0]["load_kw"]) == 24


def test_forecast_day_ok(client, station_svc):
    r = client.get("/api/v1/station/forecast/day/2026-08-01")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["target_date"] == "2026-08-01"
    assert len(d["load_kw"]) == 24
    assert len(d["pv_kw"]) == 24
    assert len(d["net_load_kw"]) == 24
    assert "load_peak_kw" in d
    assert "pv_energy_kwh" in d


def test_forecast_day_pv_zero_at_night(client, station_svc):
    r = client.get("/api/v1/station/forecast/day/2026-08-01")
    d = r.json()["data"]
    assert d["pv_kw"][2] == 0.0


def test_overview_ok(client, station_svc):
    r = client.get("/api/v1/station/overview")
    assert r.status_code == 200
    d = r.json()["data"]
    assert "pv" in d
    assert "pv_rated_kwp" in d
    assert d["pv_rated_kwp"] == 2000.0


def test_tariff_8_periods(client, station_svc):
    r = client.get("/api/v1/station/tariff")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 8


# ── 站配置更新 PUT /station/config ───────────────────────────────
def test_update_config_ok(client, station_svc):
    r = client.put("/api/v1/station/config", json={"contract_demand_kw": 1500.0})
    assert r.status_code == 200
    d = r.json()["data"]
    assert r.json()["code"] == 0
    assert d["contract_demand_kw"] == 1500.0
    # 更新立即生效:需量状态读到新申报值
    dr = client.get("/api/v1/station/demand").json()["data"]
    assert dr["contract_demand_kw"] == 1500.0


def test_update_config_partial_keeps_others(client, station_svc):
    r = client.put("/api/v1/station/config", json={"anti_reverse_export_setpoint_kw": 80.0})
    assert r.json()["code"] == 0
    d = r.json()["data"]
    assert d["anti_reverse_export_setpoint_kw"] == 80.0
    assert d["contract_demand_kw"] == 1250.0  # 未传字段保持原值


def test_update_config_rejects_all_none(client, station_svc):
    r = client.put("/api/v1/station/config", json={})
    assert r.status_code == 200
    assert r.json()["code"] == 1
    assert "至少提供一项" in r.json()["msg"]


def test_update_config_rejects_negative(client, station_svc):
    r = client.put("/api/v1/station/config", json={"contract_demand_kw": -5.0})
    assert r.status_code == 422  # DTO ge=0 校验拦截
