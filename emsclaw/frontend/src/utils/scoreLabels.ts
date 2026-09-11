/**
 * 评分维度共享工具：维度名中文映射 + 颜色阈值。
 * ScoreOverviewPage 和 ScoreTracesPage 共用。
 */

// ── 维度名中文映射 ──
export const DIM_LABELS: Record<string, string> = {
  // 在线 LLM-as-Judge: 工具调用质量
  tool_selection: '工具选型',
  'tool_selection-trace': '工具选型',
  tool_order_reasoning: '调用顺序',
  'tool_order_reasoning-trace': '调用顺序',
  argument_quality: '参数质量',
  'argument_quality-trace': '参数质量',
  result_utilization: '结果利用',
  'result_utilization-trace': '结果利用',
  // 离线 Code evaluator: 结构性检查
  tool_set: '工具集',
  tool_order: '工具顺序',
  subagent: '子Agent路由',
  tool_count: '工具用量',
  repeat_rate: '重复率',
  tool_result_quality: '结果质量',
  tool_args_validity: '参数有效性',
  tool_efficiency: '工具效率',
};

export function dimensionLabel(name: string): string {
  return DIM_LABELS[name] || name;
}

// ── 评分标准（用于 tooltip 展示，与 evaluator prompt 一致）──
export const SCORING_CRITERIA: Record<string, string> = {
  tool_selection: `工具选型评分标准（1-5）：
5：每一步都选了最合适的工具，无遗漏、无多余调用
4：绝大部分步骤工具选型正确，仅个别次优选择
3：大部分步骤工具正确，但有明显选型不当
2：多个关键步骤选错工具，影响任务完成
1：大量工具选型错误，任务基本未完成`,
  tool_order_reasoning: `调用顺序评分标准（1-5）：
5：调用顺序完全合理，先获取数据再分析再行动，逻辑链条清晰
4：整体顺序合理，个别步骤可以优化
3：部分步骤顺序存在问题，但不影响核心结果
2：明显有步骤颠倒或跳跃，影响了执行效率
1：调用顺序混乱，完全不符合分析逻辑`,
  argument_quality: `参数质量评分标准（1-5）：
5：所有参数准确完整，必需字段不缺，值域合理
4：绝大多数参数正确，仅个别参数有轻微偏差
3：参数基本可用，但存在缺失或不当参数
2：关键参数缺失或明显错误，影响工具执行结果
1：参数大面积错误，工具基本无法正确执行`,
  result_utilization: `结果利用评分标准（1-5）：
5：工具返回的关键数据和结论全部被正确整合到最终回复中
4：绝大部分工具结果被有效利用，仅个别遗漏
3：部分工具结果未被利用，或利用方式不够准确
2：多个工具调用结果被忽视或误用
1：工具调用与最终回复严重脱节，结果基本白费`,
};

// ── 工具名中文映射 ──
export const TOOL_LABELS: Record<string, string> = {
  read_file: '读取文件',
  write_file: '写入文件',
  execute: '执行命令',
  ls: '列出目录',
  glob: '搜索文件',
  grep: '文本搜索',
  optimize_dispatch: '优化调度',
  account_revenue: '收益核算',
  get_current_time: '获取时间',
  write_todos: '任务规划',
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name;
}

// ── 分值颜色阈值（归一化：兼容 0-1 和 1-5 两种分制） ──

const HIGH_GREEN = 0.8; // ≥80%=绿（好）
const MID_YELLOW = 0.5; // ≥50%=黄（及格）
// <50%=红（差）

function normalizeScore(v: number): number {
  // 如果值 > 1，可能是 1-5 分制（LLM-as-Judge），归一化到 0-1
  return v > 1 ? v / 5 : v;
}

/** 返回 CSS class：text-[var(--function-success)] / warning / error */
export function scoreValueClassFromNum(v: number): string {
  const n = normalizeScore(v);
  if (n >= HIGH_GREEN) return 'text-[var(--function-success)]';
  if (n >= MID_YELLOW) return 'text-[var(--function-warning)]';
  return 'text-[var(--function-error)]';
}

/** 返回 CSS class：bg-[var(--function-success)] / warning / error（用于维度色条小色块） */
export function scoreBarClassFromNum(v: number): string {
  const n = normalizeScore(v);
  if (n >= HIGH_GREEN) return 'bg-[var(--function-success)]';
  if (n >= MID_YELLOW) return 'bg-[var(--function-warning)]';
  return 'bg-[var(--function-error)]';
}
