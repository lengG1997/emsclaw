<template>
  <div class="flex flex-col h-full w-full overflow-hidden">
    <!-- Masthead -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1800px] mx-auto flex items-end justify-between gap-4 flex-wrap">
        <div class="flex items-end gap-3">
          <div class="flex items-center gap-2.5">
            <span class="size-2 rounded-full" :class="loading ? 'bg-[var(--function-warning)] animate-pulse' : 'bg-[var(--function-success)]'"></span>
            <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">会话评分</h1>
            <MetricInfo v-bind="EXPLAINERS.scoreTracesIntro" />
          </div>
          <div v-if="data" class="text-xs text-[var(--text-tertiary)] pb-0.5 font-mono">
            {{ windowLabel }} · {{ versionSel || '全部版本' }} · {{ data.sessions.length }} 个会话
          </div>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <!-- sessionId 检索 -->
          <div class="flex items-center gap-1">
            <span class="text-[11px] text-[var(--text-tertiary)]">sessionId</span>
            <input v-model="sessionIdInput" type="text" placeholder="粘贴或输入 sessionId 精确定位"
              @keydown.enter="applySessionId"
              class="h-8 w-[260px] rounded-md border border-[var(--border-main)] bg-[var(--background-card)] text-xs text-[var(--text-primary)] px-2 placeholder:text-[var(--text-tertiary)]/60 focus:outline-none focus:border-[#3a6b8c]" />
            <button @click="applySessionId" :disabled="loading"
              class="h-8 px-2 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors text-xs disabled:opacity-40">
              检索
            </button>
            <button v-if="sessionIdSel" @click="clearSessionId" :disabled="loading"
              class="h-8 px-2 rounded-md border border-[var(--border-main)] text-[var(--text-tertiary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors text-xs disabled:opacity-40"
              title="清除 sessionId 过滤">
              ×
            </button>
          </div>
          <!-- 版本筛选 -->
          <div class="flex items-center gap-1">
            <span class="text-[11px] text-[var(--text-tertiary)]">版本</span>
            <MetricInfo v-bind="EXPLAINERS.scoreVersionFilter" />
            <select v-model="versionSel" :disabled="loading"
              class="h-8 rounded-md border border-[var(--border-main)] bg-[var(--background-card)] text-xs text-[var(--text-primary)] px-2 max-w-[140px] disabled:opacity-40 focus:outline-none focus:border-[#3a6b8c]">
              <option value="">全部版本</option>
              <option v-for="v in versionOptions" :key="v" :value="v">v{{ v }}</option>
            </select>
          </div>
          <!-- 时间窗口 -->
          <div class="flex items-center rounded-md border border-[var(--border-main)] overflow-hidden">
            <button v-for="w in WINDOWS" :key="w[0]" @click="windowSel = w[0]"
              class="px-3 h-8 text-xs transition-colors"
              :class="windowSel === w[0] ? 'bg-[#3a6b8c] text-white' : 'text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)]'">
              {{ w[1] }}
            </button>
          </div>
          <button @click="refresh" :disabled="loading"
            class="size-8 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center justify-center disabled:opacity-40"
            title="刷新">
            <RefreshCw :size="13" :class="{ 'animate-spin': loading }" />
          </button>
        </div>
      </div>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto bg-[var(--background-gray-main)]">
      <!-- 未启用 -->
      <div v-if="disabledState" class="flex flex-col items-center justify-center h-full text-center gap-3 px-6">
        <AlertTriangle :size="28" class="text-[var(--function-warning)]" />
        <div class="text-sm text-[var(--text-secondary)]">Langfuse 可观测性未启用</div>
        <div class="text-xs text-[var(--text-tertiary)] max-w-md leading-relaxed">
          会话评分页需要 Langfuse 提供数据。请在启动 backend 时叠加 Langfuse 配置
          (<span class="font-mono">LANGFUSE_ENABLED=true</span> 及 public/secret key、base_url),然后重启。
        </div>
      </div>

      <!-- 加载中且无数据 -->
      <div v-else-if="loading && !hasData" class="flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] gap-3">
        <RefreshCw :size="24" class="animate-spin text-[var(--text-disable)]" />
        <span class="text-xs font-mono">SYNC…</span>
      </div>

      <!-- 无评分数据 -->
      <div v-else-if="!hasData" class="flex flex-col items-center justify-center h-full text-center gap-3 px-6">
        <Award :size="28" class="text-[var(--text-disable)]" />
        <div class="text-sm text-[var(--text-secondary)]">
          {{ sessionIdSel ? `没有找到 sessionId=${sessionIdSel.slice(0, 16)}… 的会话` : '还没有会话评分数据' }}
        </div>
        <div v-if="!sessionIdSel" class="text-xs text-[var(--text-tertiary)] max-w-lg leading-relaxed text-left">
          评分由 Langfuse 的 LLM-as-judge evaluator 自动产生。配置步骤:
          <ol class="list-decimal ml-5 mt-1.5 space-y-1">
            <li>打开 <span class="font-mono text-[var(--text-secondary)]">http://localhost:3001</span> 登录 Langfuse。</li>
            <li>在 <span class="text-[var(--text-secondary)]">Evaluators</span> 新建 LLM-as-judge,filter 选 name=LangGraph(只评整次对话)。</li>
            <li>和 Agent 聊几句,新对话会自动被打分,回本页即可看到。</li>
          </ol>
        </div>
        <MetricInfo v-bind="EXPLAINERS.judgeHow" />
      </div>

      <!-- 数据主体：会话列表 -->
      <div v-else-if="data" class="max-w-[1100px] mx-auto p-6 pt-4 space-y-3">
        <SessionScoreCard
          v-for="s in pagedSessions"
          :key="s.session_id"
          :session="s"
          :linking="linkingIds.has(s.session_id)"
          @open-chat="openChat"
        />

        <!-- 提示行 -->
        <div v-if="data.sessions.length === 0" class="text-center text-xs text-[var(--text-tertiary)] py-8">
          {{ sessionIdSel ? `当前 sessionId 没有匹配的会话评分。` : `当前筛选条件下没有会话评分数据。` }}
        </div>

        <!-- 分页 -->
        <div v-else-if="totalPages > 1" class="flex items-center justify-between pt-2 text-xs text-[var(--text-tertiary)]">
          <div class="font-mono">
            第 {{ pageStart }}-{{ pageEnd }} 条 / 共 {{ data.sessions.length }} 条
          </div>
          <div class="flex items-center gap-1">
            <button @click="goPage(1)" :disabled="pageSel === 1"
              class="h-7 px-2 rounded border border-[var(--border-main)] hover:bg-[var(--background-gray-main)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              «
            </button>
            <button @click="goPage(pageSel - 1)" :disabled="pageSel === 1"
              class="h-7 px-2 rounded border border-[var(--border-main)] hover:bg-[var(--background-gray-main)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              ‹
            </button>
            <span class="px-2 font-mono">{{ pageSel }} / {{ totalPages }}</span>
            <button @click="goPage(pageSel + 1)" :disabled="pageSel === totalPages"
              class="h-7 px-2 rounded border border-[var(--border-main)] hover:bg-[var(--background-gray-main)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              ›
            </button>
            <button @click="goPage(totalPages)" :disabled="pageSel === totalPages"
              class="h-7 px-2 rounded border border-[var(--border-main)] hover:bg-[var(--background-gray-main)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              »
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { RefreshCw, AlertTriangle, Award } from 'lucide-vue-next';
import MetricInfo from '@/components/MetricInfo.vue';
import SessionScoreCard from '@/components/score-traces/SessionScoreCard.vue';
import { EXPLAINERS } from '@/constants/explainers';
import { getLangfuseStatus, getLangfuseScoreTraces, lookupSessionByThread } from '@/api/langfuse';
import type { LangfuseScoreTraces, LangfuseScoreSession, LangfuseStatus } from '@/types/langfuse';
import { showErrorToast } from '@/utils/toast';
import { useRouter } from 'vue-router';

const WINDOWS: [string, string][] = [['today', '今日'], ['7d', '7天'], ['30d', '30天']];
const PAGE_SIZE = 20;

const router = useRouter();
const loading = ref(false);
const status = ref<LangfuseStatus | null>(null);
const data = ref<LangfuseScoreTraces | null>(null);
const windowSel = ref('7d');
const versionSel = ref('');
const sessionIdInput = ref('');
const sessionIdSel = ref('');
const versionOptions = ref<string[]>([]);
const pageSel = ref(1);
const linkingIds = ref<Set<string>>(new Set());

const totalPages = computed(() => data.value ? Math.max(1, Math.ceil(data.value.sessions.length / PAGE_SIZE)) : 1);
const pagedSessions = computed(() => {
  if (!data.value) return [];
  const start = (pageSel.value - 1) * PAGE_SIZE;
  return data.value.sessions.slice(start, start + PAGE_SIZE);
});
const pageStart = computed(() => data.value && data.value.sessions.length ? (pageSel.value - 1) * PAGE_SIZE + 1 : 0);
const pageEnd = computed(() => data.value ? Math.min(pageSel.value * PAGE_SIZE, data.value.sessions.length) : 0);

function goPage(n: number) {
  pageSel.value = Math.max(1, Math.min(totalPages.value, n));
}

const windowLabel = computed(() => WINDOWS.find((w) => w[0] === windowSel.value)?.[1] ?? windowSel.value);
const disabledState = computed(() => status.value && (!status.value.enabled || !status.value.configured));
const hasData = computed(() => !!data.value && data.value.sessions.length > 0);

function applySessionId() {
  const v = sessionIdInput.value.trim();
  sessionIdSel.value = v;
  pageSel.value = 1;
  refresh();
}
function clearSessionId() {
  sessionIdInput.value = '';
  sessionIdSel.value = '';
  pageSel.value = 1;
  refresh();
}

async function openChat(s: LangfuseScoreSession) {
  const tid = s.session_id;
  if (linkingIds.value.has(tid)) return;
  const next = new Set(linkingIds.value);
  next.add(tid);
  linkingIds.value = next;
  try {
    const { session_id } = await lookupSessionByThread(tid);
    router.push(`/chat/${session_id}`);
  } catch (e: any) {
    const status = e?.response?.status;
    if (status === 404) {
      showErrorToast(`未找到 thread_id=${tid.slice(0, 12)}… 对应的会话（可能已删除）`);
    } else {
      showErrorToast(e?.message ?? '进入会话失败');
    }
  } finally {
    const after = new Set(linkingIds.value);
    after.delete(tid);
    linkingIds.value = after;
  }
}

async function refresh() {
  loading.value = true;
  try {
    data.value = await getLangfuseScoreTraces(
      windowSel.value,
      versionSel.value || null,
      sessionIdSel.value || null,
    );
    if (data.value.available_versions?.length) {
      versionOptions.value = data.value.available_versions;
    }
    if (data.value.error) showErrorToast(data.value.error);
  } catch (e: any) {
    showErrorToast(e?.message ?? '加载会话评分失败');
  } finally {
    loading.value = false;
  }
}

async function loadStatus() {
  try {
    status.value = await getLangfuseStatus();
  } catch {
    status.value = null;
  }
}

watch(windowSel, () => { pageSel.value = 1; refresh(); });
watch(versionSel, () => { pageSel.value = 1; refresh(); });

onMounted(async () => {
  await loadStatus();
  if (!disabledState.value) await refresh();
});
</script>
