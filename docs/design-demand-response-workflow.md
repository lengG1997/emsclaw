# 需求响应（DR）事件闭环 —— 设计文档

> 状态：**待评审**（仅有设计，无代码）
> 定位：新增一条**独立工作流入口**，不改动现有 Lead → 子 Agent 对话链路
> 一句话：把"电网发邀约 → 算能参与多少 → 申报 → 窗口内执行 → 核验 → 拿钱"这条**跨时长、带硬截止审批**的链路做成一张图，补上本项目唯一一处"必须用工作流、用工具做不到"的空白。

---

## 目录

1. [需求定义与为什么是它](#1-需求定义与为什么是它)
2. [为什么必须用工作流（而不是工具 / cron / 对话链路）](#2-为什么必须用工作流而不是工具--cron--对话链路)
3. [现有能力盘点：可复用 vs 真缺口](#3-现有能力盘点可复用-vs-真缺口)
4. [图设计：状态、节点、三条边上的 interrupt](#4-图设计状态节点三条边上的-interrupt)
5. [关键难点一：审批超时兜底](#5-关键难点一审批超时兜底)
6. [关键难点二：响应窗口怎么落地执行](#6-关键难点二响应窗口怎么落地执行)
7. [数据模型变更](#7-数据模型变更)
8. [核心算法：可参与容量与机会成本](#8-核心算法可参与容量与机会成本)
9. [入口、触发与文件落位](#9-入口触发与文件落位)
10. [分期实施与验证](#10-分期实施与验证)
11. [风险、边界与明确不做的部分](#11-风险边界与明确不做的部分)
12. [附：被否掉的备选需求](#12-附被否掉的备选需求)

---

## 1. 需求定义与为什么是它

### 1.1 需求是什么

需求响应（Demand Response，DR）是**事件驱动**的收益渠道，与峰谷套利有本质区别：

| | 峰谷套利（已实现） | 需求响应（本设计） |
|---|---|---|
| 触发 | 时段驱动，每天固定发生 | **事件驱动**，电网/聚合商邀约才发生 |
| 时间尺度 | 24h 日前计划 | 邀约通知 → **申报截止** → 响应窗口（1~4h）→ 核验 → 结算 |
| 决策内容 | 几点充、几点放 | **要不要参与、报多少容量**（承诺即合同义务） |
| 收益来源 | 峰谷价差 | 响应补偿（元/kWh × 响应速度系数）+ 备用容量费 |
| 关键约束 | 需量上限、SOC | **窗口内必须真的压下来**，否则考核/罚款 |

典型链路：**邀约 → 评估可参与容量 → 申报（有截止时间）→ 等中标 → 窗口前预置 SOC → 窗口内执行削减 → 核验实际削减量 → 结算补偿**。

### 1.2 为什么它是本项目的真空白

证据（可复现）：

```bash
# 全仓 496 个文件中，需求响应相关关键词 0 命中
python <tsd-bridge> grep "需求响应|demand_response|邀约|响应补偿|DR事件" \
  --root emsclaw
# → <<0 hit(s) in 496 file(s)>>
```

而项目自己的业务文档已经把这块收益**点名**两次：

- `docs/business.md:115`：需求响应是**事件驱动**而非时段驱动……要吃到这笔钱，系统必须能回答"要不要留一部分 SOC 和功率当备用，而不是全部拿去套利"——**这是一个跨市场的机会成本问题，在配置表的字段里无处安放**。
- `docs/business.md:177`：多市场收益（需求响应 / 备用 / 现货）—— 配置表"**无对应字段，装不进去**"。

也就是说：这不是我凭空想的功能，而是**项目在论证自己价值时用来当论据的那块收益，恰恰是它自己没实现的**。当前平台能算峰谷套利、能算需量节省、能算碳减排（`account_revenue`），但 DR 这条收益线是 0。

### 1.3 为什么现在做是合适的

- **求解器已就位**：判断"能参与多少"需要算"需量最多能压到多少""一天最多能吞吐多少"，这正是 `solver` 的 `sweep.find_limit` / `preview.envelope` 已经能算的（见 §3）。
- **审批与持久化底座已就位**：DR 申报必须人工确认，而 HITL interrupt + `AsyncPostgresSaver` + `ApprovalRecord` 已在生产跑（`factory.py:282-289`、`models.py:64-93`）。
- **缺口是编排，不是算法**：需要新增的是"跨时长状态机 + 硬截止审批 + 窗口执行 + 核验"，这正是工作流擅长的部分。

---

## 2. 为什么必须用工作流（而不是工具 / cron / 对话链路）

这是本设计的**核心论证**。四个理由，其中前两个是决定性的。

### 2.1 理由一：审批有**硬截止时间**，而 interrupt 本身没有超时

DR 申报的截止时间由电网规定（例如邀约 09:00 发出、11:00 截止）。这个审批**不能无限等**：

- 现有 chat 里的 HITL 审批（`apply_schedule`）语义是"等你决定，多久都行"，没有超时兜底——因为下发计划晚一小时无非是晚一小时。
- DR 申报**晚一分钟就等于放弃这笔收益**，且必须有一个**确定性**的默认动作（保守申报 / 放弃）。

LangGraph 的 interrupt 提供了"暂停 → 持久化 → 恢复"的原语（`route/approvals.py:109` 合成 `Command(resume={interrupt_id: {...}})`），但**超时触发必须由图外的巡检来做**（见 §5）。这套组合是工作流特有的：一个有状态的图可以被"挂起数小时"，然后在两个不同触发源（人工决策 / 超时巡检）中**任意一个**到达时继续。**用顺序代码或 Celery chain 写不出"挂起 + 双触发源恢复"。**

### 2.2 理由二：现有定时能力**必然过 LLM**，不适合"守护窗口"

`task-service` 的所有 AI 任务只有一条路径：HTTP 调后端 `/api/v1/chat`，把一段 prompt 交给 Lead Agent。

- `emsclaw/task-service/app/tasks.py:46-68`（`_run_chat_sync`）：POST `/api/v1/chat`，`payload={"input": prompt, "source": "task"}`。
- `tasks.py:189`：`daily_revenue_report` 就是发一句「生成昨日收益报告」，让它路由到 `DispatchPlanningExpert`。

这意味着现有每一分钟级的定时"AI 任务"都要付出一次完整 agent 循环的代价。而 DR 需要的是：

- **窗口前**：检查 SOC 是否已充到预置水平（纯数值比较，不需要 LLM）
- **窗口中**：每 tick 确认执行是否偏离（纯数值比较）
- **窗口后**：核验实际削减量（纯数值计算）

用 LLM 守一个 2 小时的窗口，既不经济（token 成本）也不可靠（模型输出有不确定性）。**把这些环节编进图里做成确定性节点，才能既省钱又保证"该压的时候一定压下去"。**

### 2.3 理由三：不能塞进现有对话链路

deepagents 0.6.12 的 `SubAgent` 规格**没有** `graph` / `runnable` 字段（`.venv/.../deepagents/middleware/subagents.py:36-130`，字段仅 name / description / system_prompt / tools / model / middleware / interrupt_on / skills / permissions / response_format）。因此：

- ❌ 不能"把某个子代理换成一张图"——没有官方挂载点。
- ❌ 不宜塞进某个 tool 内部——DR 的整个人工决策可能挂起数小时，而它挂在 Lead 会话上，会让一个会话长期占着 pending interrupt，语义与成本都不对。
- ✅ 只能做成**独立入口**（独立图 + 独立路由），与 Lead 链路互为邻接而非嵌套。

### 2.4 理由四：若用 Celery 自造审批，等于维护第二套审批体系

现有审批是**会话耦合**的（`route/approvals.py:48`）：

```
POST /sessions/{session_id}/approvals/{interrupt_id}   body: {decision: approve|reject|edit|respond}
```

它需要 session、需要 SSE queue、需要 `_agent_background_worker` 恢复流。如果 DR 用 Celery 自己实现"等审批"，就要新增一套审批表、一套审批 UI、一套恢复语义——**而 interrupt 路线可以直接复用 `ApprovalRecord` 与现有审批页**。

> **一句话总结 §2**：DR 的价值在于"挂起 → 双触发源恢复 → 窗口内确定性执行"，这三件事分别是 interrupt、超时巡检、图内节点——**恰好是工作流的定义，也恰好是工具与 cron 的短板。**

---

## 3. 现有能力盘点：可复用 vs 真缺口

### 3.1 可直接复用（不需要新造）

| 能力 | 位置 | 在 DR 里干什么 |
|---|---|---|
| LP 求解 + 约束类型 | `dispatch_planning/solver.py:76-103`（`ConstraintSpec`，8 类） | 生成"含响应窗口"的计划 |
| 强制窗口内放电 | `ConstraintSpec.mode_lock`（`hours` + `mode=discharge` + `min_power_kw`） | **窗口内必须压下来**的硬约束 |
| 窗口前充到指定 SOC | `ConstraintSpec.soc_target`（`hour` + `soc_pct`） | 窗口前把电备好 |
| 可压需量边界 | `solver.py:1071`（`_sweep_find_limit`）→ `sweep.find_limit='demand_cap_kw'` | **算"最多能削多少 kW"** |
| 日吞吐可行域 | `solver.py:780`（`_preview`）→ `envelope.throughput_kwh` | 算填谷能力 |
| 备用档位口径 | `solver.py:428`（`_reserve_floor_info`）、`ConstraintSpec.level`（低/中/高 = 0.10/0.20/0.30×峰荷，2h） | 备用容量类 DR 的容量口径 |
| 计划落库与失效 | `models.py:381-409`（`ChargeSchedule`）+ `apply_schedule.py:82`（`supersede_active`） | 窗口执行计划 |
| 审批与恢复 | `models.py:64-93`（`ApprovalRecord`）+ `route/approvals.py:48` | 申报审批、执行审批 |
| 会话级持久化 | `factory.py:282-289`（`AsyncPostgresSaver`） | 图挂起数小时后恢复 |
| 15min 滚动需量时序 | `models.py:318-337`（`MeterSnapshot.rolling_demand_kw`） | **核验窗口内是否真达标** |
| 当月峰值需量 | `ems_data.py:160-178`（`month_max_demand_kw`） | 基线口径 |
| 装配零件 | `agents/base.py:23-49`（`get_model` / `build_sandbox` / `build_sse` / `build_offload`） | 新图直接复用 |
| 收益分项 | `dispatch_planning/tools/account_revenue.py` | 结算核算是它的同类 |

### 3.2 真缺口（必须新增）

| 缺口 | 证据 | 影响 |
|---|---|---|
| **DR 事件 / 申报 / 结算三张表全无** | `grep 需求响应` 0 命中；`models.py` 无相关实体 | 状态无处持久化 |
| **无 DR 补偿单价与速度系数参数** | `models.py:412-421` `StationConfig` 只有 `capacity_price_yuan_per_kw_month` / `demand_price_yuan_per_kw_month` / `contract_demand_kw` / `anti_reverse_export_setpoint_kw` | 收益算不出来 |
| **`reserve` 是"全时段统一"的 SOC 下限** | `solver.py:428` 折算逻辑 + `optimize_dispatch.py:121` 文档：档位折算成"每小时 SOC 下限 ≥ 关键负荷×时长" | **不支持"仅窗口内预留"**，只能靠 `mode_lock` + `soc_target` 组合表达（可行，见 §6.2） |
| **无"基础计划 + 响应叠加层"模型** | `apply_schedule.py:82` 的 `supersede_active` 会把当日 base 计划置为 `superseded` 且**不回滚** | 响应结束后需人工重建计划 |
| **`ChargeSchedule.status='draft'` 已建模但从未写入** | `models.py:392` 定义了 `draft|active|superseded`；`apply_schedule.py:85` 直接写 `status="active"` | 可**直接复用**为"待审批草案" |
| 无窗口达标判定逻辑 | 无代码 | 核验环节需新建 |

### 3.3 一个正面发现：DR 窗口不需要改求解器

`reserve` 虽然是全时段口径，但 DR 的"窗口内削减"可以**用现有约束类型拼出来**：

```python
# 窗口前充满（例如 13:00 前充到 90%）
{"type": "soc_target", "hour": 13, "soc_pct": 0.90}
# 窗口内强制放电 ≥ 500kW（14:00-16:00）
{"type": "mode_lock", "hours": [14, 15], "mode": "discharge", "min_power_kw": 500}
# 同时守住申报需量
{"type": "respect_declared_demand"}
```

**结论：第一版 DR 可以零求解器改动落地**，只需在 `ConstraintSpec` 之外新增业务参数（补偿单价等）。这显著降低实施成本，也是我建议先做 DR 而非其他候选的理由之一。

---

## 4. 图设计：状态、节点、三条边上的 interrupt

### 4.1 图形态

```
                         ┌──────────────────┐
  邀约录入 ──────────────▶│ ingest_event     │ 解析窗口/截止时间，校验合法性
                         └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │ assess_capacity  │ ← solver.preview / sweep.find_limit
                         │                  │   算可参与容量区间 + 机会成本
                         └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │ build_bids       │ 生成 2~3 个方案（保守/推荐/激进）
                         └────────┬─────────┘
                                  ▼
                    ╔═════════════════════════╗
                    ║ interrupt #1: 申报审批  ║ ◀── 超时巡检可强制 resume(reject)
                    ║ (承诺容量 = 合同义务)   ║
                    ╚════════════┬════════════╝
                        reject ──┤── approve
                          ▼      ▼
                    ┌────────┐  ┌──────────────────┐
                    │ 放弃   │  │ submit_bid       │ 外部动作，审计留痕
                    └────────┘  └────────┬─────────┘
                                         ▼
                                ┌──────────────────┐
                                │ await_award      │ 未中标 → END
                                └────────┬─────────┘
                                         ▼
                                ┌──────────────────┐
                                │ prepare_window   │ 落 draft 计划 + 充到预置 SOC
                                └────────┬─────────┘
                                         ▼
                                ╔═════════════════════════╗
                                ║ interrupt #2: 执行审批  ║
                                ╚════════════┬════════════╝
                                             ▼
                                ┌──────────────────┐
                                │ execute_window   │ 落 overlay 计划，窗口内生效
                                └────────┬─────────┘
                                         ▼
                                ┌──────────────────┐
                                │ verify_window    │ MeterSnapshot.rolling_demand_kw 核验
                                └────────┬─────────┘
                                   达标 ─┤─ 未达标
                                    ▼    ▼
                          ┌──────────┐  ┌────────────────┐  ┌──────────┐
                          │ settle   │  │ alert_shortfall│  │ END      │
                          └──────────┘  └────────────────┘  └──────────┘
```

### 4.2 State schema（草案）

```python
class DRState(TypedDict):
    # ── 事件 ──
    event_id: str
    kind: Literal["削峰", "填谷", "备用"]
    window_start_ts: int
    window_end_ts: int
    bid_deadline_ts: int
    compensation_yuan_per_kwh: float   # 来自配置/人工录入，禁止 LLM 编造
    speed_factor: float                # 响应速度系数（1.0~1.8）
    verify_rule: dict                  # 核验口径（基线算法、允许偏差）

    # ── 评估 ──
    baseline_kw: float                 # 基线负荷
    feasible_capacity_kw: float        # 可参与容量（求解器算）
    opportunity_cost_yuan: float       # 预留电量的套利机会成本
    assess_evidence: dict              # 求解器原始返回（可追溯）

    # ── 申报 ──
    candidate_bids: list[dict]         # [{label, capacity_kw, est_revenue, est_cost, risk}]
    chosen_label: str
    decided_by: str
    decided_at: int
    bid_submitted: bool

    # ── 执行 ──
    schedule_draft_id: str
    schedule_active_id: str
    execution_window_actual_kw: list   # 窗口内逐 tick 实际值
    compliance_ok: bool
    shortfall_kw: float

    # ── 结算 ──
    verified_kwh: float
    settled_yuan: float
    report_path: str                   # 落 reports/<topic>_<ts>.md，与既有约定一致
```

### 4.3 三个 interrupt 的必要性

| interrupt | 为什么必须人工 | 能否超时兜底 |
|---|---|---|
| #1 申报审批 | 申报容量是**合同义务**，报高了要担考核风险 | ✅ 超时 → `reject` = 放弃申报（保守） |
| #2 执行审批 | 影响硬件运行，与现有 `apply_schedule` 同级风险 | ✅ 超时 → `reject` = 维持基础计划（安全） |
| #3 未达标上报 | 只是告警，不阻塞 | 不设 interrupt，走消息上报 |

---

## 5. 关键难点一：审批超时兜底

**问题**：LangGraph 的 `interrupt` 会一直挂起，没有内建超时。

**方案**：由 Celery beat 巡检 + 复用现有 resume API。

```
1. 图在 interrupt 处挂起（状态已由 AsyncPostgresSaver 持久化）
2. 图内节点在挂起前，把 {event_id, interrupt_id, session_id, bid_deadline_ts} 写入 dr_bid 表
3. Celery beat 新增 periodic task（建议 60s，与现有 pcs-sim-tick 同周期）:
   - 扫描 dr_bid 中 status=pending 且 now() > bid_deadline_ts 的行
   - 调 POST /sessions/{session_id}/approvals/{interrupt_id}
         body: {"decision": "reject"}     ← 超时默认 = 放弃
   - 记录 timeout_reject 标记，便于事后复盘
```

**为什么选 `reject` 而不是自动 approve**：申报/执行都涉及对外承诺或硬件，**超时未决时的默认动作必须是"不动作"**。这与项目既有原则一致——不可达时不装作可达（`optimize_dispatch.py:125-129` 严禁改参重试），算不出来就上报用户。

**为什么复用 `POST /sessions/.../approvals/...` 而不是新写**：该接口已处理 `Command(resume=...)` 合成、`ApprovalRecord` 落库、SSE worker 恢复（`route/approvals.py:109,126,152`）。**新增的只是"谁在什么条件下调它"。**

---

## 6. 关键难点二：响应窗口怎么落地执行

### 6.1 现有执行优先级

`PcsService.decide_mode_and_power`（`pcs_service.py:66-103`）是三级：

```
① 手动 override（override_expires_at 未过期，TTL 1h）
   ↓ 无
② 当日 active ChargeSchedule 的该小时 interval
   ↓ 无
③ 电价时段兜底（谷充 / 峰尖放 / 平待机）
```

### 6.2 两个候选方案

| | 方案 A：overlay 计划（推荐） | 方案 B：override 强制 |
|---|---|---|
| 做法 | 新增 `ChargeSchedule.kind='base'\|'dr_overlay'`，`decide_mode_and_power` 优先读 overlay，窗口结束自动回落 base | 窗口内写 `PcsDevice.override_mode/override_power_kw` |
| 改动 | 中等（改读取优先级 + 新增字段） | 小 |
| 审计 | ✅ 落库、可追溯、与 base 计划可比 | ❌ 无计划轨迹 |
| 窗口 >1h | ✅ 支持 | ❌ 现有 TTL 只有 1h（`pcs_service.py:69`），需先改 TTL |
| 恢复基础计划 | ✅ 自动回落 | ❌ 靠 TTL 过期，不可控 |
| 建议 | **采用** | 只作为应急手操保留 |

### 6.3 必须显式处理的冲突

窗口内强制放电遇到**防逆流**时可能反送（`cfg["anti_reverse_setpoint_kw"]`，`solver.py:196`）。

处理原则：**图中显式校验并把冲突上报，不允许静默**。具体做法：

- `mode_lock` 的 `min_power_kw` 与 `no_export` 同时存在时，求解器会因不可行返回 `status=infeasible` + `diagnosis` / `active_constraints`；
- 图中捕获该返回 → 降档 `min_power_kw`（例如取 `min(申报容量, 基线负荷 - 反送阈值)`）→ **重新求解并把降档事实写入 State 与用户报告**；
- 绝不做"参数改小再偷偷重试到成功"——这正是 `optimize_dispatch.py:125-129` 明令禁止的行为。

---

## 7. 数据模型变更

新增三张表（对齐 `models.py` 现有风格：`Text` 主键 + `BigInteger` 时间戳 + JSONB 明细）：

```python
class DrEvent(Base):
    """需求响应邀约。"""
    __tablename__ = "dr_events"
    id: Mapped[str] = mapped_column(Text, primary_key=True)          # DRE-<8hex>
    kind: Mapped[str] = mapped_column(String(16))                    # 削峰|填谷|备用
    window_start_ts: Mapped[int] = mapped_column(BigInteger)
    window_end_ts: Mapped[int] = mapped_column(BigInteger)
    bid_deadline_ts: Mapped[int] = mapped_column(BigInteger)
    compensation_yuan_per_kwh: Mapped[float]
    speed_factor: Mapped[float] = mapped_column(default=1.0)
    source: Mapped[str] = mapped_column(Text, default="manual")      # manual|api（初版仅 manual）
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|bid|won|lost|done
    created_at: Mapped[int] = mapped_column(BigInteger)


class DrBid(Base):
    """申报记录 — 一个 event 可有多条候选，但只有一条 submitted=True。"""
    __tablename__ = "dr_bids"
    id: Mapped[str] = mapped_column(Text, primary_key=True)          # DRB-<8hex>
    event_id: Mapped[str] = mapped_column(Text, index=True)
    plan_label: Mapped[str] = mapped_column(Text, default="")
    capacity_kw: Mapped[float]
    est_revenue_yuan: Mapped[float]
    est_opportunity_cost_yuan: Mapped[float]
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)      # 求解器原始返回，可追溯
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected|timeout_reject
    interrupt_id: Mapped[str] = mapped_column(Text, default="")      # 供超时巡检定位 resume
    created_at: Mapped[int] = mapped_column(BigInteger)


class DrSettlement(Base):
    """核验与结算。"""
    __tablename__ = "dr_settlements"
    id: Mapped[str] = mapped_column(Text, primary_key=True)          # DRS-<8hex>
    event_id: Mapped[str] = mapped_column(Text, index=True)
    baseline_kw: Mapped[float]
    actual_kw_series: Mapped[list] = mapped_column(JSONB, default=list)
    verified_kwh: Mapped[float]
    compliance_ok: Mapped[bool]
    settled_yuan: Mapped[float]
    created_at: Mapped[int] = mapped_column(BigInteger)
```

复用既有实体：

- **`ChargeSchedule.status='draft'`**（`models.py:392`）→ 直接用于 `prepare_window` 产出的待审批计划，**无需新增状态枚举**。
- **`ApprovalRecord`**（`models.py:64-93`）→ 审批留痕，字段已足够。
- **`DailyEnergyRecord`** → 结算收益并入日收益口径，保证 `account_revenue` 与收益页一致。

配置扩展（`StationConfig` 或独立配置表）：DR 默认补偿单价、速度系数、基线算法参数。**这些必须可配置，不允许由 LLM 生成。**

---

## 8. 核心算法：可参与容量与机会成本

### 8.1 可参与容量

**削峰类**：用 `sweep.find_limit='demand_cap_kw'` 求"需量上限最紧能压到多少"，与基线峰值之差即削峰能力。

```python
optimize_dispatch(
    strategies=["省钱"],
    constraints=[{"type": "respect_declared_demand"}],
    sweep=SweepSpec(find_limit="demand_cap_kw"),
)
# → sweep.limit.value 即最紧可行需量上限
# 可参与容量 ≈ baseline_peak_kw - sweep.limit.value
```

**填谷类**：用 `preview=True` 取 `envelope.throughput_kwh.unconstrained`（同约束下策略最优的自然吞吐），作为填谷上限。

⚠️ **必须校验的是 `points[i].feasible` / `sweep.any_feasible`，不是顶层 `status`。** 顶层键是 `scan_status`，只代表"扫描完成"（`optimize_dispatch.py:80-82` 明确警告过这个坑）。

### 8.2 机会成本

预留能量用于 DR 的代价 = 放弃的套利收益 + 循环退化成本：

```
opportunity_cost = reserved_kwh × (峰谷价差 − 0)  +  reserved_kwh × w_degrade 折算
```

其中峰谷价差来自 `_tariff_24h()`（`_shared.py:54-65`），`w_degrade` 来自 `strategies.resolve()`（`strategies.py:32-48`）。

判定规则：**仅当 `预计补偿 ≥ 机会成本 × 安全系数` 才建议参与**；否则给出"不建议参与 + 差多少"的量化结论，而不是含糊的"收益一般"。

### 8.3 示例测算

> ⚠️ **以下为示例输入，非实测**。站容量、价差、补偿单价均须以实际站配置与当地政策为准。

| 输入 | 取值 | 来源 |
|---|---|---|
| 储能规模 | 1MW / 2MWh（2×500kW + 2×1000kWh） | `pcs_service.py:32-37` 种子设备 |
| 窗口 | 2h | 假定 |
| 削峰补偿 | 3 元/kWh | 安徽口径（`docs/business.md:115`） |
| 速度系数 | 1.2 | 同上 |
| 峰谷价差 | 0.65 元/kWh | 江苏 2025 后口径（`docs/business.md:100`） |

```
预留能量            = 500kW × 2h = 1000 kWh
预计补偿            = 1000 × 3 × 1.2     = 3,600 元
机会成本（套利）     = 1000 × 0.65        =   650 元
单次净收益          ≈ 2,950 元
按 20 次/年         ≈ 59,000 元/年
```

即 **DR 单次收益约为同量能量套利收益的 5.5 倍**——这正是"跨市场机会成本问题"的量化形态，也是为什么必须算而不是拍脑袋。

---

## 9. 入口、触发与文件落位

### 9.1 入口

| 入口 | 形态 | 说明 |
|---|---|---|
| 录入邀约 | `POST /api/v1/dr/events` | 初版人工录入（电网/聚合商邀约通常是电话/邮件/平台） |
| 推进图 | 内部 worker（复用 SSE worker 模式）或 Celery 直调 | 与现有 resume worker 同构 |
| 审批 | `POST /sessions/{id}/approvals/{interrupt_id}` | **复用现有接口**，不改 |
| 超时巡检 | Celery beat 新增 periodic | 见 §5 |

### 9.2 文件落位（建议）

```
emsclaw/backend/deepagent/workflows/            # 新建：与 agents/ 平级，放"非对话"工作流
  └── demand_response/
      ├── graph.py          # StateGraph 组装
      ├── state.py          # DRState
      ├── nodes.py          # 各节点实现
      └── params.py         # 补偿单价/速度系数读取（禁止 LLM 生成）
emsclaw/backend/route/dr.py                     # 新路由
emsclaw/backend/mapper/dr_mapper.py             # 数据访问
emsclaw/backend/service/dr_service.py           # 业务规则（可参与容量、机会成本、核验）
emsclaw/task-service/app/tasks.py               # 新增 dr_deadline_watch（超时巡检）
emsclaw/task-service/app/celery_app.py          # 注册 beat_schedule
emsclaw/tests/test_dr_*.py                      # 单测（对齐现有 tests/ 命名）
```

**与现有结构的边界**：`workflows/` 不注册到 `AgentRegistry`，不出现在 Lead 的 subagents 列表里，因此**Lead 的委派能力不受影响**，现有 7 卡端到端基线也不会被破坏。

---

## 10. 分期实施与验证

| 阶段 | 交付 | 验证方式 | 预估改动量 |
|---|---|---|---|
| **P0** 决策闭环 | 邀约录入 + 可参与容量评估 + 多方案 + 申报审批（interrupt #1）+ 落库 | 单测：给定邀约与站配置，断言可参与容量与机会成本；手测：走完一次审批 | 中（新表 3 张 + 图 4 节点） |
| **P1** 执行闭环 | prepare_window + interrupt #2 + overlay 执行 + 核验 | 用 `pcs_sim_tick` 仿真：窗口内注入高负荷，断言实际削减 ≥ 申报值的 X% | 中高（需改 `decide_mode_and_power`） |
| **P2** 结算闭环 | 核验结算 + 收益并入日收益口径 + 报告落 `reports/` | 对比 `account_revenue` 口径一致性 | 低 |

**分期理由**：P0 完全不碰硬件与执行链路，风险最低，且**已经能产出业务价值**（"这次邀约该不该参与、报多少"是纯决策问题，正是平台最强的地方）。执行与结算依赖仿真数据语义，放后期更稳妥。

**回归保护**：每个阶段完成后跑一遍现有 7 卡基线（见 `.workbuddy/memory/MEMORY.md` §7），确认对话链路耗时与工具调用数无变化——因为本设计不修改 Lead 链路，**理论上应当完全不动**，基线变化即为异常信号。

---

## 11. 风险、边界与明确不做的部分

### 11.1 关键前提（若不成立，价值受限）

1. **邀约来源**：初版只能人工录入。若站侧无法获取邀约（无 API、无 IM 通道），则 DR 是"手输才管用"的半自动能力。**这是本设计最大的外部依赖，需先确认。**
2. **补偿参数可信**：补偿单价与速度系数必须来自配置或人工录入。**LLM 编一个单价出来会让整个收益测算失真**，因此图中所有涉及金额的参数都要带来源标注。
3. **核验口径**：电网侧基线算法（前 N 日均值 / 相似日）各家不同，需按当地规则配置。初版可用 `meter_snapshots` 的自身历史做近似，但**必须标注"近似基线"**。

### 11.2 明确不做

| 不做 | 理由 |
|---|---|
| 自动申报（无人工确认） | 承诺容量是合同义务，必须人工拍板 |
| 毫秒级实时闭环下发 | 交底层控制器，平台只做日前/小时级决策（`docs/business.md:212` 已划此边界） |
| 现货市场套利 | 与本设计相邻但独立，且依赖现货价格源，不做范围蔓延 |
| 让 LLM 生成补偿单价 / 基线结果 | 关键数字不来自模型（`docs/business.md:217` 第一条硬边界） |
| 把 DR 塞进 Lead 的 subagents | deepagents 0.6.12 无此挂载点（§2.3） |

### 11.3 失败模式与对策

| 失败模式 | 对策 |
|---|---|
| 图挂起数小时后 checkpointer 取不到状态 | `factory.py:282-289` 已有"取不到就降级"的写法，DR 图需显式处理：降级 → 上报，不静默 |
| 审批超时未触发（beat 挂了） | 巡检任务本身要可观测：无巡检心跳时，图内节点在挂起前即写入 deadline，并在报告中提示"超时兜底依赖 task-service" |
| 窗口内执行被设备离线打断 | `verify_window` 核验发现达标率不足 → 走 `alert_shortfall` 上报，不装作达标 |

---

## 12. 附：被否掉的备选需求

我在同一轮盘点中还发现了另外两个真空白，但**判断它们不该做成工作流**，记录于此以免重复讨论。

### 12.1 月度需量预算台账与超线预警

- **空白确认**：只有"瞬时需量 vs 申报值"（`get_demand_status.py:13`）与"当月已发生峰值"（`ems_data.py:160`），**没有逐日台账、没有月底趋势预测、没有预算进度**。
- **为什么否掉**：可用「cron + 一张台账表 + 一个读工具」完成，**图化收益低**。为图而图会凭空增加维护成本——这正是 `docs/business.md:142` 对路线 B 的批评："需求增长 → 条件分支爆炸，图越来越难维护"。
- **何时可做**：若将来需要"预测月底会超线 → 自动生成提前削峰计划 → 人工确认"，那一步才需要图。当前形态不需要。

### 12.2 执行偏差闭环（Plan-Do-Check-Act）

- **空白确认**：`apply_schedule` 下发后即结束，无"实际 vs 计划"偏差监测与自愈。
- **为什么暂缓**：它确实是强图形态，但**与 DR 的 P1 执行期监测高度重叠**。
- **建议**：先做 DR，其 `verify_window` 会把"实际 vs 目标"的比对骨架建起来，之后再抽出来服务偏差闭环。**DR 是它的前置，不是它的替代。**

### 12.3 基本电费计费方式切换（容量制 vs 需量制）

- **空白确认**：`StationConfig` 同时有 `capacity_price_yuan_per_kw_month`（30 元/kW·月）与 `demand_price_yuan_per_kw_month`（40 元/kW·月）（`models.py:419-420`），但**没有"该选哪种"的决策能力**。选错是每月固定亏损。
- **为什么否掉**：纯离线分析（拉 12 个月峰值 → 两种口径对比 → 给临界点），**一个工具 + 一份报告即可**，无跨时长状态、无审批、无执行，不需要图。

---

## 参考证据索引

| 结论 | 证据位置 |
|---|---|
| DR 完全空白（0 命中） | `grep "需求响应\|demand_response\|邀约" --root emsclaw` → 0 hit / 496 files |
| DR 被业务文档点名为"无处安放" | `docs/business.md:115`、`docs/business.md:177` |
| SubAgent 无 graph 字段 | `.venv/Lib/site-packages/deepagents/middleware/subagents.py:36-130` |
| 现有定时任务必过 LLM | `emsclaw/task-service/app/tasks.py:46-68`、`:189` |
| beat 调度清单 | `emsclaw/task-service/app/celery_app.py:19-32` |
| 审批 resume 契约 | `emsclaw_backend/route/approvals.py:48`、`:109`、`:126` |
| PCS 三级优先级 / override TTL | `emsclaw_backend/service/pcs_service.py:66-103`、`models.py:222-224` |
| 8 类约束 | `dispatch_planning/solver.py:76-103` |
| reserve 全时段口径 | `solver.py:428`、`optimize_dispatch.py:116-123` |
| 可压需量边界 | `solver.py:1071`（`_sweep_find_limit`） |
| 15min 滚动需量 | `models.py:318-337` |
| `ChargeSchedule.status` 含未使用的 `draft` | `models.py:392` vs `apply_schedule.py:85` |
| 当月峰值需量 | `emsclaw_backend/service/ems_data.py:160-178` |
| 站配置两种基本电费单价 | `models.py:412-421` |
| checkpointer 装配与降级 | `emsclaw_backend/deepagent/agents/business/factory.py:282-289` |
| 装配零件可复用 | `emsclaw_backend/deepagent/agents/base.py:23-49` |
