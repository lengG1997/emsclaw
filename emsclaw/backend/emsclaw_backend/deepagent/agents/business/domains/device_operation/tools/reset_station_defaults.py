"""reset_station_defaults 工具 - 重置场站为标准默认配置(1MW/2MWh + 2MWp)。

清空现有 PCS/电池/光伏/关口表/电价/站配置及全部快照,重建标准设备模型:
  2×500kW PCS(并机 1MW,eff 0.90)+ 2×1000kWh 电池(750V×667A≈500kW,0.5C)
  + 2MWp 光伏 + 2000kW 关口表 + 申报需量 1000kW/防逆流 50kW + 8 时段 TOU。

重建后立即回灌 7 天历史快照(1 分钟一帧,10080 帧),让总览页
「关口表能量流 / 有功功率 / 日电量与收益」三图表立即显示曲线,无需等 beat tick 累积。

破坏性写操作,经 device_operation 域 HITL 审批后执行。
"""
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from emsclaw_backend.mapper.device_mapper import DeviceMapper
from emsclaw_backend.mapper.pcs_mapper import PcsMapper
from emsclaw_backend.mapper.station_mapper import StationMapper


class ResetStationDefaultsArgs(BaseModel):
    confirm: bool = Field(
        ...,
        description="必须传 true 确认清空并重建场站默认设备配置;false 或缺省则拒绝执行",
    )


@tool(args_schema=ResetStationDefaultsArgs)
def reset_station_defaults(confirm: bool) -> str:
    """重置场站为标准默认设备配置(2×500kW PCS + 2×1000kWh 电池 + 2MWp 光伏 + 关口表 + 站配置 + 电价时段 + 7 天历史快照)。

    清空并重建场站默认配置,然后回灌 7 天历史快照让总览页立即显示曲线。
    """
    if not confirm:
        return _err("未确认(confirm!=true),已取消重置。")
    try:
        pcs_mapper = PcsMapper()
        stn_mapper = StationMapper()
        dev_mapper = DeviceMapper(session_factory=pcs_mapper._sf)

        # 1. 清空快照 + 配置表(顺序:先快照后配置,避免外键)
        cleared = _purge_all(pcs_mapper, stn_mapper, dev_mapper)

        # 2. 重建默认设备(ensure_seeded 检测表空才建,清空后正好触发)
        from emsclaw_backend.service.pcs_service import PcsService
        from emsclaw_backend.service.station_service import StationSimService
        pcs_seeded = PcsService(mapper=pcs_mapper).ensure_seeded()
        stn_seeded = StationSimService(mapper=stn_mapper,
                                       pcs_service=PcsService(mapper=pcs_mapper)).ensure_seeded()

        # 3. 回灌 7 天历史快照(1 分钟一帧),让总览页三图表立即有曲线
        pcs_service = PcsService(mapper=pcs_mapper)
        history_seeded = StationSimService(
            mapper=stn_mapper, pcs_service=pcs_service
        ).seed_history(hours=168)

        # 4. 汇总结果
        devices = dev_mapper.find_all()
        device_lines = [
            f"  • {d.name}  类型={d.device_type}  状态={d.status}  ID={d.id}"
            for d in devices
        ]
        return json.dumps({
            "success": True,
            "message": "场站已重置为标准默认配置(含 7 天历史快照)",
            "data": {
                "cleared": cleared,
                "pcs_seeded": pcs_seeded,
                "station_seeded": stn_seeded,
                "history_seeded": history_seeded,
                "device_count": len(devices),
                "devices": device_lines,
            },
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(f"重置失败: {e}")


def _purge_all(pcs_mapper: PcsMapper, stn_mapper: StationMapper,
               dev_mapper: DeviceMapper) -> dict:
    """清空场站/PCS 全部快照与配置表 + 相关 devices。返回各表删除条数。"""
    sf = pcs_mapper._sf
    counts = {}
    # 用裸 SQL 按外键反序删;表名见 db/models.py
    from sqlalchemy import text
    with sf() as s:
        for tbl in (
            "battery_snapshots", "pcs_snapshots",
            "pv_snapshots", "meter_snapshots", "weather_snapshots",
            "daily_energy_records", "electricity_tariffs",
            "battery_devices", "pcs_devices",
            "pv_devices", "meter_devices",
            "station_config",
        ):
            try:
                r = s.execute(text(f'DELETE FROM "{tbl}"'))
                counts[tbl] = r.rowcount or 0
            except Exception:
                # 表不存在(如全新库)跳过
                counts[tbl] = -1
        s.commit()
    # devices 表里 pcs/battery/pv/meter/inverter 全清(garbage 也一并清)
    # 单独 session,避免与上面事务混淆
    with sf() as s:
        for tbl in ("devices",):
            try:
                r = s.execute(text(
                    "DELETE FROM devices WHERE device_type IN "
                    "('pcs','battery','pv','meter','inverter')"
                ))
                counts[tbl] = r.rowcount or 0
            except Exception:
                counts[tbl] = -1
        s.commit()
    return counts


def _err(msg: str) -> str:
    return json.dumps({"success": False, "message": msg, "data": None},
                      ensure_ascii=False, indent=2)
