// 与 emsclaw_backend/entity/pcs.py 对应
export type PcsMode = 'charge' | 'discharge' | 'standby' | 'auto';

export interface PcsDevice {
  id: string;
  device_id: string;
  rated_power_kw: number;
  rated_reactive_kvar: number;
  ac_voltage_v: number;
  dc_voltage_v: number;
  rated_efficiency: number;
  min_soc: number;
  max_soc: number;
  override_mode: PcsMode | null;
  override_power_kw: number | null;
  override_expires_at: number;
  battery_id: string | null;
  created_at: number;
  updated_at: number;
}

export interface BatteryDevice {
  id: string;
  device_id: string;
  rated_capacity_kwh: number;
  rated_voltage_v: number;
  rated_current_a: number;
  soc: number;
  soh: number;
  cycle_count: number;
  created_at: number;
  updated_at: number;
}

export interface PcsSnapshot {
  id: string;
  pcs_id: string;
  timestamp: number;
  active_power_kw: number;
  reactive_power_kvar: number;
  mode: PcsMode;
  ac_voltage_v: number;
  dc_voltage_v: number;
  efficiency: number;
  status: string;
}

export interface BatterySnapshot {
  id: string;
  battery_id: string;
  timestamp: number;
  soc: number;
  voltage: number;
  current_a: number;
  temperature: number;
  mode: PcsMode;
  cycle_count: number;
}

export interface PcsStatusItem {
  pcs: PcsDevice;
  battery: BatteryDevice | null;
  latest_pcs_snapshot: PcsSnapshot | null;
  latest_battery_snapshot: BatterySnapshot | null;
}

export const PCS_MODE_LABEL: Record<PcsMode, string> = {
  charge: '充电',
  discharge: '放电',
  standby: '待机',
  auto: '自动',
};

// 今日充放电调度计划(对应 PcsService.get_charge_schedule)
export interface ChargeScheduleSegment {
  start_hour: number;
  end_hour: number;
  start: string;   // "HH:00"
  end: string;     // "HH:00"
  mode: PcsMode;
  label: string;   // 充电(低谷) / 放电(高峰) / 放电(尖峰) / 待机
  power_ratio_lo: number;
  power_ratio_hi: number;
  power_kw: number; // 按在线 PCS 总额定功率 × ratio 上界换算的展示功率
}

export interface ChargeSchedule {
  date: string; // "YYYY-MM-DD"
  total_rated_power_kw: number;
  strategies: string[] | null;
  status: string;
  schedule_id: string | null;
  created_by: string | null; // session_id(=thread_id),可用于跳转到创建该计划的会话
  segments: ChargeScheduleSegment[];
}
