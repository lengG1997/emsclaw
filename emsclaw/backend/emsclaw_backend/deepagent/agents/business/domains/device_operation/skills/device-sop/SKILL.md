---
name: device-sop
description: EMS 设备录入与配网标准作业流程
---

# 设备管理标准作业流程 (SOP)

## 0. 数据原则（重要，先读）

**全部设备数据由工具内部从数据库自动聚合——无需也不应另行 glob 工作目录、读取 skill 文档或查找配置文件。**

- 设备列表/单个设备详情：调 `list_devices()` / `get_device(device_id=...)` 即拿到完整字段（名称、类型、网络配置、在线状态）
- 站配置（申报需量/防逆流设定/需量电价）：`get_device` 系列工具返回里含站配置；修改用 `set_station_config`
- **禁止** glob `**/*`、glob `/domain-skills/**`、read_file 找设备配置——这些都是工具自取的，agent 找不到也找不到（数据在 DB 不在文件系统）

调用工具即拿到完整现状，基于返回数据组织人话叙述即可。

## 1. 录入新设备
1. 确认设备名称（唯一）与类型（battery / inverter / meter）。
2. 调用 `create_device(name, device_type)`。
3. 成功 → 记录返回的 `device_id`；失败（如重名）→ 如实告知用户。

## 2. 配网（建议在录入后立即进行）
1. 向用户确认 IP 地址、协议（ModbusTCP / MQTT）、可选端口。
2. 调用 `configure_network(device_id, ip_address, protocol, port?)`，device_id 用上一步返回值。
3. 成功 → 设备状态转为 pending_online，告知用户设备已配置待上线。

## 3. 查询
- 列出全部：`list_devices()`；按类型：`list_devices(device_type)`。
- 查单个：`get_device(device_id=...)` 或 `get_device(name=...)`。

## 4. 禁止事项
- 不编造设备 ID 或网络配置。
- 工具返回 `success=false` 时，如实转达 `message`，不伪造成功。
- **不 glob / 不 read_file 找数据**——数据在 DB，由工具自取。
