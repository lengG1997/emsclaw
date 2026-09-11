import { apiClient, ApiResponse } from './client';

export type ApprovalDecision = 'approve' | 'reject' | 'edit' | 'respond';
export type ApprovalStatus = 'pending' | 'decided' | 'auto_approved';

export interface ApprovalRecord {
  id: string;
  session_id: string;
  thread_id: string;
  interrupt_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  tool_call_id: string | null;
  tool_result: string | null;
  parent_agent: string;
  subagent_type: string | null;
  subagent_instance_id: string | null;
  initiator_user_id: string;
  approver_user_id: string | null;
  decision: ApprovalDecision | null;
  original_request_message: string;
  auto: boolean;
  status: ApprovalStatus;
  created_at: number;
  decided_at: number | null;
  initiator_username: string | null;
  approver_username: string | null;
}

export interface ApprovalsPage {
  items: ApprovalRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListApprovalsParams {
  page?: number;
  page_size?: number;
  status?: ApprovalStatus;
  initiator?: string;
  session_id?: string;
}

export async function listApprovals(params: ListApprovalsParams = {}): Promise<ApprovalsPage> {
  const response = await apiClient.get<ApiResponse<ApprovalsPage>>('/approvals', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
      status: params.status,
      initiator: params.initiator,
      session_id: params.session_id,
    },
  });
  return response.data.data;
}

export async function getApproval(recordId: string): Promise<ApprovalRecord> {
  const response = await apiClient.get<ApiResponse<ApprovalRecord>>(`/approvals/${recordId}`);
  return response.data.data;
}
