"""StationSimService - 场站级模拟业务规则层。

职责:
- tick:推进 PCS(PcsService)+ 生成天气/光伏/关口表/需量/日电量
- ensure_seeded:建光伏/关口表设备 + 站配置 + 默认电价时段表
- 查询:overview / 各快照范围 / 电价 / 日电量 / 需量

物理模型(全 kW 口径,与 PCS 500kW 同量级,便于演示削峰填谷/防逆流/需量):
- 负荷:双峰曲线,峰 ~1500kW / 谷 ~350kW
- 光伏:rated_kwp × irradiance/1000 × 0.8(综合损耗),夜间 0
- 关口表:grid_net = load - PV + battery_power(charge+/discharge-)
  -> import/export/reverse_flow/rolling_demand
- 日电量:tick 累计 charge/discharge kWh + 收益(按当前时段电价)

不接触 HTTP。全防御:无设备/配置时用默认值、跳过写入、不抛错。
"""
from __future__ import annotations
import math
import random
import shortuuid
import time
from datetime import datetime, date as _date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from emsclaw_backend.db.models import (
    DailyEnergyRecord, Device, ElectricityTariff, MeterDevice, MeterSnapshot,
    PvDevice, PvSnapshot, StationConfig, WeatherSnapshot,
)
from emsclaw_backend.mapper.device_mapper import DeviceMapper
from emsclaw_backend.mapper.station_mapper import StationMapper
from emsclaw_backend.service.pcs_service import PcsService

_TICK_SECONDS = 60
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now() -> int:
    return int(time.time())


def _display_hour(now_ts: int) -> int:
    return datetime.fromtimestamp(now_ts, tz=_SHANGHAI).hour


def _date_str(now_ts: int) -> str:
    return datetime.fromtimestamp(now_ts, tz=_SHANGHAI).strftime("%Y-%m-%d")


def _start_of_day_ts(now_ts: int) -> int:
    dt = datetime.fromtimestamp(now_ts, tz=_SHANGHAI)
    return int(datetime(dt.year, dt.month, dt.day, tzinfo=_SHANGHAI).timestamp())


# ── 物理模型:负荷 / 光照 / 天气 ──

def _load_profile_base_kw(hour: int) -> float:
    """场站实测负荷确定性基值(kW):双峰(午峰+晚峰),夜间低谷。

    tick 与预测共用此基值,保证历史曲线与预测曲线同源、逻辑可循。
    """
    if 0 <= hour < 6:
        base = 350 + hour * 25
    elif 6 <= hour < 9:
        base = 500 + (hour - 6) * 120
    elif 9 <= hour < 12:
        base = 860 + (hour - 9) * 210       # 860-1280
    elif 12 <= hour < 14:
        base = 1280 - (hour - 12) * 140
    elif 14 <= hour < 17:
        base = 1000 + (hour - 14) * 150     # 1000-1450
    elif 17 <= hour < 20:
        base = 1450 + (hour - 17) * 30      # 晚峰 1450-1540
    elif 20 <= hour < 24:
        base = 1300 - (hour - 20) * 200
    else:
        base = 400
    return float(base)


def _load_profile_kw(hour: int) -> float:
    """场站实测负荷(kW):基值 × ±5% 扰动(实时 tick 用)。"""
    return _load_profile_base_kw(hour) * random.uniform(0.95, 1.05)


def _seasonal_pv_factor(doy: int) -> float:
    """光伏季节因子(夏高冬低,0.4~1.0)。

    以夏至(doy≈172)为峰、冬至(doy≈355)为谷。预测光伏随日期变化。
    """
    return round(0.7 + 0.3 * math.cos(2 * math.pi * (doy - 172) / 365), 3)


def _clear_sky_irradiance(hour: int) -> float:
    """晴空辐照(W/m²),以 13 点为峰的钟形,夜间 0。"""
    if hour < 6 or hour > 18:
        return 0.0
    frac = math.cos((hour - 13) / 6.0 * (math.pi / 2))
    return max(0.0, 1000.0 * frac)


def _gen_weather(hour: int) -> tuple[float, float, float, float]:
    """返回 (irradiance W/m², temperature ℃, cloud_cover 0-1, wind_speed m/s)。"""
    cloud = random.uniform(0.0, 0.4)
    irradiance = _clear_sky_irradiance(hour) * (1 - cloud * 0.7)
    temp = 18.0 + 10.0 * max(0.0, math.cos((hour - 14) / 6.0 * (math.pi / 2))) - cloud * 4.0
    temp += random.uniform(-1.5, 1.5)
    wind = random.uniform(0.5, 5.0)
    return round(irradiance, 1), round(temp, 1), round(cloud, 2), round(wind, 1)


# ── 默认电价时段(尖/峰/平/谷,元/kWh) ──
_DEFAULT_TARIFFS = [
    ("valley", 0, 7, 0.35),
    ("flat", 7, 9, 0.75),
    ("peak", 9, 12, 1.05),
    ("flat", 12, 14, 0.75),
    ("peak", 14, 17, 1.05),
    ("sharp", 17, 19, 1.25),
    ("flat", 19, 22, 0.75),
    ("valley", 22, 24, 0.35),
]


class StationSimService:
    def __init__(self, mapper: Optional[StationMapper] = None,
                 pcs_service: Optional[PcsService] = None):
        self._mapper = mapper or StationMapper()
        self._pcs = pcs_service or PcsService()

    # ── tick ──────────────────────────────────────────────────
    def tick(self, now_ts: Optional[int] = None) -> dict:
        now_ts = now_ts if now_ts is not None else _now()
        hour = _display_hour(now_ts)

        # 1. PCS 推进(写 pcs/电池快照、更新 SOC)
        try:
            pcs_result = self._pcs.tick_all(now_ts)
            ticked = pcs_result.get("ticked", 0)
        except Exception:
            ticked = 0

        # 2. 天气(场站级,总有)
        irradiance, temp, cloud, wind = _gen_weather(hour)
        try:
            self._mapper.insert_weather_snapshot(WeatherSnapshot(
                id=f"WSN-{shortuuid.uuid()[:10]}", timestamp=now_ts,
                irradiance=irradiance, temperature=temp,
                cloud_cover=cloud, wind_speed=wind,
            ))
        except Exception:
            pass

        # 3. 光伏出力
        pv_kw = 0.0
        try:
            pv_dev = self._mapper.first_pv_device()
            if pv_dev is not None:
                pv_kw = pv_dev.rated_capacity_kwp * (irradiance / 1000.0) * 0.8
                pv_kw = round(pv_kw * random.uniform(0.97, 1.0), 2)
                self._mapper.insert_pv_snapshot(PvSnapshot(
                    id=f"PVSN-{shortuuid.uuid()[:10]}", pv_id=pv_dev.id,
                    timestamp=now_ts, generation_kw=pv_kw, irradiance=irradiance,
                    temperature=temp, status="running" if pv_kw > 0 else "standby",
                ))
        except Exception:
            pass

        # 4. 实测负荷
        load_kw = round(_load_profile_kw(hour), 2)

        # 5. 电池功率(Σ 在线 PCS 有功,charge+/discharge-)
        battery_power = self._sum_battery_power()

        # 6. 关口表:grid_net = load - PV + battery_power
        grid_net = load_kw - pv_kw + battery_power
        import_kw = round(max(0.0, grid_net), 2)
        export_kw = round(max(0.0, -grid_net), 2)
        # 关口表一级有功功率(带符号:正=下网受电,负=上网送电)
        total_active_power_kw = round(import_kw - export_kw, 2)

        cfg = self._safe_config()
        setpoint = cfg.anti_reverse_export_setpoint_kw if cfg else 0.0
        reverse_flow = export_kw > setpoint

        rolling_demand = 0.0
        try:
            meter_dev = self._mapper.first_meter_device()
            if meter_dev is not None:
                rolling_demand = self._rolling_demand(meter_dev.id, import_kw, now_ts)
                self._mapper.insert_meter_snapshot(MeterSnapshot(
                    id=f"MSN-{shortuuid.uuid()[:10]}", meter_id=meter_dev.id,
                    timestamp=now_ts, import_kw=import_kw, export_kw=export_kw,
                    load_kw=load_kw, reverse_flow=reverse_flow,
                    rolling_demand_kw=round(rolling_demand, 2),
                    frequency=round(50.0 + random.uniform(-0.1, 0.1), 2),
                    power_factor=round(random.uniform(0.92, 0.99), 3),
                    total_active_power_kw=total_active_power_kw,
                ))
        except Exception:
            pass

        # 7. 日电量累计
        energy = self._accumulate_daily_energy(battery_power, hour, now_ts)

        return {
            "ts": now_ts,
            "ticked": ticked,
            "pv_kw": pv_kw,
            "load_kw": load_kw,
            "battery_power_kw": round(battery_power, 2),
            "import_kw": import_kw,
            "export_kw": export_kw,
            "total_active_power_kw": total_active_power_kw,
            "reverse_flow": reverse_flow,
            "rolling_demand_kw": round(rolling_demand, 2),
            "energy_today": _orm_dict(energy),
        }

    def _safe_config(self) -> Optional[StationConfig]:
        try:
            return self._mapper.get_station_config()
        except Exception:
            return None

    def _sum_battery_power(self) -> float:
        try:
            rows = self._pcs.list_status()
        except Exception:
            return 0.0
        total = 0.0
        for r in rows:
            snap = r.get("latest_pcs_snapshot")
            if snap is not None:
                total += snap.active_power_kw
        return total

    def _rolling_demand(self, meter_id: str, current_import: float, now_ts: int) -> float:
        """近 15min import 均值;无历史则取当前。"""
        try:
            rows = self._mapper.meter_snapshots_range(meter_id, now_ts - 900, now_ts)
        except Exception:
            return current_import
        if not rows:
            return current_import
        vals = [r.import_kw for r in rows] + [current_import]
        return sum(vals) / len(vals)

    def _accumulate_daily_energy(self, battery_power: float, hour: int,
                                 now_ts: int) -> Optional[DailyEnergyRecord]:
        """累计今日充放电电量(kWh)+ 收益(按当前时段电价)。"""
        try:
            date_str = _date_str(now_ts)
            rec = self._mapper.get_daily_energy(date_str)
            now = _now()
            charge_delta = max(0.0, battery_power) * _TICK_SECONDS / 3600.0
            discharge_delta = max(0.0, -battery_power) * _TICK_SECONDS / 3600.0
            tariff = self._mapper.get_tariff_for_hour("default", hour)
            price = tariff.energy_price if tariff else 0.7
            revenue_delta = discharge_delta * price * 0.9 - charge_delta * price
            if rec is None:
                rec = DailyEnergyRecord(
                    id=f"DE-{shortuuid.uuid()[:10]}", date=date_str,
                    charge_kwh=round(charge_delta, 4),
                    discharge_kwh=round(discharge_delta, 4),
                    revenue=round(revenue_delta, 2), updated_at=now,
                )
            else:
                rec.charge_kwh = round(rec.charge_kwh + charge_delta, 4)
                rec.discharge_kwh = round(rec.discharge_kwh + discharge_delta, 4)
                rec.revenue = round(rec.revenue + revenue_delta, 2)
                rec.updated_at = now
            return self._mapper.upsert_daily_energy(rec)
        except Exception:
            return None

    # ── 查询 ──────────────────────────────────────────────────
    def get_overview(self) -> dict:
        cfg = self._safe_config()
        region = cfg.region if cfg else "default"
        pv_dev = self._mapper.first_pv_device()
        pv_rated = pv_dev.rated_capacity_kwp if pv_dev else 0.0
        pv_snap = self._mapper.latest_pv_snapshot(pv_dev.id) if pv_dev else None
        meter_dev = self._mapper.first_meter_device()
        meter_snap = self._mapper.latest_meter_snapshot(meter_dev.id) if meter_dev else None
        weather = self._mapper.latest_weather_snapshot()
        energy = self._mapper.get_daily_energy(_date_str(_now()))
        hour = _display_hour(_now())
        tariff = self._mapper.get_tariff_for_hour(region, hour)
        tariff_current = None
        if tariff:
            tariff_current = {
                "period_type": tariff.period_type,
                "energy_price": tariff.energy_price,
                "start": f"{tariff.start_hour:02d}:00",
                "end": f"{tariff.end_hour:02d}:00",
            }
        return {
            "pv": _orm_dict(pv_snap),
            "pv_rated_kwp": pv_rated,
            "meter": _orm_dict(meter_snap),
            "weather": _orm_dict(weather),
            "energy_today": _orm_dict(energy),
            "tariff_current": tariff_current,
            "station_config": _orm_dict(cfg),
        }

    def pv_snapshots_range(self, start_ts: int, end_ts: int) -> list:
        pv_dev = self._mapper.first_pv_device()
        if pv_dev is None:
            return []
        return self._mapper.pv_snapshots_range(pv_dev.id, start_ts, end_ts)

    def meter_snapshots_range(self, start_ts: int, end_ts: int) -> list:
        meter_dev = self._mapper.first_meter_device()
        if meter_dev is None:
            return []
        return self._mapper.meter_snapshots_range(meter_dev.id, start_ts, end_ts)

    def weather_snapshots_range(self, start_ts: int, end_ts: int) -> list:
        return self._mapper.weather_snapshots_range(start_ts, end_ts)

    def list_tariffs(self) -> list:
        return self._mapper.list_tariffs("default")

    def list_daily_energy(self, days: int = 7) -> list:
        return self._mapper.list_daily_energy(days)

    def get_demand(self) -> dict:
        cfg = self._safe_config()
        contract = cfg.contract_demand_kw if cfg else 0.0
        current = 0.0
        max_today = 0.0
        try:
            meter_dev = self._mapper.first_meter_device()
            if meter_dev:
                snap = self._mapper.latest_meter_snapshot(meter_dev.id)
                current = snap.rolling_demand_kw if snap else 0.0
                max_today = self._mapper.meter_demand_max_since(
                    meter_dev.id, _start_of_day_ts(_now())
                )
        except Exception:
            pass
        return {
            "current_demand_kw": round(current, 2),
            "max_demand_today_kw": round(max_today, 2),
            "contract_demand_kw": contract,
            "demand_price_yuan_per_kw_month": cfg.demand_price_yuan_per_kw_month if cfg else 0.0,
            "demand_ratio": round(current / contract, 3) if contract else 0.0,
        }

    # ── 站配置:更新 ───────────────────────────────────────────
    def update_station_config(self, data: dict) -> dict:
        """更新站配置(申报需量/防逆流/容量电价/需量电价)。至少一项;返回更新后配置。

        供 REST API 与 device_operation 域 set_station_config 工具共用。更新立即生效,
        调度优化(optimize_dispatch)/收益核算(account_revenue)/需量状态读到的都是新值。
        """
        fields = {k: v for k, v in data.items() if v is not None}
        if not fields:
            raise ValueError("至少提供一项要更新的配置(申报需量/防逆流/电价)")
        for k, v in fields.items():
            if v < 0:
                raise ValueError(f"{k} 不能为负")
        cfg = StationConfig(id="STN-DEFAULT", updated_at=int(time.time()), **fields)
        updated = self._mapper.upsert_station_config(cfg)
        return _orm_dict(updated)

    # ── 预测 ──────────────────────────────────────────────────
    def get_forecast_day(self, target_date: _date) -> dict:
        """生成某日 24h 站级负荷/光伏预测(kW),与 tick 同源、逻辑可循。

        - load_kw: _load_profile_base_kw(h)(确定性双峰)
        - pv_kw: rated_kwp × clear_sky_irradiance/1000 × 0.8(综合损耗) × 0.85(典型云损) × 季节因子
        - net_load_kw: load - pv(电网需供给;负值=光伏过剩可能逆流)
        聚合:load_peak / pv_peak / load_energy_kwh / pv_energy_kwh(梯形积分)。
        无 PV 设备 → 光伏全 0;全防御不抛错。
        """
        doy = target_date.timetuple().tm_yday
        season = _seasonal_pv_factor(doy)
        pv_dev = self._mapper.first_pv_device()
        pv_rated = pv_dev.rated_capacity_kwp if pv_dev else 0.0

        load_kw, pv_kw, net_load_kw = [], [], []
        for h in range(24):
            load = _load_profile_base_kw(h)
            ir = _clear_sky_irradiance(h)
            pv = pv_rated * (ir / 1000.0) * 0.8 * 0.85 * season
            load_kw.append(round(load, 2))
            pv_kw.append(round(pv, 2))
            net_load_kw.append(round(load - pv, 2))

        load_energy = _trapezoid_kwh(load_kw)
        pv_energy = _trapezoid_kwh(pv_kw)
        return {
            "target_date": target_date.isoformat(),
            "load_kw": load_kw,
            "pv_kw": pv_kw,
            "net_load_kw": net_load_kw,
            "load_peak_kw": round(max(load_kw), 2) if load_kw else 0.0,
            "pv_peak_kw": round(max(pv_kw), 2) if pv_kw else 0.0,
            "load_energy_kwh": round(load_energy, 1),
            "pv_energy_kwh": round(pv_energy, 1),
            "pv_rated_kwp": pv_rated,
            "seasonal_factor": season,
        }

    def get_forecast(self, days: int = 7, today: Optional[_date] = None) -> list:
        """today + 未来 days-1 天的站级预测列表。"""
        today = today or _date.today()
        return [self.get_forecast_day(today + timedelta(days=i))
                for i in range(max(1, days))]

    # ── seed ──────────────────────────────────────────────────
    def ensure_seeded(self) -> dict:
        now = _now()
        dm = DeviceMapper(session_factory=self._mapper._sf)
        seeded = {"pv": 0, "meter": 0, "config": 0, "tariffs": 0}

        if self._mapper.first_pv_device() is None:
            dev = dm.insert(Device(
                id=f"DEV-{shortuuid.uuid()[:8].upper()}",
                name="PV-001", device_type="pv", status="online",
                network_config={}, created_at=now, updated_at=now,
            ))
            self._mapper.insert_pv_device(PvDevice(
                id=f"PV-{shortuuid.uuid()[:8].upper()}",
                device_id=dev.id, rated_capacity_kwp=2000.0,
                orientation_deg=180.0, tilt_deg=30.0,
                created_at=now, updated_at=now,
            ))
            seeded["pv"] = 1

        if self._mapper.first_meter_device() is None:
            dev = dm.insert(Device(
                id=f"DEV-{shortuuid.uuid()[:8].upper()}",
                name="METER-001", device_type="meter", status="online",
                network_config={}, created_at=now, updated_at=now,
            ))
            self._mapper.insert_meter_device(MeterDevice(
                id=f"MET-{shortuuid.uuid()[:8].upper()}",
                device_id=dev.id, rated_kw=2000.0,
                created_at=now, updated_at=now,
            ))
            seeded["meter"] = 1

        if self._mapper.get_station_config() is None:
            self._mapper.insert_station_config(StationConfig(
                id="STN-DEFAULT", region="default",
                # 申报需量略高于无储能基线关口峰值(~1222kW),留余量符合大工业实际;
                # 同时 ≥ LP 物理下限(~1146kW,15min 保守系数下),让 respect_declared_demand 可行
                contract_demand_kw=1250.0,
                anti_reverse_export_setpoint_kw=50.0,
                capacity_price_yuan_per_kw_month=30.0,
                demand_price_yuan_per_kw_month=40.0,
                updated_at=now,
            ))
            seeded["config"] = 1

        if self._mapper.count_tariffs("default") == 0:
            for (ptype, lo, hi, price) in _DEFAULT_TARIFFS:
                self._mapper.insert_tariff(ElectricityTariff(
                    id=f"TF-{shortuuid.uuid()[:8].upper()}",
                    region="default", period_type=ptype,
                    start_hour=lo, end_hour=hi, energy_price=price,
                    created_at=now, updated_at=now,
                ))
                seeded["tariffs"] += 1

        return seeded

    # ── 历史回灌 ────────────────────────────────────────────
    def seed_history(self, hours: int = 168) -> dict:
        """从 now-hours 起、按 1 分钟一帧回放 tick 逻辑,灌满历史快照。

        直接调用 self.tick(historical_ts) —— 物理模型(负荷/光照/光伏/
        关口表/日电量)与实时 tick 同源,保证历史曲线与未来 tick 衔接。
        默认 168h=7 天=10080 帧,每帧 insert 自带 commit。

        SOC 处理:tick 内部读 battery_devices.soc 做下一帧起点,_tick_one
        每帧 update_battery_soc 持久化。10080 帧反复查库太慢,因此本方法
        用内存 dict 缓存 SOC/cycle,patch 到 mapper 上避免每帧 DB 往返,
        最后一次性回写 battery_devices。
        """
        now = _now()
        start_ts = now - hours * 3600
        frames = hours * 60
        stats = {"frames": 0, "pcs": 0, "battery": 0,
                 "pv": 0, "meter": 0, "weather": 0, "daily_energy": 0}

        # 内存 SOC 缓存:device_id -> (soc, cycle_count)
        # 注意:find_online_pcs_with_battery 在 PcsMapper 上,不在 StationMapper
        soc_cache: dict[str, tuple[float, int]] = {}
        for _pcs, bat in self._pcs._mapper.find_online_pcs_with_battery():
            soc_cache[bat.device_id] = (bat.soc, bat.cycle_count)

        # 帧内优化:把 update_battery_soc 改写到内存缓存,并让
        # find_online_pcs_with_battery 返回的 bat 注入缓存的 SOC,避免逐帧读库。
        orig_update_soc = self._pcs._mapper.update_battery_soc
        orig_find_online = self._pcs._mapper.find_online_pcs_with_battery

        def _cache_update_soc(device_id: str, new_soc: float,
                              new_cycle: int, _ts: int) -> None:
            soc_cache[device_id] = (new_soc, new_cycle)

        def _find_online_with_cache():
            pairs = orig_find_online()
            for _p, _b in pairs:
                cached = soc_cache.get(_b.device_id)
                if cached is not None:
                    _b.soc = cached[0]
                    _b.cycle_count = cached[1]
            return pairs

        self._pcs._mapper.update_battery_soc = _cache_update_soc  # type: ignore
        self._pcs._mapper.find_online_pcs_with_battery = _find_online_with_cache  # type: ignore

        try:
            for i in range(frames):
                ts = start_ts + i * 60
                try:
                    self.tick(ts)
                    stats["frames"] += 1
                except Exception:
                    pass
            # 把内存 SOC 一次性回写到 battery_devices。
            # 回灌用于冷启动历史曲线,末态强制重置到健康循环起点(0.5),避免回灌末帧
            # (可能触底/触顶)导致 real-time tick 从死锁态启动、白天放电时段持续待机。
            # cycle_count 保留回灌累计值。
            for device_id, (soc, cycle) in soc_cache.items():
                try:
                    orig_update_soc(device_id, 0.5, cycle, now)
                except Exception:
                    pass
        finally:
            self._pcs._mapper.update_battery_soc = orig_update_soc  # type: ignore
            self._pcs._mapper.find_online_pcs_with_battery = orig_find_online  # type: ignore

        # 统计各表条数
        try:
            sf = self._mapper._sf  # type: ignore[attr-defined]
            from sqlalchemy import text
            with sf() as s:
                for key, tbl in (
                    ("pcs", "pcs_snapshots"),
                    ("battery", "battery_snapshots"),
                    ("pv", "pv_snapshots"),
                    ("meter", "meter_snapshots"),
                    ("weather", "weather_snapshots"),
                    ("daily_energy", "daily_energy_records"),
                ):
                    try:
                        r = s.execute(text(f'SELECT COUNT(*) FROM "{tbl}"'))
                        stats[key] = int(r.scalar() or 0)
                    except Exception:
                        pass
        except Exception:
            pass

        return stats


def _orm_dict(obj) -> Optional[dict]:
    if obj is None:
        return None
    cols = {c.name for c in obj.__table__.columns}
    return {c: getattr(obj, c) for c in cols}


def _trapezoid_kwh(values: list) -> float:
    """24 点(每小时 1 点)功率曲线 → 日电量 kWh(梯形积分,每段 1h)。"""
    if len(values) < 2:
        return 0.0
    total = 0.0
    for i in range(len(values) - 1):
        total += (values[i] + values[i + 1]) / 2.0
    return total


# ── 启动期 hook ─────────────────────────────────────────────────
_default_service: Optional[StationSimService] = None


def get_default_service() -> StationSimService:
    global _default_service
    if _default_service is None:
        _default_service = StationSimService()
    return _default_service


def reset_default_service() -> None:
    global _default_service
    _default_service = None
