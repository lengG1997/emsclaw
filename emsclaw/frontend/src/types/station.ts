// 与 emsclaw_backend/controller/station_controller.py + service/station_service.py 对应
// 站级预测(kW,与场站 tick 同源)

export interface StationForecastDay {
  target_date: string;
  load_kw: number[];       // 24h 负荷预测(kW)
  pv_kw: number[];         // 24h 光伏预测(kW)
  net_load_kw: number[];  // 净负荷 = load - pv(负值=光伏过剩可能逆流)
  load_peak_kw: number;
  pv_peak_kw: number;
  load_energy_kwh: number; // 日用电量(梯形积分)
  pv_energy_kwh: number;   // 日发电量
  pv_rated_kwp: number;
  seasonal_factor: number;
}

// ── 场站总览聚合 GET /station/overview ──

export type TariffPeriodType = 'sharp' | 'peak' | 'flat' | 'valley';

export interface TariffCurrent {
  period_type: TariffPeriodType;
  energy_price: number; // 元/kWh
  start: string; // "HH:00"
  end: string;   // "HH:00"
}

export interface StationConfig {
  id?: string;
  region?: string;
  contract_demand_kw: number;                 // 申报需量
  anti_reverse_export_setpoint_kw: number;    // 防逆流阈值
  capacity_price_yuan_per_kw_month?: number;  // 基本容量电价
  demand_price_yuan_per_kw_month?: number;    // 需量电价
  updated_at?: number;
}

/** 站配置更新入参(PUT /station/config):全可选项,至少传一项;未传字段保持不变 */
export type StationConfigUpdate = Partial<
  Pick<StationConfig,
    | 'contract_demand_kw'
    | 'anti_reverse_export_setpoint_kw'
    | 'capacity_price_yuan_per_kw_month'
    | 'demand_price_yuan_per_kw_month'>
>;

export interface PvSnapshotPoint {
  generation_kw: number;
  irradiance: number;
  temperature: number;
  status: string;
  timestamp?: number;
  [k: string]: unknown;
}

export interface MeterSnapshotPoint {
  timestamp: number;
  import_kw: number;        // 下网(从电网受电)
  export_kw: number;        // 上网(向电网送电)
  load_kw: number;          // 实测负荷
  reverse_flow: boolean;    // 逆流标记
  rolling_demand_kw: number;// 15min 滚动需量
  frequency?: number;
  power_factor?: number;
  total_active_power_kw?: number; // 关口表一级有功(带符号,正=下网/负=上网 = import-export)
}

export interface WeatherSnapshotPoint {
  irradiance: number;
  temperature: number;
  cloud_cover: number;
  wind_speed: number;
  timestamp?: number;
}

export interface DailyEnergy {
  date: string;
  charge_kwh: number;
  discharge_kwh: number;
  revenue: number;
  updated_at?: number;
}

export interface StationOverview {
  pv: PvSnapshotPoint | null;
  pv_rated_kwp: number;
  meter: MeterSnapshotPoint | null;
  weather: WeatherSnapshotPoint | null;
  energy_today: DailyEnergy | null;
  tariff_current: TariffCurrent | null;
  station_config: StationConfig | null;
}

export interface DemandStatus {
  current_demand_kw: number;
  max_demand_today_kw: number;
  contract_demand_kw: number;
  demand_price_yuan_per_kw_month: number;
  demand_ratio: number;
}

export interface TariffRow {
  id?: string;
  region?: string;
  period_type: TariffPeriodType;
  start_hour: number;
  end_hour: number;
  energy_price: number;
}

export const TARIFF_PERIOD_LABEL: Record<TariffPeriodType, string> = {
  sharp: '尖',
  peak: '峰',
  flat: '平',
  valley: '谷',
};
