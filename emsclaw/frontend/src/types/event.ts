import type { FileInfo } from '../api/file';

export type AgentSSEEvent = {
  event: 'tool' | 'step' | 'message' | 'error' | 'done' | 'title' | 'wait' | 'plan' | 'attachments' | 'thinking' | 'message_chunk' | 'message_chunk_done' | 'statistics' | 'approval' | 'agent';
  data: ToolEventData | StepEventData | MessageEventData | ErrorEventData | DoneEventData | TitleEventData | WaitEventData | PlanEventData | ThinkingEventData | ApprovalEventData | AgentEventData;
}

export interface BaseEventData {
  event_id: string;
  timestamp: number;
}

/** 工具元数据（图标、分类、描述） */
export interface ToolMetaData {
  icon: string;
  category: string;
  description: string;
  sandbox?: boolean;
}

export interface ToolEventData extends BaseEventData {
  tool_call_id: string;
  /** 并发批次标识:同一次 LLM 响应派生的多个 tool_call 共享同一 batch_id(=LangGraph parent_ids[0])。
   *  前端按 batch_id 聚类并排渲染,区分「并发」vs「顺序」。 */
  batch_id?: string;
  name: string;
  status: "calling" | "called";
  function: string;
  args: {[key: string]: any};
  content?: any;
  /** 工具调用耗时（毫秒），仅 status=called 时存在 */
  duration_ms?: number;
  /** 工具元数据（图标、分类、描述） */
  tool_meta?: ToolMetaData;
  /** 子 agent 归属（v2 透传）。主 agent 时缺失/depth=0；子 agent depth=1 */
  agent_id?: string;
  depth?: number;
}

export interface StepEventData extends BaseEventData {
  status: "pending" | "running" | "completed" | "failed"
  id: string
  description: string
  tools?: ToolEventData[]
}

export interface MessageEventData extends BaseEventData {
  content: string;
  role: "user" | "assistant";
  attachments: FileInfo[];
}

export interface ErrorEventData extends BaseEventData {
  error: string;
}

/** 统计信息 */
export interface StatisticsData {
  total_duration_ms?: number;
  tool_call_count?: number;
  input_tokens?: number;
  cached_tokens?: number;
  output_tokens?: number;
  token_count?: number;
  /** 本轮 Langfuse trace id —— 点赞/踩时回传给后端写入 user_feedback score */
  trace_id?: string;
}

/** 轮次文件信息（done 事件中携带） */
export interface RoundFileInfo {
  file_id: string;
  filename: string;
  relative_path: string;
  size: number;
  upload_date: string;
  file_url: string;
  category: 'output' | 'research_data';
  /** 是否为报告/交付物（后端权威判定：reports/ 目录 或 文档类扩展名） */
  is_report?: boolean;
}

export interface DoneEventData extends BaseEventData {
  /** 执行统计信息 */
  statistics?: StatisticsData;
  /** 本轮新增/修改的文件列表 */
  round_files?: RoundFileInfo[];
}

export interface WaitEventData extends BaseEventData {
}

export interface TitleEventData extends BaseEventData {
  title: string;
}

export interface PlanEventData extends BaseEventData {
  steps: StepEventData[];
  /** 子 agent 归属（v2 透传） */
  agent_id?: string;
  depth?: number;
}

/** 思考过程事件 */
export interface ThinkingEventData extends BaseEventData {
  content: string;
  /** 子 agent 归属（v2 透传） */
  agent_id?: string;
  depth?: number;
}

// ── HITL 审批事件（C2 mapper: approval_required/decided/auto_approve_set）──
/** 单个待审批动作（工具调用） */
export interface ApprovalActionRequest {
  name: string;
  args: { [key: string]: any };
  description?: string;
}

/** 审批配置：声明该动作允许的决策类型 */
export interface ApprovalReviewConfig {
  action_name: string;
  allowed_decisions: string[];  // approve|reject|edit|respond 子集
  description?: string;
}

export interface ApprovalEventData extends BaseEventData {
  /** required=待审批;decided=已决策;auto_approve_set=自动审批开关切换 */
  kind: "required" | "decided" | "auto_approve_set";
  interrupt_id?: string;
  /** kind=required 时：待审批的工具调用列表 */
  action_requests?: ApprovalActionRequest[];
  /** kind=required 时：每个动作允许的决策类型（前端按此渲染按钮子集） */
  review_configs?: ApprovalReviewConfig[];
  raw_value?: { [key: string]: any };
  /** kind=decided 时：决策类型 */
  decision?: string;
  /** kind=decided 时：是否自动决策 */
  auto?: boolean;
  /** kind=auto_approve_set 时：开关是否开启 */
  enabled?: boolean;
}

// ── 子 agent 委派事件（C2 mapper: agent_call/agent_result）──
export interface AgentEventData extends BaseEventData {
  /** call=子 agent 开始;result=子 agent 结束 */
  kind: "call" | "result";
  agent_id: string;
  subagent_type: string;
  depth: number;
  /** kind=call 时：子 agent 的输入（task 工具的 description） */
  description?: string;
  /** kind=result 时：子 agent 的输出 */
  result?: string;
  parent_tool_call_id?: string;
}