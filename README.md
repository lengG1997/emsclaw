<div align="center">

<img src="images/ems-claw.png" alt="emsclaw" width="160">

# emsclaw

### 基于 FastAPI + LangGraph + DeepAgents 的 EMS 多智能体平台

Vue 3 前端 · 带 Agent 运行时的 FastAPI 后端 · 远程 sandbox 容器 · Celery 任务调度

[🚀 在线体验](#-在线体验) · [业务介绍](docs/business.md) · [架构](docs/architecture.md) · [演示](docs/demo.md) · [模型选型](#大模型选型) · [快速开始](#快速开始) · [文档导航](#文档导航)

**仓库：** [GitHub](https://github.com/lengG1997/emsclaw) · [Gitee](https://gitee.com/lengGizz/emsclaw)

**🚀 在线体验：<http://47.106.113.186:15173>**（账号 `admin` / 密码 `admin123`，无需本地部署）

</div>

---

## 🚀 在线体验

无需本地部署，公网可直接打开：

| 服务 | 地址 | 账号 | 密码 |
|---|---|---|---|
| **平台前端** | http://47.106.113.186:15173 | `admin` | `admin123` |
| **Langfuse 可观测** | http://47.106.113.186:13001 | `admin@emsclaw.local` | `admin123` |

> 该环境跑的是 Vite dev server 且沿用默认口令，**仅供功能演示，请勿写入真实数据**；由维护者自建、非高可用部署，地址可能随时失效。
> 界面导览与验证基线见 [演示](docs/demo.md)。

## 这是什么

`emsclaw` 是面向 EMS（能源管理系统）的多智能体平台。它把一个由 **DeepAgents 0.6.x（LangGraph 内核）** 驱动的 Agent 运行时嵌入 FastAPI 后端，通过 SSE 事件流把"模型思考 / 工具调用 / 计划变更 / 最终回复"实时推给 Vue 3 前端，并配合远程 sandbox 容器执行代码与文件操作、用 Celery 做定时任务调度。

**核心主张：把决策权交给 Agent，把关键数字交给求解器。**

- **Agent 负责"怎么做"** —— 理解自然语言意图、路由到领域专家、自主挑选工具与调用顺序；
- **LP 求解器负责"是多少"** —— 功率 / SOC / 需量 / 收益全部由 scipy HiGHS 算出，模型不编造数值；
- **人只定边界** —— 影响硬件的动作走 HITL 审批，冲突时给诊断而不是硬凑一个方案。

仓库根目录是 `uv` workspace（本身不含代码），成员包都在 `emsclaw/` 下。

```
emsclaw/                             # uv workspace 根（不构建为包）
├─ backend/                          # FastAPI + DeepAgent 运行时
│  ├─ emsclaw_backend/               #   ← Python 包（import 根 emsclaw_backend.*）
│  │  ├─ main.py                     #     FastAPI 入口
│  │  ├─ route/ controller/ service/ #     分层：路由 → 控制器 → 业务规则
│  │  ├─ mapper/ entity/ db/         #     数据访问 → ORM 模型 → 会话
│  │  ├─ deepagent/                  #     Agent 运行时（主 agent + 域子 agent）
│  │  ├─ core_kit/ im/ observability/
│  │  └─ config.py models.py user/
│  └─ Dockerfile
├─ builtin-skills/                   # 内置 skill（docx/pdf/pptx/xlsx 等，烘焙进后端镜像）
├─ frontend/                         # Vue 3 + Vite + TS（import 根 @/）
├─ task-service/                     # FastAPI + Celery + croniter（import 根 app.*）
├─ sandbox/                          # 远程代码执行 + 文件系统沙箱
└─ tests/                            # pytest（asyncio_mode=auto，rootdir = 仓库根）

Skills/                              # 外置 skills，用户自行安装（挂载 /app/Skills）
scripts/                             # 运维与评测脚本（Langfuse 配置、模型评测）
docs/                                # 文档与架构图
.env.example                         # 环境变量样例（复制为 .env 使用）
docker-compose.yml
docker-compose.langfuse.yml          # 可观测性栈（可选叠加）
```

## 为什么这么做

工商业储能"做策略"的传统动作，是打开一个配置页、人工誊抄电价文件、把 24 小时逐段铺满——**策略 = 一张人工维护的时段表**。这套做法依赖三个前提：价差被政策锁定、峰谷时段提前写死、策略只需看电价。

**这三个前提在 2025—2026 年同时被打破了**：江苏峰谷价差降至 0.65 元/kWh（原约 0.85）；浙江以国网大工业口径测算加权价差 -28.5%；自 2026-03-01 起直接参与市场交易的经营主体**不再由政策规定分时电价时段**，至少 9—10 个省市已落地取消行政分时电价。

同一个需求——"明天产线加急，帮我出一套储能充放电策略，别让关口表需量超线"——三条技术路线会给出完全不同的形态：

| 维度 | A · 配置表 + 规则引擎 | B · LangGraph 工作流 | C · DeepAgents（本平台） |
|---|---|---|---|
| 策略载体 | 人工维护的时段表 | 编码期画死的有向图 | Agent 推理 + 策略组合 + 8 类约束 + LP 目标函数 |
| "几点充放"谁定 | 工程师手工铺满 24 小时 | 开发者编码期定节点顺序 | 模型按当日电价 / 负荷 / 光伏实时推导 |
| 电价 / 政策变了 | 改表，全量项目重配 | 改节点或数据源 → 发版 | 换数据源，策略与约束不动 |
| 需量管理 | 阈值规则，不感知"充电本身会刷新需量" | 图里没写就卡住 | LP 硬约束 + 15min 保守系数 |
| 算不出来时 | 抛异常 / 静默给默认计划 | 图里没画 → 卡住 | 给诊断（binding 约束 / 物理下限），**上报而非自行改参重试** |
| 适合 | 规则长期稳定、价差被锁定 | 流程完全固定 | 多目标权衡、需求多变、要解释的日前决策 |

> 一句话：**A 把策略誊成一张表，B 把策略画成一张图，C 让 Agent 在"约束 + 求解器"围出的安全区里现场找路——人只定边界，不画路径。**

📖 **完整的现场分析、账本数据与 15 维对比 → [业务介绍](docs/business.md)**

## 已落地能力

现状基线：24h 日前调度计划 + LP 求解（scipy HiGHS）+ 4 个可组合策略组合（省钱 / 保电池 / 绿电优先 / 防逆流）+ HITL 审批下发。

| 痛点场景 | Agent 怎么解 | 对应模块 |
|---|---|---|
| 多目标优化调度 | 策略组合可多选叠加，`resolve()` 合并权重后 LP 生成 24h 充放电计划 | `dispatch_planning` · `optimize_dispatch` · `strategies.py` |
| 储能优化控制 | 退化成本项（`w_degrade`）入目标函数，激进充放被惩罚；SOC / 倍率 / 循环硬约束求解 | `保电池` 策略 · LP 退化惩罚 |
| 光伏防逆流 | `防逆流` 策略（`anti_reverse=0` 严禁上网）+ 关口表实时监测 + 逆流告警 | `防逆流` 策略 · 关口表能量流图 |
| 需量管理 | 需量上限硬约束，预测负荷冲高时储能提前放电削峰 | 需量约束 · 需量 KPI |
| 自然语言意图理解 | Lead Agent 意图路由 + 领域子 Agent → 约束翻译 → HITL 审批下发 | `business` profile · `apply_schedule` |
| 收益核算 | 按来源（峰谷套利 / 需量节省 / 光伏自用 / 碳减排）拆解 | `account_revenue` · `RevenueBreakdown.vue` |

> **边界说明（如实标注）：** 防逆流当前是**计划级约束 + 关口表监测 + 逆流告警**；储能优化是 **LP 退化惩罚项**；多目标是 **4 组合可叠加 + 合并权重**。

## 大模型选型

| 部署形态 | 模型 | 定位 | 最低门槛 |
|---|---|---|---|
| **本地部署（最低）** | **Qwen3.5-27B** | 中文支持好、数据不出域，满足「能跑起来」的下限 | 单张 **24 GB 显存**（Int4 权重约 15 GB） |
| **本地部署（推荐）** | **Qwen3.8-27B** | 中文支持好、数据不出域、可跑 agent 长会话 | 单张 **24 GB 显存**（AWQ / GPTQ-Int4 权重约 15 GB） |
| **云端模型** | **DeepSeek V3.2** | 复杂推理 / 长上下文 | 按量调用，无需本机算力 |
| **云端模型** | **DeepSeek V4.1-flash** | 低延迟、高频问答与表单化追问 | 同上 |

- **本地部署分两档**：**最低档 Qwen3.5-27B**、**推荐档 Qwen3.8-27B**。两者同为 dense 27B，Int4 量化后权重都在 15 GB 量级，**显存门槛都是单张 24 GB**；差别在能力 —— 3.8 在 agentic 上领先一代以上（SWE-bench Pro 61.7 vs 53.5），且为 Apache 2.0、原生多模态。
- **⚠️ 需要说明的一点：同规模下 3.5 并不省显存。** 选最低档的理由不应是「省卡」——两者量化后占用相当，机器能装下 3.8-27B 就没有理由停在 3.5。3.5-27B 的合理适用面是**已有成熟 Int4 量化件、追求稳定运行栈**的场景。
- **没有选同门 MoE（如 35B-A3B）**：**MoE 省算力不省显存**——Q4 权重加运行时实测超 24 GB，24 GB 卡装不下，而 agent 长会话吃的是显存与上下文，不是解码速度。
- **中文支持**：Qwen 系中文语料与中文指令跟随明显更稳，本地部署选它可同时满足「中文业务对话 + 工具调用」两项要求。
- **云端兜底**：DeepSeek V3.2 承担复杂推理，V4.1-flash 承担低延迟高频调用；两者按量计费，不需要本机显卡。

> 若打算**走百炼 API** 而非本地权重用 3.5-27B，注意本次评测中 `qwen3.5-*` 全系因**账号模型权限**返回 `400 Access denied`（`docs/model-evaluation.md` 第 2.4 节），须先在百炼控制台开通。

> **接入注意事项（踩过的坑）**
> 1. 后端 `emsclaw_backend/deepagent/engine.py` 的上下文窗口靠**子串匹配**推断，`Qwen3.5-27B` / `Qwen3.8-27B` 都会命中 `qwen3` 被猜成 `131072`。**必须**在 model config 里显式配 `context_window`，并与 vLLM 启动参数 `--max-model-len` 对齐，否则摘要阈值按 131K 计、实际显存只兑现 32K，**溢出才报错**。
> 2. vLLM 起服务需 `--tool-call-parser qwen3_coder --enable-auto-tool-choice`，否则模型发不出 tool call —— 工具调不通，HITL 审批也就无从触发。
> 3. 本地自建模型会被成本统计按 qwen-plus 价虚报（`emsclaw_backend/route/statistics.py` 兜底分支），需补 rate=0 分支。

> 端到端评测方法与选型结论（17 模型 × 2 张快捷卡片真实运行）见 [模型选型评测](docs/model-evaluation.md)。
> 上述结论背后的机制（显存怎么算、KV cache / 前缀缓存为什么生效、MoE 省的是什么）见 [大模型基础知识与选型指南](docs/llm-basics-and-selection-guide.md)。

## 快速开始

> 想先看效果？直接打开[在线体验](#-在线体验)，无需本地部署。

### 环境

Python 依赖用 [`uv`](https://docs.astral.sh/uv/) 管理。根 `uv.lock` 锁定版本，`pyproject.toml` 配置了国内（aliyun）PyPI 镜像源。

```bash
uv sync                       # 安装所有 workspace 成员的依赖
```

后端用 Python 3.13；sandbox 用 3.12（其依赖在构建时重新解析，**不要**假设共享的 lock 适用）。

### 测试

```bash
pytest                                           # 跑全部测试（testpaths = emsclaw/tests）
pytest emsclaw/tests/test_device_service.py      # 单文件
pytest emsclaw/tests/test_device_orm.py::test_x   # 单个用例
pytest -k device                                 # 按名匹配
```

### 前端

```bash
cd emsclaw/frontend && npm install
npm run dev          # Vite dev server（/api 代理到 backend，/task-service 代理到 scheduler）
npm run build        # vite build（产物 dist/）
npm run type-check   # vue-tsc 类型检查
npm test             # vitest
```

### Docker（运行完整栈的主要方式）

`docker-compose.yml` 拉起完整栈。首次运行先准备环境变量：

```bash
cp .env.example .env      # 按需填写 API_KEY、Langfuse 密钥等
docker compose up -d
```

Windows 下有 `.bat` 辅助脚本（`rebuild-all.bat`、`rebuild-backend.bat`、`restart-frontend.bat`）。

> **⚠️ 没有热重载：** backend 与 frontend 源码都**没有** bind-mount（`Dockerfile.dev` 把源码 COPY 进镜像跑，无 HMR），容器内运行的就是镜像里的代码。修改 backend Python 或 frontend 源码后**都需重建镜像**：
> ```bash
> docker compose build backend && docker compose up -d backend
> docker compose build frontend && docker compose up -d frontend
> ```
> `restart-frontend.bat` / `restart backend` 只重启不重建，**不会**加载新代码。

## 文档导航

| 文档 | 内容 | 适合谁 |
|---|---|---|
| **[业务介绍](docs/business.md)** | EMS 为什么需要 Agent、传统配置表的三个前提如何被打破（含 2025—2026 实测账本数据）、三种技术路线 15 维对比、应用场景与不该用的边界、痛点 → 模块对应 | 业务方、产品、技术选型 |
| **[架构](docs/architecture.md)** | 服务拓扑与端口、后端分层、Agent 运行时（deepagents 0.6.x）、SSE 数据流与生产者/消费者解构、HITL 审批全链路、提示词五层边界、技术栈与部署 | 后端、架构、二次开发 |
| **[演示](docs/demo.md)** | 在线环境入口、7 张界面截图导览、快捷卡片端到端验证基线（9 卡 / 535.5s / $0.12）、在线 LLM-as-Judge + 离线 Code Evaluator 双层评测、Langfuse 可观测 | 首次体验、评测、运维 |
| **[模型选型评测](docs/model-evaluation.md)** | 17 个模型 × 2 张卡片端到端批量评测（34 次真实运行）：评分维度与权重、选型结论与理由、物理下限独立校验、需量电费折算成本（元/月 vs 元/次）、复现步骤 | 选型、评测、成本决策 |
| **[大模型基础知识与选型指南](docs/llm-basics-and-selection-guide.md)** | 从「一个 token 怎么被算出来」讲到选型决策：分词 / 嵌入 / QKV / 注意力 / FFN / 采样、KV cache 与前缀缓存（链式哈希）、PagedAttention、稠密与 MoE、TTFT / TPS、自建 vs 买 API、按显存预算分档与量化 / 引擎选型；30 节正文 + 现象解释索引 + 公式与参数速查 | 团队技术底稿、新人入门、选型讨论 |

专题文档：

- [模型评测原始数据表](docs/model-matrix-data.md)（自动生成，勿手工编辑）与 [原始结果 JSON](docs/model-matrix-results.json) —— 由 `scripts/model_matrix_report.py` 生成
- [需求响应（DR）事件闭环设计](docs/design-demand-response-workflow.md) —— 待实现的独立工作流入口设计稿
- [设备巡检工作流设计](docs/design-patrol-workflow.md) —— 待实现的独立工作流入口设计稿
- [Langfuse Judge 配置与排查](docs/langfuse-judge-setup.md)
- [SSE 队列 / Worker / Agent 流程图](docs/sse-queue-worker-agent-flow.svg)
- [SSE 全链路分解图（架构 / 时序 / 审批流 / 审批 UI）](docs/sse-pipeline/)

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy(async) · LangGraph · DeepAgents 0.6.x · langchain-openai |
| 前端 | Vue 3 · Vite · TypeScript · Tailwind · reka-ui · xterm · monaco · marked+katex+mermaid |
| 任务调度 | Python 3.13 · FastAPI · Celery · croniter · Redis |
| 沙箱 | Python 3.12 · 远程代码执行 + 文件系统沙箱 |
| 数据 | PostgreSQL 16 · Redis 7 |
| 工具链 | [`uv`](https://docs.astral.sh/uv/) · Docker Compose · pytest |

## 贡献

欢迎提交 Issue 与 Pull Request。提交前请确保：

```bash
pytest                                              # 后端（rootdir = 仓库根）
cd emsclaw/frontend && npm run type-check && npm test   # 前端
```

## License

本项目基于 [MIT License](LICENSE) 开源。
