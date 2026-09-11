"""tick 配置驱动 + 全数据链路走 tick —— 回归测试。

背景(要避免的问题):
  1. 负荷曲线 `_load_profile_base_kw` 把千瓦值硬编码在代码里,与 StationConfig 无关
     —— 改场站规模(储能/光伏/变压器容量)负荷曲线纹丝不动。
  2. tick 的光伏公式与站级预测的光伏公式是两份不同的代码:
     tick = rated × 辐照/1000 × 0.8(无季节因子、无典型云损)
     预测 = rated × 晴空辐照/1000 × 0.8 × 0.85 × 季节因子
     同一场站历史曲线峰值 1600kW vs 预测曲线峰值 1024kW,差 1.56 倍,
     且 tick 完全没有季节变化。
  3. 面向 agent 的 get_forecast / get_station_overview 走的是 get_forecast_day
     的独立公式路径,策略求解走的是 forecast_from_ticks —— 界面上看到的预测
     与策略用的预测是两套数据。
  4. forecast_from_ticks 只看负荷历史:光伏历史不足时 pv_kw 静默保持全 0,
     却仍标 confidence="high" —— LP 会以为光伏全天不出力。
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from emsclaw_backend.db.models import MeterSnapshot
from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.service import station_service as S
from emsclaw_backend.service.ems_data import (
    SOURCE_FALLBACK_FORMULA,
    SOURCE_MIXED,
    SOURCE_TICK_HISTORY,
    forecast_from_ticks,
)
from emsclaw_backend.service.station_service import StationSimService

_SH = ZoneInfo("Asia/Shanghai")

# 改造前硬编码的负荷曲线。留作回归基准:load_peak_kw 取默认值时必须逐点相等,
# 否则既有部署的负荷量级会被悄悄改掉。
LEGACY_LOAD_CURVE = (
    350, 375, 400, 425, 450, 475, 500, 620, 740, 860, 1070, 1280,
    1280, 1140, 1000, 1150, 1300, 1450, 1480, 1510, 1300, 1100, 900, 700,
)


@pytest.fixture
def svc(sqlite_station_db):
    return StationSimService(mapper=StationMapper(session_factory=sqlite_station_db))


# ── 1. 负荷曲线:形状固定、幅度由配置决定 ──────────────────────


def test_load_curve_default_matches_legacy():
    """默认 load_peak_kw 下曲线与改造前逐点一致(向后兼容)。"""
    for h in range(24):
        assert S._load_profile_base_kw(h) == pytest.approx(LEGACY_LOAD_CURVE[h], abs=1e-9)


def test_load_curve_scales_with_configured_peak():
    """曲线按 load_peak_kw 等比缩放 —— 这是"tick 基于配置生成数据"的核心。"""
    for peak in (755.0, 3020.0):
        curve = [S._load_profile_base_kw(h, peak) for h in range(24)]
        assert max(curve) == pytest.approx(peak)
        ratio = peak / S._LOAD_PROFILE_SHAPE_PEAK_KW
        for h in range(24):
            assert curve[h] == pytest.approx(LEGACY_LOAD_CURVE[h] * ratio, abs=1e-9)


def test_shape_table_peak_matches_declared_peak():
    """形状表峰值必须等于声明的基准,否则默认口径就错了。"""
    assert S._LOAD_PROFILE_SHAPE_PEAK_KW == max(LEGACY_LOAD_CURVE)
    assert S._DEFAULT_LOAD_PEAK_KW == S._LOAD_PROFILE_SHAPE_PEAK_KW


# ── 2. 配置落库与生效 ──────────────────────────────────────────


def test_ensure_seeded_writes_load_peak_and_derives_contract_demand(svc):
    """播种时写入 load_peak_kw,并由它派生申报需量(而非写死 1250)。"""
    svc.ensure_seeded()
    cfg = svc.mapper.get_station_config()
    assert cfg.load_peak_kw == pytest.approx(S._DEFAULT_LOAD_PEAK_KW)

    expected = round(cfg.load_peak_kw * S._DEFAULT_CONTRACT_DEMAND_RATIO / 10) * 10
    assert cfg.contract_demand_kw == pytest.approx(expected)
    # 与改造前的硬编码值一致,保证既有部署行为不变
    assert expected == 1250.0


def test_forecast_load_peak_follows_config(svc):
    """改配置 → 预测(进而是 tick 实测)负荷幅度真的跟着变。"""
    svc.ensure_seeded()
    d = date(2026, 9, 10)

    before = svc.get_forecast_day(d)["load_peak_kw"]
    assert before == pytest.approx(S._DEFAULT_LOAD_PEAK_KW)

    svc.update_station_config({"load_peak_kw": 3020.0})
    after = svc.get_forecast_day(d)["load_peak_kw"]
    assert after == pytest.approx(3020.0)

    # 申报需量不跟着动 —— 它是独立合同值,由用户显式设置
    assert svc.mapper.get_station_config().contract_demand_kw == pytest.approx(1250.0)


def test_updating_other_fields_keeps_load_peak(svc):
    """upsert 白名单纳入 load_peak_kw,同时不因更新别的字段被重置。"""
    svc.ensure_seeded()
    svc.update_station_config({"load_peak_kw": 2000.0})
    svc.update_station_config({"contract_demand_kw": 1600.0})

    cfg = svc.mapper.get_station_config()
    assert cfg.load_peak_kw == pytest.approx(2000.0)
    assert cfg.contract_demand_kw == pytest.approx(1600.0)
    # 未触及的字段保持原值
    assert cfg.anti_reverse_export_setpoint_kw == pytest.approx(50.0)


# ── 3. tick 与预测共用同一条光伏公式 ───────────────────────────


def test_tick_and_forecast_pv_share_one_formula(svc):
    """同一场站、同一辐照下,tick 与预测必须给出同一个光伏出力。"""
    svc.ensure_seeded()
    d = date(2026, 9, 10)
    doy = d.timetuple().tm_yday
    fc = svc.get_forecast_day(d)

    for h in range(24):
        ir = S.irradiance_after_cloud(
            S.clear_sky_irradiance_wm2(h, doy), S._TYPICAL_CLOUD_COVER
        )
        # tick 侧走的就是 pv_output_kw(rated, irradiance);预测侧必须同值
        assert fc["pv_kw"][h] == pytest.approx(S.pv_output_kw(2000.0, ir), abs=0.02)


def test_forecast_pv_reproduces_legacy_magnitude(svc):
    """预测光伏量与改造前同量级(0.85 典型云损的标定被保留)。"""
    svc.ensure_seeded()
    d = date(2026, 9, 10)
    season = S._seasonal_pv_factor(d.timetuple().tm_yday)
    fc = svc.get_forecast_day(d)

    for h in range(24):
        legacy = 2000.0 * (S._clear_sky_irradiance(h) / 1000.0) * 0.8 * 0.85 * season
        assert fc["pv_kw"][h] == pytest.approx(legacy, abs=0.5)


def test_pv_irradiance_includes_seasonal_factor():
    """季节因子作用在辐照上,所以 tick 与预测都有季节变化(改造前 tick 没有)。"""
    summer = S.clear_sky_irradiance_wm2(13, 172)
    winter = S.clear_sky_irradiance_wm2(13, 355)
    assert summer > winter
    assert S.pv_output_kw(2000.0, summer) > S.pv_output_kw(2000.0, winter)


# ── 4. 逐条判定数据来源:光伏不再静默归零 ──────────────────────


def test_forecast_from_ticks_marks_pv_source_separately(svc):
    """只灌负荷历史、不灌光伏历史时:光伏必须回退公式,而不是静默全 0。"""
    svc.ensure_seeded()
    mapper = svc.mapper
    meter = mapper.first_meter_device()
    assert meter is not None

    base = int(datetime(2026, 8, 1, tzinfo=_SH).timestamp())
    for day in range(4):
        for hour in range(24):
            mapper.insert_meter_snapshot(MeterSnapshot(
                id=f"MSN-T{day}-{hour}", meter_id=meter.id,
                timestamp=base + day * 86400 + hour * 3600,
                import_kw=100.0, export_kw=0.0, load_kw=900.0, reverse_flow=False,
                rolling_demand_kw=900.0, frequency=50.0, power_factor=0.95,
                total_active_power_kw=100.0,
            ))

    fc = forecast_from_ticks(date(2026, 8, 5), mapper=mapper)

    assert fc["load_source"] == SOURCE_TICK_HISTORY
    assert fc["pv_source"] == SOURCE_FALLBACK_FORMULA
    assert fc["source"] == SOURCE_MIXED
    assert fc["confidence"] == "low"          # 混合来源不能标 high
    assert fc["load_days_covered"] == 4
    assert fc["pv_days_covered"] == 0

    # 关键回归:光伏必须来自回退公式(白天有出力),不能是静默的 [0.0]*24
    assert max(fc["pv_kw"]) > 0.0
    # 负荷则来自 tick 快照
    assert fc["load_kw"][3] == pytest.approx(900.0)


def test_forecast_from_ticks_all_fallback_without_history(svc):
    """完全无历史时:两侧都标记为公式回退,置信度 low,且不抛错。"""
    svc.ensure_seeded()
    fc = forecast_from_ticks(date(2026, 8, 5), mapper=svc.mapper)

    assert fc["load_source"] == SOURCE_FALLBACK_FORMULA
    assert fc["pv_source"] == SOURCE_FALLBACK_FORMULA
    assert fc["source"] == SOURCE_FALLBACK_FORMULA
    assert fc["confidence"] == "low"
    assert max(fc["load_kw"]) > 0.0
    assert max(fc["pv_kw"]) > 0.0
