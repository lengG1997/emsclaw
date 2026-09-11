import { apiClient, ApiResponse } from './client';
import type { Device, DeviceType } from '@/types/device';

export async function listDevices(deviceType?: DeviceType): Promise<Device[]> {
  const response = await apiClient.get<ApiResponse<Device[]>>('/devices', {
    params: deviceType ? { device_type: deviceType } : undefined,
  });
  return response.data.data;
}

export async function getDevice(deviceId: string): Promise<Device> {
  const response = await apiClient.get<ApiResponse<Device>>(`/devices/${deviceId}`);
  return response.data.data;
}

export async function createDevice(data: { name: string; device_type: DeviceType }): Promise<Device> {
  const response = await apiClient.post<ApiResponse<Device>>('/devices', data);
  return response.data.data;
}

export async function configureDeviceNetwork(
  deviceId: string,
  data: { ip_address: string; protocol: 'ModbusTCP' | 'MQTT'; port?: number },
): Promise<Device> {
  const response = await apiClient.post<ApiResponse<Device>>(`/devices/${deviceId}/network`, data);
  return response.data.data;
}