"""PcsService — 储能模拟业务规则层。

职责:
- 调度状态机决定 mode + 有功基准:override → 当日 active 计划
  → 无计划时按电价时段兜底(低谷充电/高峰放电/平段待机)
- 手动 override 优先于一切(override_expires_at 未过期时)
- 每 tick:算功率 → SOC 积分(夹 [min_soc,max_soc],触边界转 standby)
  → 写 pcs_snapshots + battery_snapshots → 更新 battery_devices.soc/cycle_count
- ensure_seeded:表空时建 1 个 PCS + 1 个 Battery 默认设备

不接触 HTTP。mapper 可注入便于测试。
"""
from __future__ import annotations
import random
import shortuuid
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from emsclaw_backend.db.models import (
    BatteryDevice, BatterySnapshot, Device, PcsDevice, PcsSnapshot,
)
from emsclaw_backend.entity.pcs import PcsMode, PcsStatus
from emsclaw_backend.mapper.pcs_mapper import PcsMapper
from emsclaw_backend.mapper.schedule_mapper import ScheduleMapper
from loguru import logger

_TICK_SECONDS = 60  # beat 周期 = 60s
_SHANGHAI = ZoneInfo("Asia/Shanghai")

# ── 场站设备模型(1MW/2MWh,2×500kW PCS + 2×1000kWh 电池,0.5C) ──
# 单台 PCS 500kW;单台电池 1000kWh,750V×667A≈500kW=PCS 额定(自洽)
_SEED_PCS_RATED_KW = 500.0
_SEED_BAT_CAPACITY_KWH = 1000.0
_SEED_BAT_RATED_CURRENT_A = 667.0
_SEED_PCS_EFFICIENCY = 0.90


def _now() -> int:
    return int(time.time())


def _display_hour(now_ts: int) -> int:
    """tick 时间戳 → 北京时区小时(用于时段判定)。"""
    dt = datetime.fromtimestamp(now_ts, tz=_SHANGHAI)
    return dt.hour


def _date_str(now_ts: int) -> str:
    """tick 时间戳 → 北京时区日期串(YYYY-MM-DD,用于查当日 active 计划)。"""
    return datetime.fromtimestamp(now_ts, tz=_SHANGHAI).strftime("%Y-%m-%d")


class PcsService:
    def __init__(self, mapper: Optional[PcsMapper] = None,
                 schedule_mapper: Optional[ScheduleMapper] = None):
        self._mapper = mapper or PcsMapper()
        # ScheduleMapper 共用 PcsMapper 的 session_factory(测试时随 sqlite fixture 一起切换);
        # 未注入则默认 SyncSessionLocal,与 PcsMapper 生产态一致。
        self._schedule_mapper = schedule_mapper or ScheduleMapper(
            session_factory=self._mapper._sf
        )

    # ── 纯函数:调度状态机 ────────────────────────────────────
    def decide_mode_and_power(self, hour: int, pcs: PcsDevice) -> tuple[str, float]:
        """决定运行模式 + 目标有功基准(kW,充电+/放电-)。

        优先级:① 手动 override 未过期(应急/急停,1h TTL)→ ② 当日 active 充放电
        计划该小时的 DispatchInterval(power_ratio × rated)→ ③ 无计划时按电价时段
        兜底(谷充/峰尖放/平待机)。③ 与 tariff 表同源(总览背景带/调度优化/收益
        核算用同一张表),避免无人下发计划时储能孤岛永久待机、页面有功无值。
        SOC 不在此决定--按功率物理积分演化(符合现实);夹 [min_soc,max_soc] 在
        _tick_one 处理。
        """
        now = _now()
        # 1. override 优先(应急手动)
        if (pcs.override_mode and pcs.override_expires_at
                and pcs.override_expires_at > now):
            power = pcs.override_power_kw if pcs.override_power_kw is not None else 0.0
            if pcs.override_mode == PcsMode.DISCHARGE.value:
                power = -abs(power)
            elif pcs.override_mode == PcsMode.CHARGE.value:
                power = abs(power)
            else:  # standby / auto
                power = 0.0 if pcs.override_mode == PcsMode.STANDBY.value else power
            return pcs.override_mode, power
        # 2. 读当日 active 计划;有计划(含显式 standby 段)以计划为准
        try:
            seg = self._schedule_mapper.get_active_segment(_date_str(now), hour)
        except Exception:
            seg = None
        if seg is not None:
            mode = seg.get("mode", "standby")
            if mode == "standby":
                return "standby", 0.0
            ratio = float(seg.get("power_ratio", 0.0) or 0.0)
            power = pcs.rated_power_kw * ratio
            if mode == "discharge":
                power = -power
            return mode, power
        # 3. 无计划 → 电价时段兜底(谷充/峰尖放/平待机)
        return self._tariff_fallback(hour, pcs)

    def _tariff_fallback(self, hour: int, pcs: PcsDevice) -> tuple[str, float]:
        """无当日计划时的默认行为:按电价时段表推导(谷充/峰尖放/平待机)。

        tariff 表是场站单一真相源;查询失败/无数据 → 待机(全防御)。
        """
        try:
            from emsclaw_backend.mapper.station_mapper import StationMapper
            tariff = StationMapper(
                session_factory=self._mapper._sf
            ).get_tariff_for_hour("default", hour)
        except Exception:
            tariff = None
        if tariff is None:
            return "standby", 0.0
        if tariff.period_type == "valley":
            return "charge", pcs.rated_power_kw
        if tariff.period_type in ("peak", "sharp"):
            return "discharge", -pcs.rated_power_kw
        return "standby", 0.0

    # ── tick ──────────────────────────────────────────────────
    def tick_all(self, now_ts: Optional[int] = None) -> dict:
        """推进所有 online PCS 一帧;返回 {ticked, ts}。"""
        now_ts = now_ts if now_ts is not None else _now()
        hour = _display_hour(now_ts)
        pairs = self._mapper.find_online_pcs_with_battery()
        ticked = 0
        for pcs, bat in pairs:
            self._tick_one(pcs, bat, hour, now_ts)
            ticked += 1
        return {"ticked": ticked, "ts": now_ts}

    def _tick_one(self, pcs: PcsDevice, bat: BatteryDevice,
                  hour: int, now_ts: int) -> None:
        mode, target_power = self.decide_mode_and_power(hour, pcs)
        # ±5% 扰动
        active = target_power * random.uniform(0.95, 1.05)
        if mode == "standby":
            active = 0.0

        eff = pcs.rated_efficiency * random.uniform(0.985, 1.015)
        eff = max(0.0, min(1.0, eff))
        ac_v = pcs.ac_voltage_v * random.uniform(0.99, 1.01)
        dc_v = pcs.dc_voltage_v * random.uniform(0.99, 1.01)

        # SOC 积分
        new_soc = bat.soc
        if mode != "standby" and bat.rated_capacity_kwh > 0:
            delta = active * _TICK_SECONDS / 3600.0 / bat.rated_capacity_kwh
            new_soc = bat.soc + delta
        # 边界夹取,触边界转 standby
        clamped = False
        if new_soc >= pcs.max_soc:
            new_soc = pcs.max_soc
            if mode == "charge":
                mode, active = "standby", 0.0
                clamped = True
        if new_soc <= pcs.min_soc:
            new_soc = pcs.min_soc
            if mode == "discharge":
                mode, active = "standby", 0.0
                clamped = True

        # 电池电流(带符号:充电+/放电-)
        current = (active / dc_v) if dc_v != 0 else 0.0
        temperature = 28.0 + abs(active) / max(pcs.rated_power_kw, 1.0) * 5.0
        temperature += random.uniform(-1.0, 1.0)
        # 循环次数:完成一次满充放算一循环(简化:每 100 ticks +1 当有功率)
        new_cycle = bat.cycle_count
        if abs(active) > 0:
            new_cycle = bat.cycle_count + (1 if (now_ts // 3600) % 100 == 0 else 0)

        status = PcsStatus.RUNNING.value if abs(active) > 0 else PcsStatus.STANDBY.value

        # 写快照
        self._mapper.insert_pcs_snapshot(PcsSnapshot(
            id=f"PSN-{shortuuid.uuid()[:10]}",
            pcs_id=pcs.id, timestamp=now_ts,
            active_power_kw=round(active, 2),
            reactive_power_kvar=round(pcs.rated_reactive_kvar * 0.1 * random.uniform(0.8, 1.2), 2),
            mode=mode, ac_voltage_v=round(ac_v, 1), dc_voltage_v=round(dc_v, 1),
            efficiency=round(eff, 4), status=status,
        ))
        self._mapper.insert_battery_snapshot(BatterySnapshot(
            id=f"BSN-{shortuuid.uuid()[:10]}",
            battery_id=bat.id, timestamp=now_ts,
            soc=round(new_soc, 4), voltage=round(dc_v, 1),
            current_a=round(current, 2),
            temperature=round(temperature, 1),
            mode=mode, cycle_count=new_cycle,
        ))
        # 持久 SOC
        self._mapper.update_battery_soc(bat.device_id, round(new_soc, 4),
                                        new_cycle, now_ts)

    # ── 查询 ──────────────────────────────────────────────────
    def get_status(self, pcs_id: str) -> Optional[dict]:
        pcs = self._mapper.find_pcs_by_id(pcs_id)
        if pcs is None:
            return None
        p_snap = self._mapper.latest_pcs_snapshot(pcs_id)
        b_snap = None
        if pcs.battery_id:
            bat = self._mapper.find_battery_by_device_id(pcs.battery_id)
            if bat is not None:
                b_snap = self._mapper.latest_battery_snapshot(bat.id)
        return {
            "pcs": p_snap,
            "battery": b_snap,
        }

    def list_snapshots(self, pcs_id: str, start_ts: int, end_ts: int) -> list:
        return self._mapper.pcs_snapshots_range(pcs_id, start_ts, end_ts)

    def list_status(self) -> list[dict]:
        """列出所有 PCS + 关联电池 + 各自最新快照(供仪表盘 KPI)。"""
        return self._mapper.find_all_pcs_with_latest()

    def list_battery_snapshots(self, pcs_id: str, start_ts: int,
                               end_ts: int) -> list:
        """某台 PCS 关联电池的历史快照(SOC/电压/电流/温度),供总览页 SOC 曲线。

        mapper.battery_snapshots_range 已存在,数据每 tick 都在写;此处只补查询路径。
        """
        pcs = self._mapper.find_pcs_by_id(pcs_id)
        if pcs is None or not pcs.battery_id:
            return []
        bat = self._mapper.find_battery_by_device_id(pcs.battery_id)
        if bat is None:
            return []
        return self._mapper.battery_snapshots_range(bat.id, start_ts, end_ts)

    def get_charge_schedule(self, target_date: str | None = None) -> dict:
        """充放电调度计划:读指定日期 status=active 的 ChargeSchedule(调度优化生成并下发)。

        target_date 缺省=今天。返回 {date, total_rated_power_kw, strategies, status,
        schedule_id, created_by, segments[]}。
        每个 segment 为一条 DispatchInterval(hour/mode/power_kw/power_ratio/
        soc_target_pct/period/tariff_price)。无已下发计划 → segments 为空、status='none'。
        """
        now_ts = _now()
        date_str = target_date or _date_str(now_ts)
        pairs = self._mapper.find_online_pcs_with_battery()
        total_rated = sum(p.rated_power_kw for p, _ in pairs) if pairs else 0.0
        try:
            sched = self._schedule_mapper.get_active_schedule(date_str)
        except Exception:
            sched = None
        if sched is None or not sched.intervals:
            return {
                "date": date_str, "total_rated_power_kw": total_rated,
                "strategies": [], "status": "none", "schedule_id": None,
                "created_by": None,
                "segments": [], "note": "该日无已下发的充放电计划,储能按默认电价时段运行(谷充/峰放)",
            }
        mode_label = {"charge": "充电", "discharge": "放电", "standby": "待机"}
        segments = []
        for seg in sched.intervals:
            h = seg.get("hour", 0)
            mode = seg.get("mode", "standby")
            segments.append({
                "hour": h,
                "start": f"{h:02d}:00", "end": f"{(h + 1) % 24:02d}:00",
                "mode": mode, "label": mode_label.get(mode, mode),
                "power_kw": round(float(seg.get("power_kw", 0.0) or 0.0), 1),
                "power_ratio": round(float(seg.get("power_ratio", 0.0) or 0.0), 4),
                "soc_target_pct": round(float(seg.get("soc_target_pct", 0.0) or 0.0), 4),
                "period": seg.get("period", ""),
                "tariff_price": float(seg.get("tariff_price", 0.0) or 0.0),
            })
        return {
            "date": date_str, "total_rated_power_kw": total_rated,
            "strategies": sched.strategies or [], "status": sched.status,
            "schedule_id": sched.id, "created_by": sched.created_by,
            "segments": segments,
        }

    # ── 控制 ──────────────────────────────────────────────────
    def set_mode(self, pcs_id: str, mode: str, power_kw: float,
                expires_at: int) -> PcsDevice:
        if self._mapper.find_pcs_by_id(pcs_id) is None:
            raise ValueError(f"PCS '{pcs_id}' 不存在")
        updated = self._mapper.update_pcs_override(
            pcs_id, override_mode=mode, override_power_kw=power_kw,
            override_expires_at=expires_at, updated_at=_now(),
        )
        if updated is None:
            raise ValueError(f"PCS '{pcs_id}' 不存在")
        return updated

    # ── seed ──────────────────────────────────────────────────
    def ensure_seeded(self) -> int:
        """表空时建 2 台默认 PCS + 2 个默认 Battery(1MW/2MWh 场站);已存在则跳过。

        场站设备模型:2×500kW PCS(并机 1MW)+ 2×1000kWh 电池(750V×667A≈500kW=PCS 额定,0.5C)。
        """
        if self._mapper.count_pcs() > 0:
            # 已有设备:防止 SOC 触底卡死(容器重启后整个白天放电时段持续待机、页面无数据)
            recovered = self._recover_depleted_batteries()
            if recovered:
                logger.info(f"recovered {recovered} depleted battery SOC to 0.5")
            return 0
        now = _now()
        from emsclaw_backend.mapper.device_mapper import DeviceMapper
        dm = DeviceMapper(session_factory=self._mapper._sf)
        created = 0
        for i in (1, 2):
            pcs_dev = dm.insert(Device(
                id=f"DEV-{shortuuid.uuid()[:8].upper()}",
                name=f"PCS-{i:03d}", device_type="pcs",
                status="online", network_config={},
                created_at=now, updated_at=now,
            ))
            bat_dev = dm.insert(Device(
                id=f"DEV-{shortuuid.uuid()[:8].upper()}",
                name=f"BAT-{i:03d}", device_type="battery",
                status="online", network_config={},
                created_at=now, updated_at=now,
            ))
            self._mapper.insert_pcs(PcsDevice(
                id=f"PCS-{shortuuid.uuid()[:8].upper()}",
                device_id=pcs_dev.id, rated_power_kw=_SEED_PCS_RATED_KW,
                rated_reactive_kvar=100.0, ac_voltage_v=380.0, dc_voltage_v=750.0,
                rated_efficiency=_SEED_PCS_EFFICIENCY, min_soc=0.10, max_soc=0.90,
                battery_id=bat_dev.id, created_at=now, updated_at=now,
            ))
            self._mapper.insert_battery(BatteryDevice(
                id=f"BAT-{shortuuid.uuid()[:8].upper()}",
                device_id=bat_dev.id, rated_capacity_kwh=_SEED_BAT_CAPACITY_KWH,
                rated_voltage_v=750.0, rated_current_a=_SEED_BAT_RATED_CURRENT_A,
                soc=0.50, soh=0.925, cycle_count=0,
                created_at=now, updated_at=now,
            ))
            created += 1
        return created

    def _recover_depleted_batteries(self, recover_soc: float = 0.5) -> int:
        """SOC 触底(<=min_soc)的电池重置到 recover_soc,防止过放死锁。

        容器重启后若 SOC 卡在 min_soc,放电时段会持续待机、整个白天页面无数据;
        启动时把触底电池拉回健康循环起点。返回恢复的电池数。
        """
        now = _now()
        recovered = 0
        for _pcs, bat in self._mapper.find_online_pcs_with_battery():
            if bat.soc <= _pcs.min_soc:
                self._mapper.update_battery_soc(bat.device_id, recover_soc,
                                                bat.cycle_count, now)
                recovered += 1
        return recovered


# ── 启动期 hook ─────────────────────────────────────────────────
_default_service: Optional[PcsService] = None


def get_default_service() -> PcsService:
    global _default_service
    if _default_service is None:
        _default_service = PcsService()
    return _default_service


def reset_default_service() -> None:
    """测试 / 重启场景清空单例。"""
    global _default_service
    _default_service = None
