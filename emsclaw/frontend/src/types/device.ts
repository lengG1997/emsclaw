// 与 backend/schemas.py DeviceDTO 字段对应
export type DeviceType = 'battery' | 'inverter' | 'meter' | 'pcs';
export type DeviceStatus = 'offline' | 'pending_online' | 'online';

export interface NetworkConfig {
  ip_address: string;
  protocol: 'ModbusTCP' | 'MQTT';
  port?: number;
  configured_at: number;
}

export interface Device {
  id: string;
  name: string;
  device_type: DeviceType;
  status: DeviceStatus;
  network_config: NetworkConfig | Record<string, never>;
  created_at: number;
  updated_at: number;
}