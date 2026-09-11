import { AgentSSEEvent } from "./event";

export enum SessionStatus {
    PENDING = "pending",
    RUNNING = "running",
    WAITING = "waiting",
    COMPLETED = "completed",
    AWAITING_APPROVAL = "awaiting_approval"
}

export interface CreateSessionResponse {
    session_id: string;
}

export interface GetSessionResponse {
    session_id: string;
    title: string | null;
    status: SessionStatus;
    events: AgentSSEEvent[];
    is_shared: boolean;
    mode: string;
    model_config_id: string | null;
}

export interface ListSessionItem {
    session_id: string;
    title: string | null;
    latest_message: string | null;
    latest_message_at: number | null;
    status: SessionStatus;
    unread_message_count: number;
    is_shared: boolean;
    mode: string;
    pinned?: boolean;
    source?: string | null;
}

export interface ListSessionResponse {
    sessions: ListSessionItem[];
}

export interface ConsoleRecord {
    ps1: string;
    command: string;
    output: string;
  }
  
  export interface ShellViewResponse {
    output: string;
    session_id: string;
    console: ConsoleRecord[];
  }

export interface FileViewResponse {
    content: string;
    file: string;
}

export interface SignedUrlResponse {
    signed_url: string;
    expires_in: number;
}

export interface ShareSessionResponse {
    session_id: string;
    is_shared: boolean;
}

export interface SharedSessionResponse {
    session_id: string;
    title: string | null;
    status: SessionStatus;
    events: AgentSSEEvent[];
    is_shared: boolean;
}

export interface SkillItem {
    name: string;
    files: string[];
}

export interface ExternalSkillItem {
    name: string;
    description: string;
    files: string[];
    blocked: boolean;
    builtin?: boolean;
    /** 内置 skill 所属的领域 Agent 名（仅 builtin 时有值） */
    domain?: string;
}

// ── Agent 视图：父子 Agent 清单（Lead + 领域子 agent）──

export interface AgentTool {
    name: string;
    description: string;
    /** 参数 schema 的 properties（JSON schema） */
    args: Record<string, any>;
}

export interface AgentSkill {
    name: string;
    description: string;
    files: string[];
}

export interface AgentInfo {
    name: string;
    label: string;
    kind: 'lead' | 'domain';
    description: string;
    /** Langfuse 提示词名（版本化 key） */
    prompt_name: string;
    /** 本地提示词源（git 真相源 / Langfuse 种子） */
    prompt: string;
    /** Lead 提示词是模板（含 {capabilities} 占位，运行时注入） */
    prompt_is_template: boolean;
    tools: AgentTool[];
    skills: AgentSkill[];
    /** 触发 HITL 审批的工具 {tool_name: {allowed_decisions, description}} */
    interrupt_on: Record<string, any>;
    /** Lead 可分派的子 agent 名单（仅 kind=lead） */
    subagents?: string[];
}

export interface AgentRoster {
    agents: AgentInfo[];
    langfuse_enabled: boolean;
}
  