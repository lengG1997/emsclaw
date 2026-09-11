"""backend ORM models (PostgreSQL)."""
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, Integer, String, Text, Index, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    fullname: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_login: Mapped[int] = mapped_column(BigInteger, default=0)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # token
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(32), default="user")
    expires_at: Mapped[int] = mapped_column(BigInteger, default=0)
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    refresh_expires_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # shortuuid
    thread_id: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="business")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    vm_root_dir: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    unread_message_count: Mapped[int] = mapped_column(Integer, default=0)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_message: Mapped[str] = mapped_column(Text, default="")
    latest_message_at: Mapped[int] = mapped_column(BigInteger, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(Text, default="")
    model_config_: Mapped[dict] = mapped_column("model_config", JSONB, default=dict)
    events: Mapped[list] = mapped_column(JSONB, default=list)
    plan: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_updated_at", "updated_at"),
    )


class ApprovalRecord(Base):
    """审批记录 — HITL approval 的可查询、可分页持久化(替代扫 session.events JSONB)。"""
    __tablename__ = "approval_records"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # shortuuid
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, default="")
    interrupt_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, default="")
    tool_args: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), default=dict
    )
    tool_call_id: Mapped[Optional[str]] = mapped_column(Text, default=None, nullable=True)
    tool_result: Mapped[Optional[str]] = mapped_column(Text, default=None, nullable=True)
    parent_agent: Mapped[str] = mapped_column(Text, default="Lead")
    subagent_type: Mapped[Optional[str]] = mapped_column(Text, default=None, nullable=True)
    subagent_instance_id: Mapped[Optional[str]] = mapped_column(Text, default=None, nullable=True)
    initiator_user_id: Mapped[str] = mapped_column(Text, default="")
    approver_user_id: Mapped[Optional[str]] = mapped_column(Text, default=None, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(Text, default=None, nullable=True)
    original_request_message: Mapped[str] = mapped_column(Text, default="")
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/decided/auto_approved
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    decided_at: Mapped[Optional[int]] = mapped_column(BigInteger, default=None, nullable=True)
    __table_args__ = (
        Index("ix_approval_records_session_created", "session_id", "created_at"),
        Index("ix_approval_records_status", "status"),
        Index("ix_approval_records_initiator", "initiator_user_id"),
        Index("ix_approval_records_interrupt", "interrupt_id"),
    )


class Model(Base):
    __tablename__ = "models"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(Text, default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(Text, default="")
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user_id: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class BlockedSkill(Base):
    __tablename__ = "blocked_skills"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, default="")
    skill_name: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("user_id", "skill_name", name="uq_blocked_skills_user_skill"),)


class TaskSettings(Base):
    """Per-user task execution settings (keyed by user_id)."""
    __tablename__ = "task_settings"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # user_id
    agent_stream_timeout: Mapped[int] = mapped_column(Integer, default=0)
    sandbox_exec_timeout: Mapped[int] = mapped_column(Integer, default=0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_reserve: Mapped[int] = mapped_column(Integer, default=0)
    max_history_rounds: Mapped[int] = mapped_column(Integer, default=0)
    max_output_chars: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class IMUserBinding(Base):
    __tablename__ = "im_user_bindings"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    platform_user_id: Mapped[str] = mapped_column(Text, default="")
    platform_union_id: Mapped[str] = mapped_column(Text, default="")
    agent_user_id: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_im_binding_platform_user"),
        Index("ix_im_binding_platform_agent", "platform", "agent_user_id", "status"),
    )

class IMChatSession(Base):
    __tablename__ = "im_chat_sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    platform_chat_id: Mapped[str] = mapped_column(Text, default="")
    agent_session_id: Mapped[str] = mapped_column(Text, default="")
    agent_user_id: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        Index("ix_im_chat_lookup", "platform", "platform_chat_id", "agent_user_id", "status"),
        Index("ix_im_chat_updated_at", "updated_at"),
    )


class IMessageDedup(Base):
    __tablename__ = "im_message_dedup"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    message_id: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("platform", "message_id", name="uq_im_dedup_platform_msg"),)


class IMSystemSetting(Base):
    __tablename__ = "im_system_settings"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class WeChatBridgeState(Base):
    __tablename__ = "wechat_bridge_state"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Device(Base):
    """EMS 设备表。"""
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # DEV-<8hex>
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)  # battery/inverter/meter
    status: Mapped[str] = mapped_column(String(32), default="offline")  # offline/pending_online/online
    network_config: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), default=dict
    )  # {ip_address, protocol, port, configured_at}
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (Index("ix_devices_device_type", "device_type"),)


class PcsDevice(Base):
    """PCS 变流器专属配置表 — 外键关联 devices.id。"""
    __tablename__ = "pcs_devices"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # PCS-<8hex>
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    rated_power_kw: Mapped[float] = mapped_column(default=500.0)
    rated_reactive_kvar: Mapped[float] = mapped_column(default=100.0)
    ac_voltage_v: Mapped[float] = mapped_column(default=380.0)
    dc_voltage_v: Mapped[float] = mapped_column(default=750.0)
    rated_efficiency: Mapped[float] = mapped_column(default=0.92)
    min_soc: Mapped[float] = mapped_column(default=0.10)
    max_soc: Mapped[float] = mapped_column(default=0.90)
    override_mode: Mapped[Optional[str]] = mapped_column(String(16), default=None)
    override_power_kw: Mapped[Optional[float]] = mapped_column(default=None)
    override_expires_at: Mapped[int] = mapped_column(BigInteger, default=0)
    battery_id: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("device_id", name="uq_pcs_devices_device_id"),)


class BatteryDevice(Base):
    """电池专属配置表 — 外键关联 devices.id。"""
    __tablename__ = "battery_devices"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # BAT-<8hex>
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    rated_capacity_kwh: Mapped[float] = mapped_column(default=2000.0)
    rated_voltage_v: Mapped[float] = mapped_column(default=750.0)
    rated_current_a: Mapped[float] = mapped_column(default=300.0)
    soc: Mapped[float] = mapped_column(default=0.50)
    soh: Mapped[float] = mapped_column(default=0.925)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("device_id", name="uq_battery_devices_device_id"),)


class PcsSnapshot(Base):
    """PCS 时序快照表 — 每次 tick 一行。"""
    __tablename__ = "pcs_snapshots"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pcs_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_power_kw: Mapped[float] = mapped_column(default=0.0)
    reactive_power_kvar: Mapped[float] = mapped_column(default=0.0)
    mode: Mapped[str] = mapped_column(String(16), default="standby")
    ac_voltage_v: Mapped[float] = mapped_column(default=380.0)
    dc_voltage_v: Mapped[float] = mapped_column(default=750.0)
    efficiency: Mapped[float] = mapped_column(default=0.92)
    status: Mapped[str] = mapped_column(String(16), default="standby")
    __table_args__ = (Index("ix_pcs_snapshots_pcs_ts", "pcs_id", "timestamp"),)


class BatterySnapshot(Base):
    """电池时序快照表 — 每次 tick 一行。"""
    __tablename__ = "battery_snapshots"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    battery_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    soc: Mapped[float] = mapped_column(default=0.50)
    voltage: Mapped[float] = mapped_column(default=750.0)
    current_a: Mapped[float] = mapped_column(default=0.0)
    temperature: Mapped[float] = mapped_column(default=28.0)
    mode: Mapped[str] = mapped_column(String(16), default="standby")
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("ix_battery_snapshots_bat_ts", "battery_id", "timestamp"),)


# ── 场站级数据(光伏 / 关口表 / 天气 / 电价 / 日电量 / 站配置) ──────


class PvDevice(Base):
    """光伏阵列配置表 - 外键关联 devices.id。"""
    __tablename__ = "pv_devices"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # PV-<8hex>
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    rated_capacity_kwp: Mapped[float] = mapped_column(default=500.0)  # 峰值功率 kWp
    orientation_deg: Mapped[float] = mapped_column(default=180.0)     # 方位角(南=180)
    tilt_deg: Mapped[float] = mapped_column(default=30.0)             # 倾角
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("device_id", name="uq_pv_devices_device_id"),)


class PvSnapshot(Base):
    """光伏时序快照表 - 每次 tick 一行。"""
    __tablename__ = "pv_snapshots"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pv_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation_kw: Mapped[float] = mapped_column(default=0.0)
    irradiance: Mapped[float] = mapped_column(default=0.0)   # W/m²
    temperature: Mapped[float] = mapped_column(default=25.0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    __table_args__ = (Index("ix_pv_snapshots_pv_ts", "pv_id", "timestamp"),)


class MeterDevice(Base):
    """关口表/电表配置表 - 外键关联 devices.id。"""
    __tablename__ = "meter_devices"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # MET-<8hex>
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    rated_kw: Mapped[float] = mapped_column(default=2000.0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("device_id", name="uq_meter_devices_device_id"),)


class MeterSnapshot(Base):
    """关口表时序快照表 - 每次 tick 一行。

    import_kw:从电网受电(下网);export_kw:向电网送电(上网/逆流);
    load_kw:场站实测负荷;reverse_flow:逆流标记;rolling_demand_kw:滚动 15min 需量;
    total_active_power_kw:关口表一级有功功率(带符号,正=下网/负=上网,= import_kw - export_kw)。
    """
    __tablename__ = "meter_snapshots"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    meter_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    import_kw: Mapped[float] = mapped_column(default=0.0)
    export_kw: Mapped[float] = mapped_column(default=0.0)
    load_kw: Mapped[float] = mapped_column(default=0.0)
    reverse_flow: Mapped[bool] = mapped_column(Boolean, default=False)
    rolling_demand_kw: Mapped[float] = mapped_column(default=0.0)
    frequency: Mapped[float] = mapped_column(default=50.0)
    power_factor: Mapped[float] = mapped_column(default=0.95)
    total_active_power_kw: Mapped[float] = mapped_column(default=0.0)
    __table_args__ = (Index("ix_meter_snapshots_met_ts", "meter_id", "timestamp"),)


class WeatherSnapshot(Base):
    """气象时序快照表 - 每次 tick 一行(场站级,无设备)。"""
    __tablename__ = "weather_snapshots"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    irradiance: Mapped[float] = mapped_column(default=0.0)   # W/m²
    temperature: Mapped[float] = mapped_column(default=25.0)  # 环境温度 ℃
    cloud_cover: Mapped[float] = mapped_column(default=0.0)   # 0-1 云量
    wind_speed: Mapped[float] = mapped_column(default=2.0)    # m/s
    __table_args__ = (Index("ix_weather_snapshots_ts", "timestamp"),)


class ElectricityTariff(Base):
    """权威电价时段表 - 按区域 + 时段类型(尖/峰/平/谷)。"""
    __tablename__ = "electricity_tariffs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    region: Mapped[str] = mapped_column(String(32), default="default")
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)  # sharp/peak/flat/valley
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)      # 0-23
    end_hour: Mapped[int] = mapped_column(Integer, nullable=False)        # 1-24
    energy_price: Mapped[float] = mapped_column(default=0.0)  # 元/kWh
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        UniqueConstraint("region", "period_type", "start_hour", name="uq_tariff_region_period_start"),
        Index("ix_tariff_region", "region"),
    )


class DailyEnergyRecord(Base):
    """日充放电电量与收益 - 每天一条,tick 累计。"""
    __tablename__ = "daily_energy_records"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    charge_kwh: Mapped[float] = mapped_column(default=0.0)
    discharge_kwh: Mapped[float] = mapped_column(default=0.0)
    revenue: Mapped[float] = mapped_column(default=0.0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("date", name="uq_daily_energy_date"),)


class ChargeSchedule(Base):
    """充放电调度计划 - 由 dispatch_planning 的调度优化生成,HITL 审批后 active,驱动 PCS tick。

    单电站每日可有多条;同一 target_date 仅一条 status='active'(下发时旧 active→superseded)。
    intervals: DispatchInterval[24] JSONB,每条 {hour,mode,power_kw,power_ratio,
              soc_target_pct,period,tariff_price}(执行/监测/收益三类字段)。
    objective: 生成该计划的 summary 快照(grid_cost/demand_charge/...),供解释与对比。
    """
    __tablename__ = "charge_schedules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)               # SCH-<8hex>
    target_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(16), default="draft")      # draft|active|superseded
    # 已废弃:旧「四方视角」标签,仅历史行保留;新代码读写 strategies
    perspective: Mapped[str] = mapped_column(String(16), default="")
    strategies: Mapped[list] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), default=list
    )
    intervals: Mapped[list] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), default=list
    )
    objective: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), default=dict
    )
    created_by: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        Index("ix_charge_schedules_date_status", "target_date", "status"),
    )


class StationConfig(Base):
    """场站级配置 - 单行(region + 申报需量 / 防逆流设定 / 固定电费)。"""
    __tablename__ = "station_config"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # 固定 id "STN-DEFAULT"
    region: Mapped[str] = mapped_column(String(32), default="default")
    contract_demand_kw: Mapped[float] = mapped_column(default=1000.0)            # 申报需量
    anti_reverse_export_setpoint_kw: Mapped[float] = mapped_column(default=50.0)  # 防逆流允许上限
    capacity_price_yuan_per_kw_month: Mapped[float] = mapped_column(default=30.0)  # 基本电费(容量)
    demand_price_yuan_per_kw_month: Mapped[float] = mapped_column(default=40.0)    # 基本电费(需量)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


async def migrate_legacy() -> None:
    """启动期幂等迁移：把早期 science* 列/索引/角色重命名为 agent*。

    历史命名（ScienceClaw 时代）→ 通用 Agent 命名的原地重命名：
      - IMUserBinding.science_user_id  → agent_user_id
      - IMChatSession.science_session_id → agent_session_id
      - IMChatSession.science_user_id   → agent_user_id
      - 索引 ix_im_binding_platform_science → ix_im_binding_platform_agent
      - postgres 角色 scienceone → agentone
    纯元数据操作，不触碰行数据；重复执行安全（旧列/旧角色不存在即跳过）。
    """
    from sqlalchemy import text
    from emsclaw_backend.db.session import AsyncSessionLocal

    # 列/索引重命名（旧列/旧索引不存在则跳过 —— 幂等）
    statements = [
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='im_user_bindings' AND column_name='science_user_id'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='im_user_bindings' AND column_name='agent_user_id'
            ) THEN
                ALTER TABLE im_user_bindings RENAME COLUMN science_user_id TO agent_user_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='im_chat_sessions' AND column_name='science_session_id'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='im_chat_sessions' AND column_name='agent_session_id'
            ) THEN
                ALTER TABLE im_chat_sessions RENAME COLUMN science_session_id TO agent_session_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='im_chat_sessions' AND column_name='science_user_id'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='im_chat_sessions' AND column_name='agent_user_id'
            ) THEN
                ALTER TABLE im_chat_sessions RENAME COLUMN science_user_id TO agent_user_id;
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes WHERE indexname='ix_im_binding_platform_science'
            )
            AND NOT EXISTS (
                SELECT 1 FROM pg_indexes WHERE indexname='ix_im_binding_platform_agent'
            ) THEN
                ALTER INDEX ix_im_binding_platform_science RENAME TO ix_im_binding_platform_agent;
            END IF;
        END $$;
        """,
        """
        -- 角色迁移：scienceone → agentone。
        -- 仅当 scienceone 存在且 agentone 不存在时才改名（避免重名冲突；
        -- 若 agentone 已存在则认为迁移已完成，跳过）。
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scienceone')
               AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='agentone') THEN
                ALTER ROLE scienceone RENAME TO agentone;
            END IF;
        END $$;
        """,
    ]
    try:
        async with AsyncSessionLocal() as session:
            for stmt in statements:
                await session.execute(text(stmt))
            await session.commit()
    except Exception:
        # 迁移失败不应阻断启动；列重命名会在首次实际访问时暴露问题
        import logging
        logging.getLogger(__name__).warning(
            "migrate_legacy failed (will retry next boot)", exc_info=True
        )
