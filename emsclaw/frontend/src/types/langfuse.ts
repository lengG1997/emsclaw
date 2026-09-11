// Langfuse 模型总览页数据类型（与后端 /api/v1/langfuse/overview 负载一一对应）

export interface LangfuseStatus {
  enabled: boolean;
  configured: boolean;
  base_url: string;
}

export interface LangfuseKpi {
  total_calls: number;
  session_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number; // 美元
  p50_latency_ms: number;
  p95_latency_ms: number;
  avg_ttft_ms: number;
  error_rate: number; // 0~1
}

export interface LangfuseModelRow {
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  tokens: number;
  cost: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  avg_ttft_ms: number;
  error_rate: number;
  tokens_per_sec: number;
}

export interface LangfuseDailyRow {
  date: string; // YYYY-MM-DD
  calls: number;
  tokens: number;
  cost: number;
  p50_latency_ms: number;
  error_rate: number;
}

export interface LangfuseOverview {
  enabled: boolean;
  configured: boolean;
  model: string | null;
  window: { days: string; from: string; to: string };
  kpi: LangfuseKpi | null;
  by_model: LangfuseModelRow[];
  daily: LangfuseDailyRow[];
  error?: string;
}

// ── 质量评分（LLM-as-judge）──
export interface LangfuseScoreKpi {
  score_count: number;
  avg_score: number;
  score_name_count: number;
  score_model_count: number;
}

export interface LangfuseScoreNameRow {
  name: string;
  count: number;
  avg_value: number;
}

export interface LangfuseScoreModelRow {
  model: string;
  count: number;
  avg_value: number;
}

export interface LangfuseScoreDailyRow {
  date: string;
  count: number;
  avg_value: number;
}

export interface LangfuseScoreDistRow {
  value: number;
  count: number;
}

export interface LangfuseScoresOverview {
  enabled: boolean;
  configured: boolean;
  name: string | null;
  window: { days: string; from: string; to: string };
  kpi: LangfuseScoreKpi | null;
  by_name: LangfuseScoreNameRow[];
  by_model: LangfuseScoreModelRow[];
  daily: LangfuseScoreDailyRow[];
  distribution: LangfuseScoreDistRow[];
  error?: string;
}

// ── 评分会话视图（按 session 聚合，session 下多个 trace 每个含评分 + 理由）──
export interface LangfuseScoreItem {
  id: string;
  name: string;
  value: number | string | boolean | null;
  data_type: 'NUMERIC' | 'BOOLEAN' | 'CATEGORICAL' | 'TEXT' | 'CORRECTION';
  comment: string; // 评分理由（LLM-as-judge 给的中文解释）
  timestamp: string;
  source: string;
}

export interface ToolCallStep {
  name: string;            // 工具名，如 "read_file"
  input: string;           // 参数 JSON
  output: string;          // 结果 JSON
  start_time: string;
  end_time: string;
  latency: number | null;  // 秒
  observation_id: string;
  scores: LangfuseScoreItem[];  // 挂在这个步骤上的评分
}

export interface LangfuseScoreTrace {
  trace_id: string;
  observation_id: string;
  session_id: string;
  version: string;
  mode: string;
  query: string;
  output: string;
  started_at: string;
  score_count: number;
  avg_score: number | null;
  scores: LangfuseScoreItem[];
  tool_steps: ToolCallStep[];
}

export interface LangfuseScoreSession {
  session_id: string;
  version: string;
  mode: string;
  query: string;
  output: string;
  started_at: string;
  last_at: string;
  trace_count: number;
  score_count: number;
  avg_score: number | null;
  traces: LangfuseScoreTrace[];
}

export interface LangfuseScoreTraces {
  enabled: boolean;
  configured: boolean;
  version: string | null;
  session_id: string | null;
  window: { days: string; from: string; to: string };
  available_versions: string[];
  sessions: LangfuseScoreSession[];
  error?: string;
}

// ── 工具调用总览（/api/v1/langfuse/tools）──
export interface LangfuseToolKpi {
  tool_call_count: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  error_rate: number;
}

export interface LangfuseToolRow {
  tool: string;
  calls: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  error_rate: number;
}

export interface LangfuseToolDailyRow {
  day: string;
  calls: number;
  avg_latency_ms: number;
  error_rate: number;
}

export interface LangfuseToolsOverview {
  enabled: boolean;
  configured: boolean;
  supported?: boolean;
  error?: string;
  tool?: string | null;
  window?: { days: string; from: string; to: string };
  kpi?: LangfuseToolKpi | null;
  by_tool?: LangfuseToolRow[];
  daily?: LangfuseToolDailyRow[];
}

// ── Experiment 评估(离线 skill 评估闭环)──

export interface LangfuseDataset {
  id: string;
  name: string;
  items_count: number;
  created_at: string | null;
}

export interface LangfuseDatasetListResponse {
  enabled: boolean;
  configured: boolean;
  datasets: LangfuseDataset[];
}

export interface LangfuseExperimentDimension {
  name: string;
  total: number;
  passed: number;
  pass_rate: number; // 0~1
}

export interface LangfuseExperimentRun {
  experiment_id: string;
  experiment_name: string;
  started_at: string | null;
  ended_at: string | null;
  item_count: number;
  scored_count: number;
  overall_pass_rate: number; // 0~1
  dimensions: LangfuseExperimentDimension[];
}

export interface LangfuseExperimentsOverview {
  enabled: boolean;
  configured: boolean;
  dataset: string | null;
  runs: LangfuseExperimentRun[];
}
