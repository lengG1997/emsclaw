import { apiClient, ApiResponse } from './client';
import type {
  LangfuseStatus,
  LangfuseOverview,
  LangfuseScoresOverview,
  LangfuseScoreTraces,
  LangfuseToolsOverview,
  LangfuseDatasetListResponse,
  LangfuseExperimentsOverview,
} from '@/types/langfuse';

export async function getLangfuseStatus(): Promise<LangfuseStatus> {
  const response = await apiClient.get<ApiResponse<LangfuseStatus>>('/langfuse/status');
  return response.data.data;
}

export async function getLangfuseOverview(
  window: string,
  model?: string | null,
): Promise<LangfuseOverview> {
  const params: Record<string, string> = { window };
  if (model) params.model = model;
  const response = await apiClient.get<ApiResponse<LangfuseOverview>>('/langfuse/overview', { params });
  return response.data.data;
}

export async function getLangfuseScores(
  window: string,
  name?: string | null,
): Promise<LangfuseScoresOverview> {
  const params: Record<string, string> = { window };
  if (name) params.name = name;
  const response = await apiClient.get<ApiResponse<LangfuseScoresOverview>>('/langfuse/scores', { params });
  return response.data.data;
}

export async function getLangfuseScoreTraces(
  window: string,
  version?: string | null,
  sessionId?: string | null,
  limit: number = 50,
): Promise<LangfuseScoreTraces> {
  const params: Record<string, string | number> = { window, limit };
  if (version) params.version = version;
  if (sessionId) params.session_id = sessionId;
  const response = await apiClient.get<ApiResponse<LangfuseScoreTraces>>('/langfuse/score-traces', { params });
  return response.data.data;
}

export async function lookupSessionByThread(threadId: string): Promise<{ session_id: string; thread_id: string }> {
  const response = await apiClient.get<ApiResponse<{ session_id: string; thread_id: string }>>(
    `/langfuse/session-by-thread/${encodeURIComponent(threadId)}`,
  );
  return response.data.data;
}

export async function getLangfuseToolsOverview(
  window: string,
  name?: string,
): Promise<LangfuseToolsOverview> {
  const params: Record<string, string> = { window };
  if (name) params.name = name;
  const response = await apiClient.get<ApiResponse<LangfuseToolsOverview>>('/langfuse/tools', { params });
  return response.data.data;
}

export async function getLangfuseDatasets(): Promise<LangfuseDatasetListResponse> {
  const response = await apiClient.get<ApiResponse<LangfuseDatasetListResponse>>('/langfuse/datasets');
  return response.data.data;
}

export async function getLangfuseExperiments(
  dataset?: string | null,
): Promise<LangfuseExperimentsOverview> {
  const params: Record<string, string> = {};
  if (dataset) params.dataset = dataset;
  const response = await apiClient.get<ApiResponse<LangfuseExperimentsOverview>>(
    '/langfuse/experiments',
    { params },
  );
  return response.data.data;
}

export interface LangfusePromptVersion {
  version: number;
  labels: string[];
  prompt: string;
  config?: Record<string, unknown>;
  error?: string;
}

export interface LangfusePromptVersions {
  enabled: boolean;
  configured: boolean;
  name: string;
  versions: LangfusePromptVersion[];
  latest_version: number | null;
  production_version: number | null;
}

export async function getLangfusePromptVersions(
  name: string,
): Promise<LangfusePromptVersions> {
  const response = await apiClient.get<ApiResponse<LangfusePromptVersions>>(
    `/langfuse/prompts/${encodeURIComponent(name)}`,
  );
  return response.data.data;
}
