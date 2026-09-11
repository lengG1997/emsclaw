import { apiClient, ApiResponse, createSSEConnection, SSECallbacks } from './client';
import type { FileInfo } from './file';
import { ListSessionItem, SessionStatus, GetSessionResponse, SkillItem, ExternalSkillItem, AgentRoster } from '../types/response';

// Re-export or alias if needed for backward compatibility, 
// but prefer using types from response.ts to ensure consistency.
export type Session = ListSessionItem; 
export type SessionDetail = GetSessionResponse;

export interface CreateSessionRequest {
  mode: string;
  model_config_id?: string;
}

export interface ChatRequest {
  message: string;
  timestamp?: number;
  event_id?: string;
  attachments?: string[];
  language?: string;
  model_config_id?: string;
}

export async function createSession(data: CreateSessionRequest): Promise<Session> {
  const response = await apiClient.put<ApiResponse<Session>>('/sessions', data);
  return response.data.data;
}

export async function listSessions(): Promise<Session[]> {
  const response = await apiClient.get<ApiResponse<{sessions: Session[]}>>('/sessions');
  return response.data.data.sessions;
}

export function listSessionsSSE(callbacks: SSECallbacks<any>): Promise<() => void> {
  // Note: backend does not have an SSE endpoint for session listing.
  // This function is kept for compatibility but should not be used in production.
  return createSSEConnection('/sessions', { method: 'GET' }, callbacks);
}

export function subscribeSessionNotifications(callbacks: SSECallbacks<any>): Promise<() => void> {
  return createSSEConnection('/sessions/notifications', { method: 'GET' }, callbacks);
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const response = await apiClient.get<ApiResponse<SessionDetail>>(`/sessions/${sessionId}`);
  return response.data.data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/sessions/${sessionId}`);
}

// 置顶/取消置顶会话
export async function updateSessionPin(sessionId: string, pinned: boolean): Promise<{session_id: string, pinned: boolean}> {
  const response = await apiClient.patch<ApiResponse<{session_id: string, pinned: boolean}>>(`/sessions/${sessionId}/pin`, { pinned });
  return response.data.data;
}

// 重命名会话
export async function updateSessionTitle(sessionId: string, title: string): Promise<{session_id: string, title: string}> {
  const response = await apiClient.patch<ApiResponse<{session_id: string, title: string}>>(`/sessions/${sessionId}/title`, { title });
  return response.data.data;
}

export function chatWithSession(sessionId: string, data: ChatRequest, callbacks: SSECallbacks<any>): Promise<() => void> {
  return createSSEConnection(`/sessions/${sessionId}/chat`, { method: 'POST', body: data }, callbacks);
}

export async function stopSession(sessionId: string): Promise<void> {
  await apiClient.post(`/sessions/${sessionId}/stop`);
}

// ── 用户反馈（点赞/踩 → Langfuse score）──

export interface FeedbackRequest {
  /** like | dislike | none（none=取消之前的选择） */
  value: 'like' | 'dislike' | 'none';
  /** 本轮 Langfuse trace id（取自该轮 statistics.trace_id） */
  trace_id?: string;
  /** 被评价的 assistant 消息 event_id */
  message_event_id?: string;
  /** 点踩原因标签 */
  reasons?: string[];
  /** 用户补充说明 */
  comment?: string;
  /** 切换前的取值（like↔dislike 变更记录） */
  previous_value?: string;
  /** 前端点击时间戳（秒） */
  client_ts?: number;
}

export interface FeedbackResponse {
  ok: boolean;
  /** 是否成功写入 Langfuse（未启用 tracing / 缺 trace_id 时为 false） */
  recorded: boolean;
  trace_id?: string;
  reason?: string;
}

/**
 * 上报用户对某轮回复的点赞/踩。
 * 后端会把本轮上下文（模型/token/耗时/工具/子agent/产物…）一并写入 Langfuse score。
 */
export async function submitFeedback(
  sessionId: string,
  data: FeedbackRequest,
): Promise<FeedbackResponse> {
  const response = await apiClient.post<ApiResponse<FeedbackResponse>>(
    `/sessions/${sessionId}/feedback`,
    data,
  );
  return response.data.data;
}

// ── HITL 审批(C5)──

/** 单个审批决策请求体 */
export interface ApprovalDecisionRequest {
  /** approve | reject | edit | respond */
  decision: string;
  /** decision=edit 时必填,覆盖工具调用的 args */
  edit_payload?: { [key: string]: any };
}

/**
 * 审批 resume - 用户对 pending approval 给决策,触发 resume worker 继续 stream。
 * 返回 SSE 流(与 chatWithSession 同构),剩余事件喂回 handleEvent。
 */
export function resumeApproval(
  sessionId: string,
  interruptId: string,
  body: ApprovalDecisionRequest,
  callbacks: SSECallbacks<any>,
): Promise<() => void> {
  return createSSEConnection(
    `/sessions/${sessionId}/approvals/${encodeURIComponent(interruptId)}`,
    { method: 'POST', body },
    callbacks,
  );
}

/**
 * 开启 auto_approve_all - 后续 pending interrupts 自动 approve。
 * SSE 客户端传 resume=false:只设 flag,前端自己用 resumeApproval SSE 驱动 resume
 * (避免后端 worker 推到无消费者的 queue)。
 */
export async function setAutoApproveAll(
  sessionId: string,
  resume: boolean = false,
): Promise<{ ok: boolean; auto_approve: boolean; resume_triggered: boolean }> {
  const response = await apiClient.post<
    ApiResponse<{ ok: boolean; auto_approve: boolean; resume_triggered: boolean }>
  >(`/sessions/${sessionId}/approvals/auto_approve_all`, null, { params: { resume } });
  return response.data.data;
}

export async function shareSession(sessionId: string): Promise<{session_id: string, is_shared: boolean}> {
  const response = await apiClient.post<ApiResponse<{session_id: string, is_shared: boolean}>>(`/sessions/${sessionId}/share`);
  return response.data.data;
}

export async function unshareSession(sessionId: string): Promise<{session_id: string, is_shared: boolean}> {
  const response = await apiClient.delete<ApiResponse<{session_id: string, is_shared: boolean}>>(`/sessions/${sessionId}/share`);
  return response.data.data;
}

export async function getSharedSession(sessionId: string): Promise<SessionDetail> {
  const response = await apiClient.get<ApiResponse<SessionDetail>>(`/sessions/shared/${sessionId}`);
  return response.data.data;
}

export async function clearUnreadMessageCount(sessionId: string): Promise<void> {
  await apiClient.post(`/sessions/${sessionId}/clear_unread_message_count`);
}

// Tool Views
export async function viewShellSession(sessionId: string, shellSessionId: string): Promise<any> {
  const response = await apiClient.post<ApiResponse<any>>(`/sessions/${sessionId}/shell`, { session_id: shellSessionId });
  return response.data.data;
}

export async function viewFile(sessionId: string, filePath: string): Promise<{file: string, content: string}> {
  const response = await apiClient.post<ApiResponse<{file: string, content: string}>>(`/sessions/${sessionId}/file`, { file: filePath });
  return response.data.data;
}

export async function getVNCUrl(sessionId: string, expireMinutes: number = 15): Promise<{signed_url: string, expires_in: number}> {
  const response = await apiClient.post<ApiResponse<{signed_url: string, expires_in: number}>>(`/sessions/${sessionId}/vnc/signed-url`, { expire_minutes: expireMinutes });
  return response.data.data;
}

export const getSessionFiles = async (session_id: string): Promise<FileInfo[]> => {
  const response = await apiClient.get<ApiResponse<FileInfo[]>>(`/sessions/${session_id}/files`);
  return response.data.data;
};

export const getSharedSessionFiles = async (session_id: string): Promise<FileInfo[]> => {
  const response = await apiClient.get<ApiResponse<FileInfo[]>>(`/sessions/${session_id}/share/files`);
  return response.data.data;
};

export async function getSkills(): Promise<ExternalSkillItem[]> {
  const response = await apiClient.get<ApiResponse<ExternalSkillItem[]>>('/sessions/skills');
  return response.data.data;
}

export async function blockSkill(skillName: string, blocked: boolean): Promise<{skill_name: string, blocked: boolean}> {
  const response = await apiClient.put<ApiResponse<{skill_name: string, blocked: boolean}>>(`/sessions/skills/${encodeURIComponent(skillName)}/block`, { blocked });
  return response.data.data;
}

export async function deleteSkill(skillName: string): Promise<{skill_name: string, deleted: boolean}> {
  const response = await apiClient.delete<ApiResponse<{skill_name: string, deleted: boolean}>>(`/sessions/skills/${encodeURIComponent(skillName)}`);
  return response.data.data;
}

export async function getSkillFiles(skillName: string, path: string = ""): Promise<any[]> {
  const response = await apiClient.get<ApiResponse<any[]>>(`/sessions/skills/${skillName}/files`, { params: { path } });
  return response.data.data;
}

export async function readSkillFile(skillName: string, file: string): Promise<{file: string, content: string}> {
  const response = await apiClient.post<ApiResponse<{file: string, content: string}>>(`/sessions/skills/${skillName}/read`, { file });
  return response.data.data;
}

export function getSkillFileDownloadUrl(skillName: string, path: string): string {
    // Correct URL for sessions router
    return `/api/v1/sessions/skills/${encodeURIComponent(skillName)}/download?path=${encodeURIComponent(path)}`;
}

export async function saveSkillFromSession(sessionId: string, skillName: string): Promise<{skill_name: string, saved: boolean}> {
  const response = await apiClient.post<ApiResponse<{skill_name: string, saved: boolean}>>(`/sessions/${sessionId}/skills/save`, { skill_name: skillName });
  return response.data.data;
}


export async function readSandboxFile(sessionId: string, path: string): Promise<{file: string, content: string}> {
  const response = await apiClient.get<ApiResponse<{file: string, content: string}>>(`/sessions/${sessionId}/sandbox-file`, { params: { path } });
  return response.data.data;
}

export async function downloadSandboxFile(sessionId: string, path: string): Promise<Blob> {
  const response = await apiClient.get(`/sessions/${sessionId}/sandbox-file/download`, {
    params: { path },
    responseType: 'blob',
  });
  return response.data;
}

export async function optimizePrompt(query: string, modelConfigId?: string | null): Promise<{ optimized_query: string }> {
  const payload: Record<string, string> = { query };
  if (modelConfigId) payload.model_config_id = modelConfigId;
  const response = await apiClient.post<ApiResponse<{ optimized_query: string }>>('/agent/optimize_prompt', payload);
  return response.data.data;
}

// ── Agent 视图（父子 Agent 的 tools/skills/提示词一览）──

export async function getAgents(): Promise<AgentRoster> {
  const response = await apiClient.get<ApiResponse<AgentRoster>>('/sessions/agents');
  return response.data.data;
}
