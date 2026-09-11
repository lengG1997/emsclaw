<template>
  <div class="flex flex-col h-full w-full overflow-hidden approvals-page">
    <!-- Masthead -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1800px] mx-auto">
        <div class="flex items-end justify-between gap-4 flex-wrap">
          <div class="flex items-end gap-4">
            <div class="flex items-center gap-2.5">
              <span class="size-2 rounded-full" :class="loading ? 'bg-[var(--function-warning)] animate-pulse' : 'bg-[var(--function-success)]'"></span>
              <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">审批记录</h1>
            </div>
            <div class="flex items-baseline gap-2 pb-0.5">
              <span class="font-mono text-2xl font-semibold tabular-nums text-[var(--text-primary)] leading-none">{{ total }}</span>
              <span class="text-xs text-[var(--text-tertiary)]">条记录</span>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="relative">
              <select v-model="filterStatus" class="appearance-none bg-[var(--background-gray-main)] border border-[var(--border-main)] rounded-md pl-3 pr-8 py-1.5 text-xs text-[var(--text-secondary)] focus:outline-none focus:border-[var(--border-input-active)] transition-colors">
                <option value="">全部状态</option>
                <option value="pending">待审批</option>
                <option value="decided">已决策</option>
                <option value="auto_approved">自动通过</option>
              </select>
              <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-[10px]">▾</span>
            </div>
            <button @click="refresh" class="size-8 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center justify-center" title="刷新">
              <RefreshCw :size="13" :class="{ 'animate-spin': loading }" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Table -->
    <div class="flex-1 overflow-y-auto bg-[var(--background-gray-main)]">
      <div v-if="loading && items.length === 0" class="flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] gap-3">
        <RefreshCw :size="24" class="animate-spin text-[var(--text-disable)]" />
        <span class="text-xs font-mono">SYNC…</span>
      </div>
      <div v-else-if="items.length === 0" class="flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] gap-3 py-20">
        <ShieldCheck :size="28" class="text-[var(--text-disable)]" />
        <span class="text-sm text-[var(--text-secondary)]">无审批记录</span>
        <p class="text-xs">触发需要审批的工具调用后,记录会出现在此处</p>
      </div>
      <div v-else class="max-w-[1800px] mx-auto px-6 py-4">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-[var(--border-dark)] text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
              <th class="px-3 py-2.5 text-left font-medium w-10">#</th>
              <th class="px-3 py-2.5 text-left font-medium">工具</th>
              <th class="px-3 py-2.5 text-left font-medium w-28">父Agent</th>
              <th class="px-3 py-2.5 text-left font-medium w-32">子Agent</th>
              <th class="px-3 py-2.5 text-left font-medium w-24">发起人</th>
              <th class="px-3 py-2.5 text-left font-medium w-24">审批人</th>
              <th class="px-3 py-2.5 text-left font-medium w-32">会话</th>
              <th class="px-3 py-2.5 text-left font-medium">发起消息</th>
              <th class="px-3 py-2.5 text-left font-medium w-24">决策</th>
              <th class="px-3 py-2.5 text-left font-medium w-24">状态</th>
              <th class="px-3 py-2.5 text-left font-medium w-40">时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, idx) in items"
              :key="r.id"
              class="border-b border-[var(--border-light)] hover:bg-[var(--background-card)] transition-colors cursor-pointer"
              @click="openDetail(r)"
            >
              <td class="px-3 py-3 font-mono text-xs text-[var(--text-tertiary)] tabular-nums">{{ String((page - 1) * pageSize + idx + 1).padStart(2, '0') }}</td>
              <td class="px-3 py-3">
                <div class="font-medium text-[var(--text-primary)] font-mono text-xs">{{ r.tool_name || '—' }}</div>
                <div v-if="r.tool_args && Object.keys(r.tool_args).length" class="font-mono text-[10px] text-[var(--text-tertiary)] mt-0.5 truncate max-w-[200px]" :title="JSON.stringify(r.tool_args, null, 2)">
                  {{ JSON.stringify(r.tool_args) }}
                </div>
              </td>
              <td class="px-3 py-3 text-xs text-[var(--text-secondary)]">{{ r.parent_agent || '—' }}</td>
              <td class="px-3 py-3 text-xs">
                <span v-if="r.subagent_type" class="text-[var(--text-secondary)] font-mono">{{ r.subagent_type }}</span>
                <span v-else class="text-[var(--text-disable)]">—</span>
              </td>
              <td class="px-3 py-3 text-xs text-[var(--text-secondary)]">{{ r.initiator_username || r.initiator_user_id || '—' }}</td>
              <td class="px-3 py-3 text-xs text-[var(--text-secondary)]">
                <span v-if="r.approver_username || r.approver_user_id">{{ r.approver_username || r.approver_user_id }}</span>
                <span v-else class="text-[var(--text-disable)]">—</span>
              </td>
              <td class="px-3 py-3">
                <button v-if="r.session_id" @click.stop="openSession(r.session_id)" class="text-xs font-mono text-[#e85d2a] hover:underline truncate max-w-[120px] block" :title="`打开分享页 ${r.session_id}`">
                  {{ r.session_id }}
                </button>
                <span v-else class="text-xs text-[var(--text-disable)]">-</span>
              </td>
              <td class="px-3 py-3 text-xs text-[var(--text-secondary)]">
                <div class="truncate max-w-[280px]" :title="r.original_request_message">
                  {{ r.original_request_message || '—' }}
                </div>
              </td>
              <td class="px-3 py-3">
                <span v-if="r.decision" class="inline-flex items-center gap-1.5 text-xs" :class="decisionText(r.decision)">
                  <span class="size-1.5 rounded-full" :class="decisionDot(r.decision)"></span>
                  {{ decisionLabel(r.decision) }}
                </span>
                <span v-else class="text-xs text-[var(--text-disable)]">—</span>
              </td>
              <td class="px-3 py-3">
                <span class="inline-flex items-center gap-1.5 text-xs" :class="statusText(r.status)">
                  <span class="size-1.5 rounded-full" :class="statusDot(r.status)"></span>
                  {{ statusLabel(r.status) }}
                </span>
              </td>
              <td class="px-3 py-3 text-xs text-[var(--text-tertiary)] font-mono tabular-nums">
                {{ formatTime(r.created_at) }}
                <div v-if="r.decided_at" class="text-[10px] text-[var(--text-disable)]">→ {{ formatTime(r.decided_at) }}</div>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Pagination -->
        <div class="flex items-center justify-between mt-4 pt-3 border-t border-[var(--border-light)]">
          <div class="text-xs text-[var(--text-tertiary)] font-mono">
            第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条
          </div>
          <div class="flex items-center gap-2">
            <button @click="goPage(1)" :disabled="page <= 1 || loading" class="px-2.5 py-1 rounded text-xs border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-card)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              首页
            </button>
            <button @click="goPage(page - 1)" :disabled="page <= 1 || loading" class="px-2.5 py-1 rounded text-xs border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-card)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              上一页
            </button>
            <button @click="goPage(page + 1)" :disabled="page >= totalPages || loading" class="px-2.5 py-1 rounded text-xs border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-card)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              下一页
            </button>
            <button @click="goPage(totalPages)" :disabled="page >= totalPages || loading" class="px-2.5 py-1 rounded text-xs border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-card)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              末页
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Detail Modal -->
    <Dialog :open="selectedRecord !== null" @update:open="(v: boolean) => { if (!v) selectedRecord = null }">
      <DialogContent class="w-[760px] max-w-[95vw]">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2 text-base">
            <Terminal :size="15" class="text-[var(--text-secondary)]" />
            <span class="font-mono">{{ selectedRecord?.tool_name || '-' }}</span>
            <span v-if="selectedRecord?.subagent_type" class="text-xs font-normal text-[var(--text-tertiary)]">/ {{ selectedRecord.subagent_type }}</span>
          </DialogTitle>
        </DialogHeader>
        <div v-if="selectedRecord" class="px-6 pb-6 space-y-4 max-h-[72vh] overflow-y-auto">
          <div class="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
            <div><span class="text-[var(--text-tertiary)]">父Agent</span><span class="ml-2 text-[var(--text-secondary)]">{{ selectedRecord.parent_agent || '-' }}</span></div>
            <div><span class="text-[var(--text-tertiary)]">子Agent</span><span class="ml-2 text-[var(--text-secondary)] font-mono">{{ selectedRecord.subagent_type || '-' }}</span></div>
            <div><span class="text-[var(--text-tertiary)]">发起人</span><span class="ml-2 text-[var(--text-secondary)]">{{ selectedRecord.initiator_username || selectedRecord.initiator_user_id || '-' }}</span></div>
            <div><span class="text-[var(--text-tertiary)]">审批人</span><span class="ml-2 text-[var(--text-secondary)]">{{ selectedRecord.approver_username || selectedRecord.approver_user_id || '-' }}</span></div>
            <div><span class="text-[var(--text-tertiary)]">决策</span><span class="ml-2" :class="selectedRecord.decision ? decisionText(selectedRecord.decision) : 'text-[var(--text-disable)]'">{{ selectedRecord.decision ? decisionLabel(selectedRecord.decision) : '-' }}</span></div>
            <div><span class="text-[var(--text-tertiary)]">状态</span><span class="ml-2" :class="statusText(selectedRecord.status)">{{ statusLabel(selectedRecord.status) }}</span></div>
            <div><span class="text-[var(--text-tertiary)]">会话</span>
              <button v-if="selectedRecord.session_id" @click="openSession(selectedRecord.session_id)" class="ml-2 font-mono text-[#e85d2a] hover:underline">{{ selectedRecord.session_id }}</button>
              <span v-else class="ml-2 text-[var(--text-disable)]">-</span>
            </div>
            <div><span class="text-[var(--text-tertiary)]">时间</span><span class="ml-2 text-[var(--text-secondary)] font-mono">{{ formatTime(selectedRecord.created_at) }}{{ selectedRecord.decided_at ? ' -> ' + formatTime(selectedRecord.decided_at) : '' }}</span></div>
          </div>
          <div v-if="selectedRecord.original_request_message">
            <div class="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] mb-1">发起消息</div>
            <div class="text-xs text-[var(--text-secondary)] bg-[var(--background-gray-main)] rounded px-3 py-2">{{ selectedRecord.original_request_message }}</div>
          </div>
          <div>
            <div class="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] mb-1">入参 (tool_args)</div>
            <pre class="text-xs text-[var(--text-secondary)] whitespace-pre-wrap break-all bg-[var(--background-gray-main)] rounded px-3 py-2 max-h-[35vh] overflow-y-auto">{{ formatArgs(selectedRecord.tool_args) }}</pre>
          </div>
          <div>
            <div class="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] mb-1">出参 (tool_result)</div>
            <pre v-if="selectedRecord.tool_result" class="text-xs text-[var(--text-secondary)] whitespace-pre-wrap break-all bg-[var(--background-gray-main)] rounded px-3 py-2 max-h-[35vh] overflow-y-auto">{{ selectedRecord.tool_result }}</pre>
            <div v-else class="text-xs text-[var(--text-disable)] bg-[var(--background-gray-main)] rounded px-3 py-2">{{ selectedRecord.status === 'pending' ? '待审批,工具尚未执行' : '暂无出参' }}</div>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- Toast -->
    <Teleport to="body">
      <div v-if="toast" class="fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-md shadow-lg text-xs font-medium border-l-2" :class="toast.type === 'error' ? 'bg-[var(--background-card)] text-[var(--function-error)] border-[var(--function-error)]' : 'bg-[var(--background-card)] text-[var(--function-success)] border-[var(--function-success)]'">
        {{ toast.text }}
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { RefreshCw, ShieldCheck, Terminal } from 'lucide-vue-next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { listApprovals, type ApprovalRecord, type ApprovalStatus, type ApprovalDecision } from '@/api/approvals';
import { shareSession } from '@/api/agent';

const router = useRouter();

const items = ref<ApprovalRecord[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const filterStatus = ref<'' | ApprovalStatus>('');

const toast = ref<{ type: 'success' | 'error'; text: string } | null>(null);
const selectedRecord = ref<ApprovalRecord | null>(null);

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)));

async function refresh() {
  loading.value = true;
  try {
    const res = await listApprovals({
      page: page.value,
      page_size: pageSize.value,
      status: filterStatus.value || undefined,
    });
    items.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    showToast('error', e?.response?.data?.detail ?? e?.message ?? '加载失败');
  } finally {
    loading.value = false;
  }
}

function goPage(n: number) {
  if (n < 1 || n > totalPages.value || n === page.value) return;
  page.value = n;
  refresh();
}

function openDetail(r: ApprovalRecord) {
  selectedRecord.value = r;
}

function formatArgs(args: Record<string, unknown> | null | undefined): string {
  if (!args || !Object.keys(args).length) return '{}';
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

async function openSession(sessionId: string) {
  if (!sessionId) return;
  try {
    await shareSession(sessionId);
    // 在新窗口打开分享页,而非当前窗口跳转
    const href = router.resolve(`/share/${sessionId}`).href;
    window.open(href, '_blank');
  } catch (e: any) {
    showToast('error', e?.response?.data?.detail ?? e?.message ?? '打开分享页失败');
  }
}

function decisionLabel(d: ApprovalDecision): string {
  return { approve: '通过', reject: '拒绝', edit: '修改', respond: '回复' }[d];
}
function decisionDot(d: ApprovalDecision): string {
  return {
    approve: 'bg-[var(--function-success)]',
    reject: 'bg-[var(--function-error)]',
    edit: 'bg-[var(--function-warning)]',
    respond: 'bg-[#3a6b8c]',
  }[d];
}
function decisionText(d: ApprovalDecision): string {
  return {
    approve: 'text-[var(--function-success)]',
    reject: 'text-[var(--function-error)]',
    edit: 'text-[var(--function-warning)]',
    respond: 'text-[#3a6b8c]',
  }[d];
}

function statusLabel(s: ApprovalStatus): string {
  return { pending: '待审批', decided: '已决策', auto_approved: '自动通过' }[s];
}
function statusDot(s: ApprovalStatus): string {
  return {
    pending: 'bg-[var(--function-warning)]',
    decided: 'bg-[var(--function-success)]',
    auto_approved: 'bg-[#3a6b8c]',
  }[s];
}
function statusText(s: ApprovalStatus): string {
  return {
    pending: 'text-[var(--function-warning)]',
    decided: 'text-[var(--function-success)]',
    auto_approved: 'text-[#3a6b8c]',
  }[s];
}

function formatTime(ts: number): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

function showToast(type: 'success' | 'error', text: string) {
  toast.value = { type, text };
  setTimeout(() => (toast.value = null), 3000);
}

watch(filterStatus, () => {
  page.value = 1;
  refresh();
});

onMounted(refresh);
</script>
