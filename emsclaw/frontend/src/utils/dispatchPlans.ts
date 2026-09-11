/**
 * 多方案对比卡:回传文本拼装。
 *
 * 为什么需要它:LLM 看不到前端卡片,只知道自己正文里的命名(可能是 A/B/C),
 * 而卡片编号是「求解顺序」。仅回「方案 1」会与 LLM 的命名体系错位 ——
 * 实测发生过:用户点「采用方案 1」,agent 反问"方案 1 指 B / A / C 哪一个"。
 *
 * 解法:回传时带上「编号 + 策略 + 关键指标指纹」,LLM 据此能唯一定位到自己表格的那一行,
 * 从而直接下发,不再反问。
 */

export interface DispatchPlan {
  /** 方案名(LLM 在 optimize_dispatch(plan_label=...) 里指定)。多方案对比的**权威标识**。 */
  plan_label?: string | null;
  target_date?: string;
  strategies?: string[];
  schedule?: Array<{
    hour: number;
    mode: 'charge' | 'discharge' | 'standby';
    power_kw: number;
    soc_target_pct: number;
    period?: string;
  }>;
  summary?: Record<string, number>;
}

const fmt = (v: number | undefined | null): string => {
  if (v === undefined || v === null) return '—';
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
};

/** 方案主标题:优先用 LLM 给的 plan_label,回退到"方案 N"。 */
export const planTitle = (p: DispatchPlan, index: number): string =>
  (p.plan_label && String(p.plan_label).trim()) || `方案 ${index + 1}`;

/**
 * 拼装点击「采用方案X」后发给后端的用户消息。
 *
 * 为什么带这么多东西:LLM 看不到前端卡片。若只回「方案 1」,会与它自己的命名/顺序错位 ——
 * 实测两次都因此被反问(一次是它用 A/B/C,一次是并行求解导致卡片编号与正文编号不一致)。
 * 带上 plan_label(LLM 自己起的名字)+ 关键指标,LLM 才能唯一定位,直接下发。
 */
export const buildPickText = (p: DispatchPlan, index: number): string => {
  const s = p.summary || {};
  const title = planTitle(p, index);
  const strat = p.strategies?.length ? p.strategies.join('+') : '—';
  const fp = [
    `策略=${strat}`,
    `预计节省=${fmt(s.est_savings_yuan)}元/日`,
    `峰谷循环=${fmt((s.charge_kwh || 0) + (s.discharge_kwh || 0))}kWh`,
    `绿电率=${s.green_rate != null ? (Number(s.green_rate) * 100).toFixed(0) + '%' : '—'}`,
    `需量峰值=${fmt(s.peak_demand_kw)}kW`,
  ].join('，');
  return `采用多方案对比中的「${title}」方案（${fp}），请按该方案直接下发执行。`;
};

