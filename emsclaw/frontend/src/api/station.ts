import { apiClient, ApiResponse } from './client';
import type {
  StationForecastDay,
  StationOverview,
  StationConfig,
  StationConfigUpdate,
  DemandStatus,
  TariffRow,
  MeterSnapshotPoint,
  DailyEnergy,
} from '@/types/station';

/** 未来 N 天站级负荷/光伏预测(kW) */
export async function getStationForecast(days = 7): Promise<StationForecastDay[]> {
  const r = await apiClient.get<ApiResponse<StationForecastDay[]>>('/station/forecast', {
    params: { days },
  });
  return r.data.data;
}

/** 单日站级负荷/光伏预测(kW)。targetDate: YYYY-MM-DD */
export async function getStationForecastDay(targetDate: string): Promise<StationForecastDay> {
  const r = await apiClient.get<ApiResponse<StationForecastDay>>(
    `/station/forecast/day/${targetDate}`,
  );
  return r.data.data;
}

/** 场站总览聚合(光伏/关口表/气象/今日电量/当前电价/站配置) */
export async function getStationOverview(): Promise<StationOverview> {
  const r = await apiClient.get<ApiResponse<StationOverview>>('/station/overview');
  return r.data.data;
}

/** 关口表时序曲线(进/出口功率/逆流/需量)。from/to: 墙钟秒 */
export async function getStationMeterSnapshots(from: number, to: number): Promise<MeterSnapshotPoint[]> {
  const r = await apiClient.get<ApiResponse<MeterSnapshotPoint[]>>('/station/meter/snapshots', {
    params: { from, to },
  });
  return r.data.data;
}

/** 电价时段表(尖/峰/平/谷) */
export async function getStationTariff(): Promise<TariffRow[]> {
  const r = await apiClient.get<ApiResponse<TariffRow[]>>('/station/tariff');
  return r.data.data;
}

/** 日充放电电量与收益 */
export async function getStationDailyEnergy(days = 7): Promise<DailyEnergy[]> {
  const r = await apiClient.get<ApiResponse<DailyEnergy[]>>('/station/energy/daily', {
    params: { days },
  });
  return r.data.data;
}

/** 需量控制状态 */
export async function getStationDemand(): Promise<DemandStatus> {
  const r = await apiClient.get<ApiResponse<DemandStatus>>('/station/demand');
  return r.data.data;
}

/** 更新站配置(申报需量/防逆流/容量与需量电价)。至少一项;未传字段保持不变。返回更新后配置 */
export async function updateStationConfig(data: StationConfigUpdate): Promise<StationConfig> {
  const r = await apiClient.put<ApiResponse<StationConfig>>('/station/config', data);
  if (r.data.code !== 0) {
    throw new Error(r.data.msg || '站配置更新失败');
  }
  return r.data.data;
}
