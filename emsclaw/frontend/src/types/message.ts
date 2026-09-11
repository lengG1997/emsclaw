import type { FileInfo } from '../api/file';
import type { ToolMetaData, StatisticsData, RoundFileInfo } from './event';

export type MessageType = "user" | "assistant" | "tool" | "step" | "attachments" | "thinking" | "subagent";

export interface Message {
  type: MessageType;
  content: BaseContent;
}

export interface BaseContent {
  timestamp: number;
}

export interface MessageContent extends BaseContent {
  content: string;
  /** 该轮对话的统计信息 */
  statistics?: StatisticsData;
  /** 本轮新增/修改的文件列表 */
  round_files?: RoundFileInfo[];
}

export interface ToolContent extends BaseContent {
  tool_call_id: string;
  /** 并发批次标识(同一次 LLM 响应派生的 tool_call 共享)。后端从 LangGraph parent_ids[0] 取 */
  batch_id?: string;
  name: string;
  function: string;
  args: any;
  content?: any;
  status: "calling" | "called";
  /** 工具调用耗时（毫秒） */
  duration_ms?: number;
  /** 工具元数据（图标、分类、描述） */
  tool_meta?: ToolMetaData;
  /** Sub-agent type when this is a `task` tool delegation call */
  delegated_to?: string;
}

export interface StepContent extends BaseContent {
  id: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  tools: ToolContent[];
}

export interface AttachmentsContent extends BaseContent {
  role: "user" | "assistant";
  attachments: FileInfo[];
}

export interface ThinkingContent extends BaseContent {
  content: string;
}

/** 子 agent 委派块（agent_call/agent_result + 子 agent 的 thinking/tool/plan 归属于此） */
export interface SubagentContent extends BaseContent {
  agent_id: string;
  subagent_type: string;
  /** 子 agent 显示名（= subagent_type） */
  name: string;
  /** 子 agent 输入（task 工具的 description） */
  input: string;
  status: "running" | "complete" | "error";
  /** 子 agent 思考过程累积 */
  thinking: string;
  /** 子 agent 工具调用列表 */
  tools: ToolContent[];
  /** 子 agent 的 todo/plan */
  plan: StepContent[];
  /** 子 agent 输出（agent_result.result） */
  result?: string;
  parent_tool_call_id?: string;
}