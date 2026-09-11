# 场站智能值守 —— 异常自动巡检与处置闭环

> 状态：**待评审**（仅有设计，无代码）
> 一句话：**给场站配一个 24 小时值班员——它自己盯着，发现不对劲主动告诉你，并给出怎么处理，你点头它才动手。**

---

## 一、先看一个场景（这就是需求）

**现在的状态**：场站没人盯。需量快超了、白天在往里送电、电池 SOC 快见底了——**只有等你主动问，系统才会告诉你**。而且告诉你的方式是甩几个数字：

```
【需量控制】
• 当前需量: 1180.0kW
• 申报需量: 1250.0kW        ← 你看到这个，然后呢？
• 状态: 正常
```

**本该有的状态**：早上 9 点，你手机收到一条消息：

> ⚠️ **注意** ｜ 场站 A
> **今晚 18:00-20:00 尖峰段，电池电量可能不够**
> 现在 SOC 42%，按当前策略到 18 点只能充到 68%。尖峰放电预计只能撑 40 分钟，剩下 80 分钟要按 1.2 元/度买电。
> **建议**：把 13:00-15:00 的平段充电功率从 200kW 提到 400kW，能多充 400 度。按尖峰电价算，今晚少花约 480 元。
> ［采纳这个建议］ ［先不动］

**差别在哪**：现在只回答"是什么"，没人回答"**会怎样**"和"**怎么办**"。这个需求补的就是后两者。

---

## 二、现状：为什么现在做不到

### 2.1 全是"被动查询"，没有"主动值守"

系统里有 12 个场站数据工具（`get_demand_status` / `get_meter_status` / `get_storage_status` / `get_pv_status` / `get_station_overview` …），但它们**全部需要有人先问一句**才会跑。

`get_demand_status` 的实现很典型（`station_data/tools/get_demand_status.py:12-21`）——把数字读出来、超过阈值就标一个旗：

```python
risk = "⚠️ 超申报需量" if d["current_demand_kw"] > d["contract_demand_kw"] else "正常"
```

**标完旗就结束了。没有"接下来怎么办"。**

### 2.2 有分析能力，但是"一次性的、要人问的、只罗列不归因"

`station-analysis` skill（`station_data/skills/station-analysis/SKILL.md:53-62`）能做场站现状报告，第 3 节叫「异常与风险」——**但它做的是罗列**：

> 3. **异常与风险**:逆流 / 超需量 / SOC 越限 / 设备离线 / 高温,标注数值与时段;无则明说「运行正常」。

罗列"逆流 300kW"和回答"为什么会逆流、该怎么办"是两件事。前者是读数，后者是**诊断 + 决策**。

### 2.3 有通知通道，但只用来通知"任务跑完了"

- **站内实时通道**：`notifications.py:52-57` 的 `publish(event_type, data)` 把事件 fan out 给所有前端 SSE 连接。
- **外部通道**：飞书 webhook，`task-service/app/tasks.py:71-127` 的 `notify_task_started` / `notify_task_success` / `notify_task_failed`。
- **前端设置页**（`settings/NotificationSettings.vue`）里能配通知渠道，但选项只有两个：`Notify on start` / `Notify on finish`（`locales/zh.ts:515-516`）——**都是"任务"通知，没有一个"场站异常"通知。**

### 2.4 空白是干净的：全仓 0 命中

```bash
python <tsd-bridge> grep "健康|巡检|告警|预警|寿命" --root emsclaw --include "*.py"
# → 命中的全是 logger.warning（日志），以及 main.py:117 的 /health（服务健康检查，不是设备）
```

前端也一样：`StationOverviewPage.vue:189` 提到了"红点=逆流告警"，但那只是**图表上画一个红点**，不是告警系统。

> **小结**：读数据的能力很全，通知通道有了，分析框架也有了——**缺的是把它们串成一个"不停歇的闭环"那一层**。

---

## 三、为什么这个需求必须用工作流

这是核心论证。四个理由，前两个是决定性的。

### 3.1 理由一：告警**不是一次性判断**，它有生命周期，需要跨轮记忆

一个真实告警的状态是这样的：

```
首次触发 ──→ 持续存在（别重复喊）──→ 人工确认 ──→ 执行处置 ──→ 复检
   │              │                              │
   │              └─→ 1 小时没处理 ──→ 升级严重度 │
   │                                             │
   └───────────→ 自己恢复了 ──→ 自动关闭 ────────┘
```

关键点在于**状态要跨轮保持**：

| 行为 | 需要的记忆 | cron + 阈值判断能做吗 |
|---|---|---|
| 同一异常别每分钟喊一次 | 上次喊过什么、什么时候 | ❌ |
| 持续 1 小时没处理要升级 | 首次触发时间 | ❌ |
| 恢复正常要自动关闭并告知 | 之前是否处于告警态 | ❌ |
| 不能重复生成同一个处置方案 | 上次生成过什么、结果如何 | ❌ |

**这正是 LangGraph 的 `StateGraph` + checkpointer 的用途**：状态持久化，每次运行读到上次的状态再决定这次做什么。**cron 脚本没有"上一次"这个概念**（除非自己造一张表 + 一堆 if，那就是在手工实现图的状态机）。

### 3.2 理由二：处置要**人工审批 + 执行 + 复检**，这是一个闭环

生成的建议不能自动执行——它会改储能运行方式，属于影响硬件的动作。所以链路是：

```
生成处置方案 → 人工审批（interrupt）→ 执行 → 复检 → 没解决就重新诊断
```

`interrupt` 提供"暂停→持久化→恢复"，**执行后回到检测节点复检**是图上的**环**。用顺序代码写"停下来等人、人批了继续、跑完回头再看一眼"，只能靠轮询数据库状态字段硬凑——那又是一张自造的图。

### 3.3 理由三：诊断是**分叉的**，不是一条直线

同一个现象，原因不同，处置完全不同。以"需量快超了"为例：

```
需量快超了
├─ 负荷本身涨了（生产加急）      → 储能提前放电削峰
├─ 光伏今天不出力（阴雨）        → 提高充电频次、调整时段
├─ 储能没按计划充上电（SOC 低）  → 检查计划执行
├─ 今天压根没下发计划            → 生成并下发计划
└─ 设备离线导致无法放电          → 通知运维，无法自动处置
```

**"逐个排除可能原因"就是分支**，这是图最自然的表达。硬塞进一个函数会变成深层嵌套的 if-else，且每加一个维度就要改主流程。

### 3.4 理由四：现有定时能力**必然过 LLM**，而巡检应该是确定性的

`task-service` 里所有"AI 任务"只有一条路径：HTTP 调后端 `/api/v1/chat`，把一段 prompt 交给 Lead Agent（`task-service/app/tasks.py:46-68` 的 `_run_chat_sync`；`:189` 的收益报告就是这么干的）。

这意味着**每 15 分钟巡检一次 = 每 15 分钟跑一轮完整 agent 循环**。而巡检的大部分工作是**纯数值比对**（需量 vs 申报值、SOC vs 上下限、设备状态是否 online）——不需要 LLM，也不该为它付 token。

**巡检要的是一条绕过 `/api/v1/chat` 的确定性入口**（见 §6.1）。

> **一句话总结**：告警生命周期、审批执行复检闭环、诊断分叉、确定性入口——**这四件事恰好是"工作流"的定义，也恰好是"定时任务 + 一个工具"做不到的部分。**

---

## 四、和现有能力划清界限

这是必须讲清的一节，避免"这不是已经有 XXX 了吗"。

| 维度 | `station-analysis`（已有） | `get_schedule_status`（已有） | **智能值守（本设计）** |
|---|---|---|---|
| 触发 | 用户问 | 用户问 | **定时自动（15min）** |
| 范围 | 全站看一遍现状 | 只看计划执行偏差 | 持续跟踪**多个维度** |
| 记忆 | 无，每次从零 | 无，只看当前小时 | **告警生命周期（去重/升级/恢复）** |
| 输出 | 罗列异常 + 数值 | 偏差百分比 + 是否跟得上 | **归因 + 分级 + 处置方案** |
| 能否动作 | 只读，不下发 | 只读 | **可执行（审批后）** |
| 闭环 | 无 | 无 | **检测→处置→复检→再检测** |

**复用而非重写**：

- `get_schedule_status` 的偏差判定（`on_track`，`tools/get_schedule_status.py:54-56`）**直接作为巡检的一个维度**，不重造。
- `station-analysis` 的异常清单（逆流/超需量/SOC 越限/设备离线/高温）**直接作为巡检维度清单**，不重造。
- 处置方案生成**调用求解器**（`optimize_dispatch` / `solver`），不重造优化逻辑。
- 审批走**现有 HITL 机制**，不重造审批。

**新增的是"串起来"的那一层**：定时巡检 → 状态维护 → 归因 → 方案 → 审批 → 执行 → 复检。

---

## 五、图设计

### 5.1 状态 schema（草案）

```python
class PatrolState(TypedDict):
    # ── 本轮触发 ──
    trigger: Literal["patrol", "confirm"]   # 定时巡检 / 用户确认后执行
    run_ts: int
    session_id: str                          # 处置挂在哪条会话上

    # ── 巡检结果 ──
    findings: list[dict]      # [{kind, severity, evidence, dimension}]
    open_alerts: list[dict]   # 本次运行后仍处于 active 的告警（从库里读）

    # ── 告警状态流转（跨轮记忆的核心）──
    new_alerts: list[str]      # 本轮首次出现 → 需要播报
    persisted_alerts: list[str]  # 上轮已有且仍存在 → 只计数，不重复播报
    escalated_alerts: list[str]  # 超过阈值未处理 → 升级
    recovered_alerts: list[str]  # 上轮有、本轮消失 → 自动关闭并播报

    # ── 归因与处置 ──
    diagnosis: dict            # {alert_id: {cause, confidence, basis}}
    proposal: dict | None      # 处置方案（含求解器原始返回，可追溯）
    proposal_generated_for: list[str]  # 已生成过方案的告警，避免重复生成

    # ── 审批与执行 ──
    approval_decision: Literal["approve", "reject", "pending"]
    execution_result: dict | None
    verification: dict | None  # 复检结果
```

### 5.2 图形态

```
        ┌─── celery beat（每 15 min，不经 LLM）───┐
        ▼                                        │
  ┌───────────┐                                  │
  │ scan      │ 按维度并行检查（需量/逆流/SOC/设备/计划/温度）
  └─────┬─────┘
        ▼
  ┌───────────┐
  │ classify  │ 定级：提示 / 注意 / 严重
  └─────┬─────┘
        ▼
  ┌───────────┐   ★ 跨轮状态比对：新增 / 持续 / 升级 / 恢复
  │ reconcile │
  └─────┬─────┘
        │
    无新问题 ──────────→ 只做恢复播报 ──→ END
        │有需处置的问题
        ▼
  ┌───────────┐
  │ diagnose  │ 逐层排查原因（分叉诊断树）
  └─────┬─────┘
        ▼
  ┌───────────┐
  │ propose   │ 调求解器生成具体处置计划 → 落 draft（待审批）
  └─────┬─────┘
        ▼
  ┌───────────┐
  │ notify    │ SSE 站内 + 飞书 webhook
  └─────┬─────┘
        │
        ▼
   ╔═════════════════════╗
   ║ interrupt：人工审批 ║ ←── 用户点「采纳」
   ╚═════════┬═══════════╝
      拒绝──┤──批准
        ▼   ▼
    记录并关闭 ┌───────────┐
              │ execute   │ 落 active 计划（复用 apply_schedule 语义）
              └─────┬─────┘
                    ▼
              ┌───────────┐
              │ verify    │ 复检：问题解决了吗？
              └─────┬─────┘
                解决─┤─未解决
                 ▼   ▼
              关闭告警 回到 diagnose（最多 N 次，防死循环）
```

### 5.3 六个巡检维度（全部基于已有数据）

| 维度 | 判断依据 | 已有数据来源 |
|---|---|---|
| **需量** | 滚动需量 vs 申报需量；接近（如 >90%）即预警 | `MeterSnapshot.rolling_demand_kw`（`models.py:333`）、`StationConfig.contract_demand_kw` |
| **逆流** | `reverse_flow` 为真，或 `export_kw` 超防逆流设定 | `MeterSnapshot.reverse_flow`（`:332`）、`station_config.anti_reverse_export_setpoint_kw`（`:418`） |
| **SOC 前瞻** | 当前 SOC + 未来时段需求 → 判断尖峰段是否够用 | `BatterySnapshot.soc`、`_tariff_24h()`（`_shared.py:54-65`） |
| **设备在线** | `Device.status != online` | `models.py:201` |
| **计划执行** | **复用** `get_schedule_status` 的 `on_track` | `tools/get_schedule_status.py:54-56` |
| **数据陈旧** | 快照时间戳距今过久（tick 挂了） | 各 snapshot 表的 `timestamp` |

**关于温度维度要如实说明**：`BatterySnapshot.temperature` 由公式生成（`pcs_service.py:170`）——`28 + 功率/额定 × 5 + 随机扰动`，**最高约 34°C，永远不会超阈值**。所以温度维度可以接进来，但在当前模拟数据下**永不会触发**。这一点必须写清，不能假装它能用。

**SOC 前瞻维度是这里最有价值的一个**：它是唯一一个**"看未来"**而非"看当下"的检查——现在所有工具都是读当前值，没有"按当前趋势推演到尖峰段会怎样"的能力。这也正是 §一 那个场景的核心。

---

## 六、入口、触发与落位

### 6.1 触发方式：绕开 `/api/v1/chat` 的确定性入口

| 项 | 做法 |
|---|---|
| 定时 | `task-service/app/celery_app.py` 的 `beat_schedule` 加一条 `patrol-scan`（每 15 分钟） |
| 触发路径 | Celery task → HTTP `POST /api/v1/patrol/run`（**新端点，直接跑图，不经过 `/api/v1/chat`、不经过 LLM**） |
| 用户确认 | 前端告警卡片点「采纳」→ `POST /api/v1/patrol/{alert_id}/decide` → resume 图 |

**为什么要新端点而不是复用 `/api/v1/chat`**：现有路径会把 prompt 交给 Lead Agent 走一轮 LLM 推理（`tasks.py:46-68`）。巡检的价值在于"便宜、稳定、不歇"，套进 LLM 循环就丢了这个优势。**这是本设计对现有基础设施的唯一一处"新增通道"，也是关键的一处。**

同时保留对话路径：用户在对话里问"场站有什么问题吗"仍走 Lead → `station-analysis`（已有能力不受影响）。

### 6.2 文件落位（建议）

```
emsclaw/backend/deepagent/workflows/          # 新建：非对话工作流，与 agents/ 平级
  └── patrol/
      ├── graph.py        # StateGraph 组装
      ├── state.py        # PatrolState
      ├── scan.py         # 六维巡检（纯函数，可单测）
      ├── diagnose.py     # 归因诊断树
      └── rules.py        # 阈值与分级规则（可配置，禁止 LLM 生成）
emsclaw/backend/route/patrol.py               # 新路由：/api/v1/patrol/*
emsclaw/backend/mapper/alert_mapper.py
emsclaw/backend/service/patrol_service.py
emsclaw/task-service/app/tasks.py             # 新增 patrol_scan 任务
emsclaw/task-service/app/celery_app.py        # 注册 beat_schedule
emsclaw/tests/test_patrol_*.py
```

`workflows/` **不注册到 `AgentRegistry`**，因此不出现在 Lead 的 subagents 列表里，**现有 7 卡端到端基线不受影响**。

---

## 七、数据模型

两张新表（对齐 `models.py` 现有风格）：

```python
class AlertRecord(Base):
    """告警记录 — 生命周期跨轮维护，是"去重/升级/恢复"的依据。"""
    __tablename__ = "alert_records"
    id: Mapped[str] = mapped_column(Text, primary_key=True)        # ALR-<8hex>
    kind: Mapped[str] = mapped_column(String(32))                  # demand/reverse_flow/soc_ahead/device_offline/...
    severity: Mapped[str] = mapped_column(String(16))              # info|warn|critical
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|acked|suppressed|resolved
    first_seen_ts: Mapped[int] = mapped_column(BigInteger)
    last_seen_ts: Mapped[int] = mapped_column(BigInteger)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)   # 持续了几轮
    escalated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)    # 触发时的原始数值，可追溯
    diagnosis: Mapped[dict] = mapped_column(JSONB, default=dict)
    resolved_at: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        Index("ix_alert_kind_status", "kind", "status"),
        Index("ix_alert_active", "status", "last_seen_ts"),
    )


class AlertAction(Base):
    """处置记录 — 每个告警生成了什么方案、批没批、执行结果如何。"""
    __tablename__ = "alert_actions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)        # ALA-<8hex>
    alert_id: Mapped[str] = mapped_column(Text, index=True)
    proposal: Mapped[dict] = mapped_column(JSONB, default=dict)    # 含求解器原始返回
    draft_schedule_id: Mapped[str] = mapped_column(Text, default="")  # 落库的草案计划
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[int] = mapped_column(BigInteger, default=0)
    execution_result: Mapped[dict] = mapped_column(JSONB, default=dict)
    verification: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[int] = mapped_column(BigInteger)
```

**复用既有实体**：

- **`ChargeSchedule.status='draft'`**（`models.py:392`）——已建模但**从未被写入**（`apply_schedule.py:85` 直接写 `active`）。处置方案正好落成 `draft`，审批通过再改 `active`。**这个字段等了很久终于有用了。**
- **`ApprovalRecord`**（`models.py:64-93`）——审批留痕，字段够用。
- **`notifications.publish()`**（`notifications.py:52-57`）——站内实时推送。
- **飞书 webhook**（`task-service/app/tasks.py:71-127`）——外部推送。

---

## 八、处置方案怎么生成（复用求解器，不重造）

诊断出原因后，处置方案本质就是**一个带约束的调度计划** —— 这正是 `optimize_dispatch` 已有的能力：

| 诊断结论 | 生成的约束 | 约束类型（已有） |
|---|---|---|
| 尖峰段 SOC 不够 | 13:00 前充到 90% | `{"type":"soc_target","hour":13,"soc_pct":0.9}` |
| 需量快超 | 压住申报需量 | `{"type":"respect_declared_demand"}` |
| 白天逆流 | 严禁上网 + 平滑出力 | 策略组合 `防逆流`（`strategies.py:25-26`，`anti_reverse=0`） |
| 计划没执行 | 重新生成并下发 | 常规求解 |

**关键：数字全部来自求解器，不由 LLM 生成。** 与既有原则一致（`docs/business.md:217` 第一条硬边界：关键数字不来自模型）。

⚠️ **必须处理的冲突**：如果"尖峰段强制放电"和"防逆流不许上网"同时成立，求解器会返回 `status=infeasible` + `diagnosis` / `active_constraints`。此时**必须把冲突原样上报用户请其决策**，绝不能悄悄改小参数重试——这是 `optimize_dispatch.py:125-129` 明令禁止的行为：

> **遇到 status=infeasible 的正确处理（硬规则）**：…必须把这些数字**原样上报用户并请其决策**…**严禁**改 `reserve` 参数、改约束值反复重试。

---

## 九、分期实施

| 阶段 | 交付 | 一眼可验的验收标准 | 预估改动 |
|---|---|---|---|
| **P0** 看得见 | 六维巡检 + 分级 + 新增/恢复播报（只通知，不处置） | 把申报需量临时调低，15 分钟内收到告警；调回去，收到"已恢复" | 小（2 张表 + 巡检纯函数 + 通知） |
| **P1** 会归因 | 归因诊断树 + 处置方案生成（落 draft，不执行） | 断言：给定"尖峰 SOC 不足"，诊断结论与建议充电时段正确 | 中（+ 诊断树 + 求解器对接） |
| **P2** 能闭环 | 审批 → 执行 → 复检 → 关闭 | 端到端走通一次：告警 → 采纳 → 计划生效 → 复检通过 → 告警关闭 | 中高（+ interrupt + 执行 + 复检环） |

**分期理由**：P0 完全不碰执行链路，**已经能交付核心价值**（从"没人盯"变成"有人盯"）；P2 才触及硬件动作，放最后。

**回归保护**：每阶段完成后跑一遍现有 7 卡基线（`.workbuddy/memory/MEMORY.md` §7）。本设计不修改 Lead 链路，**基线应当零变化**——有变化即为异常信号。

---

## 十、风险与边界

### 10.1 必须如实标注的三点

1. **告警风暴**：如果阈值定得太紧，一个繁忙时段可能同时触发多个维度。P0 必须先有**去重 + 抑制**（`AlertRecord.status=suppressed`）再上线，否则会变成"狼来了"。
2. **温度维度在模拟数据下不会触发**（见 §5.3）。接进框架即可，但要如实说明它当前是"占位"。
3. **归因可能是错的**。"SOC 不足"可能真的是生产加急导致，也可能只是预测偏了。所以 P1 的诊断结论**必须带依据**（`evidence` 字段存原始数值），并且**处置建议是给用户判断的，不是替用户拍板的**。

### 10.2 明确不做

| 不做 | 理由 |
|---|---|
| 自动执行处置（无人审批） | 改储能运行方式属影响硬件的动作，必须人工确认 |
| 毫秒级保护（过流/过压跳闸） | 交底层保护装置，平台只做分钟级以上决策（`docs/business.md:212` 已划此边界） |
| 让 LLM 决定阈值或生成处置数字 | 阈值走配置（`rules.py`），数字走求解器 |
| 把值守塞进 Lead 的 subagents | deepagents 0.6.12 的 `SubAgent` 没有 `graph` 字段（`.venv/.../deepagents/middleware/subagents.py:36-130`），只能做独立入口 |
| 替代 `station-analysis` | 那是"人问就答"，这是"不问也盯"，两者互补 |

### 10.3 失败模式

| 失败模式 | 对策 |
|---|---|
| Celery beat 挂了 → 没人巡检，且用户不知道 | 巡检任务自身要有心跳：连续 N 分钟无巡检记录 → 前端显示"值守已停止" |
| 复检发现没解决 → 反复诊断死循环 | 图内设最大重试次数（如 3 次），超限则升级告警并停止自动处置 |
| 告警状态与实际情况漂移 | 每次巡检以**实际数据**为准重算，而不是信任库里旧状态；库只用于判断"是否新增/恢复" |

---

## 十一、附：本轮一并评估但未采用的方案

| 方案 | 为什么不选 |
|---|---|
| **需求响应（DR）邀约闭环** | 已单独出过设计（`docs/design-demand-response-workflow.md`）。判定为**不够容易懂**：要理解邀约、聚合商、速度系数、考核罚款等一串行业概念，价值不直观 |
| **电池健康度与寿命预测** | 数据是假的：`soh` 是硬编码常量 0.925（`models.py:240` 定义，**全仓无任何更新点**），`cycle_count` 的增长公式也不真实（`pcs_service.py:175`：每 100 小时才 +1）。做出来会是对着假数据出报告 |
| **执行偏差复盘（PDCA）** | **已实现**：`get_schedule_status`（`tools/get_schedule_status.py`）就在对比计划 SOC 与实际 SOC、返回 `deviation_pct` / `on_track`。本设计把它作为巡检的一个维度**复用**，而不是重造 |
| **电费归因（"电费为什么这么高"）** | 确实空白（`account_revenue` 只算收益侧，不算实际电费账单，`tools/account_revenue.py:112-123`）。价值直观，但归因要引入"电量电费/基本电费/力调电费"三层结构，仍带一定专业门槛。**保留为后续候选** |

---

## 参考证据索引

| 结论 | 位置 |
|---|---|
| 业务告警 0 命中（命中皆为 logger） | `grep "健康\|巡检\|告警\|预警" --root emsclaw --include *.py` |
| 现有工具全为被动查询，标旗即止 | `station_data/tools/get_demand_status.py:12-21` |
| 分析是罗列不归因 | `station_data/skills/station-analysis/SKILL.md:53-62` |
| 站内通知通道 | `emsclaw_backend/notifications.py:52-57` |
| 外部通知通道（飞书 webhook） | `task-service/app/tasks.py:71-127` |
| 通知选项仅"任务开始/结束" | `frontend/src/locales/zh.ts:515-516` |
| `get_schedule_status` 已实现偏差监测 | `dispatch_planning/tools/get_schedule_status.py:54-56` |
| `SubAgent` 无 `graph` 字段 | `.venv/Lib/site-packages/deepagents/middleware/subagents.py:36-130` |
| 现有定时必过 LLM | `task-service/app/tasks.py:46-68`、`:189` |
| beat 调度清单 | `task-service/app/celery_app.py:19-32` |
| 需量字段 | `db/models.py:333`（`rolling_demand_kw`）、`:417`（`contract_demand_kw`） |
| 逆流字段 | `db/models.py:332`（`reverse_flow`）、`:418`（防逆流设定） |
| 温度由公式生成（永不超阈值） | `service/pcs_service.py:170-171` |
| `soh` 硬编码且无更新点 | `db/models.py:240`、`service/pcs_service.py:335` |
| `ChargeSchedule.status='draft'` 未使用 | `db/models.py:392` vs `tools/apply_schedule.py:85` |
| 收益核算只算收益侧 | `dispatch_planning/tools/account_revenue.py:112-123` |
| 策略组合（防逆流） | `dispatch_planning/strategies.py:25-26` |
| infeasible 严禁改参重试 | `dispatch_planning/tools/optimize_dispatch.py:125-129` |
| 分时电价读取 | `dispatch_planning/tools/_shared.py:54-65` |
| 设备状态字段 | `db/models.py:201` |
