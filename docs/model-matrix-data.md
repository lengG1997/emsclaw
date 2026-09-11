<!-- 本文件由 scripts/model_matrix_report.py --md 自动生成，请勿手工编辑 -->

生成时间：2026-09-11 16:57:45　样本：34 次 run（17 模型 × 2 卡片）　最快 ok 耗时：25.0s

| 模型 | 链路 ok | A 链路 | B 规划 | C 结论 | E 方案有效 | D 效率 | 总均分 | 耗时合计(s) | token 合计 | 成本(元) | 达成峰值(dem/prod) | 真值对账 | 共识复现 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `system-default` | ✅ | 25.0 | 20.0 | 20.0 | 17.7 | 15.0 | **97.7** | 200.0 | 431281 | 0.56 | 1310 / 1461.9 | 3/6 | 0/0 |
| `sys-dashscope-qwen3.6-plus` | ✅ | 25.0 | 20.0 | 20.0 | 16.0 | 12.4 | **93.4** | 289.0 | 438879 | 1.20 | 1303 / 1304 | 3/6 | 0/0 |
| `sys-dashscope-qwen3.5-plus` | ✅ | 25.0 | 20.0 | 20.0 | 16.0 | 12.0 | **93.0** | 317.0 | 405455 | 0.48 | 1303 / 1304 | 3/6 | 0/0 |
| `sys-dashscope-qwen3.6-27b` | ✅ | 25.0 | 20.0 | 17.0 | 16.0 | 9.0 | **87.0** | 396.0 | 581077 | — | 1303 / 1304 | 3/6 | 0/0 |
| `sys-dashscope-qwen3.6-flash-2026-04-16` | ✅ | 25.0 | 20.0 | 20.0 | 5.9 | 15.0 | **85.9** | 146.0 | 369820 | 0.64 | — / 1310 | 4/6 | 0/0 |
| `sys-dashscope-qwen3.6-max-preview` | ✅ | 25.0 | 20.0 | 20.0 | 7.1 | 12.8 | **84.9** | 259.0 | 386526 | 3.24 | — / 1512.4 | 2/6 | 0/0 |
| `sys-dashscope-qwen3.6-plus-2026-04-02` | ✅ | 25.0 | 20.0 | 20.0 | 7.3 | 11.9 | **84.2** | 301.0 | 469341 | 1.28 | 1310 / 1634.9 | 4/6 | 0/0 |
| `sys-dashscope-qwen3.6-flash` | ✅ | 25.0 | 18.5 | 20.0 | 5.4 | 15.0 | **83.9** | 107.0 | 349363 | 0.58 | — / 1350 | 3/6 | 0/0 |
| `sys-dashscope-qwen3.6-35b-a3b` | ✅ | 25.0 | 17.0 | 20.0 | 5.3 | 15.0 | **82.3** | 90.0 | 231985 | — | 1350 / — | 3/6 | 0/0 |
| `sys-dashscope-qwen3.5-plus-2026-04-20` | ❌ | 12.5 | 16.5 | 12.0 | 5.4 | 5.2 | **51.7** | 252.0 | 166998 | 0.20 | 1634.9 / — | 2/6 | 0/0 |
| `sys-dashscope-qwen3.5-35b-a3b` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 7.0 | 0 | — | — / — | 0/6 | 0/0 |
| `sys-dashscope-qwen3.5-122b-a10b` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 8.0 | 0 | — | — / — | 0/6 | 0/0 |
| `sys-dashscope-qwen3.5-flash-2026-02-23` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 8.0 | 0 | — | — / — | 0/6 | 0/0 |
| `sys-dashscope-qwen3.5-flash` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 9.0 | 0 | — | — / — | 0/6 | 0/0 |
| `sys-dashscope-qwen3.5-plus-2026-02-15` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 9.0 | 0 | — | — / — | 0/6 | 0/0 |
| `sys-dashscope-qwen3.5-27b` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 10.0 | 0 | — | — / — | 0/6 | 0/0 |
| `sys-dashscope-qwen3.5-397b-a17b` | ❌ | 0.0 | 0.0 | 4.0 | 0.0 | 0.0 | **4.0** | 10.0 | 0 | — | — / — | 0/6 | 0/0 |

### 物理共识交叉校验（正确性代理，不计分）

**demand_cap**：17 次运行，入榜阈值 7 次；共识物理常量 = 1250 kW, 1303 kW, 1524.5 kW

| 模型 | 复现共识常量 |
|---|---|
| `sys-dashscope-qwen3.5-plus-2026-04-20` | 3/3 |
| `sys-dashscope-qwen3.6-27b` | 3/3 |
| `sys-dashscope-qwen3.6-35b-a3b` | 3/3 |
| `sys-dashscope-qwen3.6-flash` | 3/3 |
| `sys-dashscope-qwen3.6-flash-2026-04-16` | 3/3 |
| `sys-dashscope-qwen3.6-plus` | 3/3 |
| `sys-dashscope-qwen3.6-plus-2026-04-02` | 3/3 |
| `system-default` | 3/3 |
| `sys-dashscope-qwen3.5-plus` | 2/3 |
| `sys-dashscope-qwen3.6-max-preview` | 2/3 |
| `sys-dashscope-qwen3.5-122b-a10b` | 0/3 |
| `sys-dashscope-qwen3.5-27b` | 0/3 |
| `sys-dashscope-qwen3.5-35b-a3b` | 0/3 |
| `sys-dashscope-qwen3.5-397b-a17b` | 0/3 |
| `sys-dashscope-qwen3.5-flash` | 0/3 |
| `sys-dashscope-qwen3.5-flash-2026-02-23` | 0/3 |
| `sys-dashscope-qwen3.5-plus-2026-02-15` | 0/3 |

**production_priority**：17 次运行，入榜阈值 7 次；共识物理常量 = 1250 kW, 1303 kW, 1304 kW

| 模型 | 复现共识常量 |
|---|---|
| `sys-dashscope-qwen3.6-27b` | 3/3 |
| `sys-dashscope-qwen3.6-35b-a3b` | 3/3 |
| `sys-dashscope-qwen3.6-flash` | 3/3 |
| `sys-dashscope-qwen3.6-max-preview` | 3/3 |
| `sys-dashscope-qwen3.6-plus` | 3/3 |
| `sys-dashscope-qwen3.6-plus-2026-04-02` | 3/3 |
| `sys-dashscope-qwen3.5-plus` | 2/3 |
| `sys-dashscope-qwen3.6-flash-2026-04-16` | 2/3 |
| `system-default` | 2/3 |
| `sys-dashscope-qwen3.5-122b-a10b` | 0/3 |
| `sys-dashscope-qwen3.5-27b` | 0/3 |
| `sys-dashscope-qwen3.5-35b-a3b` | 0/3 |
| `sys-dashscope-qwen3.5-397b-a17b` | 0/3 |
| `sys-dashscope-qwen3.5-flash` | 0/3 |
| `sys-dashscope-qwen3.5-flash-2026-02-23` | 0/3 |
| `sys-dashscope-qwen3.5-plus-2026-02-15` | 0/3 |
| `sys-dashscope-qwen3.5-plus-2026-04-20` | 0/3 |

