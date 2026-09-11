import { apiClient, ApiResponse } from './client';
import type { BatterySnapshot, ChargeSchedule, PcsStatusItem, PcsSnapshot, PcsMode } from '@/types/pcs';

export async function listPcs(): Promise<PcsStatusItem[]> {
  const r = await apiClient.get<ApiResponse<PcsStatusItem[]>>('/pcs');
  return r.data.data;
}

export async function getPcsSnapshots(
  pcsId: string,
  from: number,
  to: number,
): Promise<PcsSnapshot[]> {
  const r = await apiClient.get<ApiResponse<PcsSnapshot[]>>(
    `/pcs/${pcsId}/snapshots`,
    { params: { from, to } },
  );
  return r.data.data;
}

export async function setPcsMode(
  pcsId: string,
  body: { mode: PcsMode; power_kw: number; expires_at: number },
): Promise<{ pcs_id: string; override_mode: PcsMode | null }> {
  const r = await apiClient.post<ApiResponse<{ pcs_id: string; override_mode: PcsMode | null }>>(
    `/pcs/${pcsId}/mode`,
    body,
  );
  return r.data.data;
}

export async function getChargeSchedule(date?: string): Promise<ChargeSchedule> {
  const r = await apiClient.get<ApiResponse<ChargeSchedule>>('/pcs/schedule', {
    params: date ? { date } : undefined,
  });
  return r.data.data;
}

export async function getBatterySnapshots(
  pcsId: string,
  from: number,
  to: number,
): Promise<BatterySnapshot[]> {
  const r = await apiClient.get<ApiResponse<BatterySnapshot[]>>(
    `/pcs/${pcsId}/battery-snapshots`,
    { params: { from, to } },
  );
  return r.data.data;
}
