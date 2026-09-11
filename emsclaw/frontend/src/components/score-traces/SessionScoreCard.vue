<template>
  <div
    class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden transition-all"
    :class="session.score_count === 0 ? 'opacity-60' : 'hover:border-[#3a6b8c]/40'"
  >
    <!-- ── 折叠行：双行布局 ── -->
    <button @click="toggle"
      class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--background-gray-main)]/50 transition-colors text-left">
      <!-- 展开箭头 -->
      <ChevronRight :size="14" class="text-[var(--text-tertiary)] flex-shrink-0 transition-transform"
        :class="{ 'rotate-90': open }" />

      <!-- 左：主信息块（双行） -->
      <div class="flex-1 min-w-0 flex flex-col gap-1">
        <!-- 上排：query 主语 -->
        <div class="flex items-center gap-2 min-w-0">
          <span class="text-[15px] font-medium text-[var(--text-primary)] truncate leading-snug">
            {{ session.query || '(无查询)' }}
          </span>
          <span v-if="session.score_count === 0"
            class="text-[10px] text-[var(--text-tertiary)] px-1.5 py-0.5 rounded bg-[var(--background-gray-main)] flex-shrink-0">
            未评分
          </span>
        </div>
        <!-- 下排：元信息 -->
        <div class="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
          <span v-if="session.version"
            class="px-1.5 py-0.5 rounded bg-[var(--background-gray-main)] text-[var(--text-secondary)] font-mono">
            v{{ session.version }}
          </span>
          <span v-if="session.mode" class="text-[var(--text-secondary)]">{{ session.mode }}</span>
          <span v-if="session.trace_count > 1">{{ session.trace_count }} 轮调用</span>
          <span>{{ formatTime(session.last_at || session.started_at) }}</span>
        </div>
      </div>

      <!-- 右：评分药丸 + 均值 + 进入按钮 -->
      <div class="flex items-center gap-2.5 flex-shrink-0">
        <!-- 评分药丸 -->
        <ScoreBadgePills v-if="sessionPills.length" :pills="sessionPills" />

        <!-- 均值 -->
        <div class="flex flex-col items-end gap-0.5 min-w-[56px]">
          <span v-if="session.avg_score !== null"
            class="text-xl font-bold tabular-nums leading-none"
            :class="scoreValueClassFromNum(session.avg_score)">
            {{ session.avg_score.toFixed(2) }}
          </span>
          <span v-else class="text-xs text-[var(--text-tertiary)] italic">—</span>
          <span class="text-[10px] text-[var(--text-tertiary)] font-mono">{{ session.score_count }} 条评分</span>
        </div>

        <!-- 进入会话 -->
        <button
          @click.stop="$emit('openChat', session)"
          :disabled="linking"
          title="进入对应对话"
          class="h-7 px-2 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] hover:border-[#3a6b8c]/50 transition-colors text-xs flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed">
          <MessageSquareText :size="12" />
          <span v-if="linking" class="font-mono">…</span>
        </button>
      </div>
    </button>

    <!-- ── 展开区 ── -->
    <div v-if="open" class="border-t border-[var(--border-light)] bg-[var(--background-gray-main)]">
      <div class="px-4 py-4 space-y-4">
        <!-- 会话摘要：首轮 query + 末轮 output -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div>
            <div class="text-[11px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wide">用户问</div>
            <div class="text-xs text-[var(--text-primary)] bg-[var(--background-card)] border border-[var(--border-light)] rounded-md p-3 leading-relaxed whitespace-pre-wrap max-h-[160px] overflow-y-auto">
              {{ session.query || '(空)' }}
            </div>
          </div>
          <div>
            <div class="text-[11px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wide">Agent 答</div>
            <div class="text-xs text-[var(--text-primary)] bg-[var(--background-card)] border border-[var(--border-light)] rounded-md p-3 leading-relaxed whitespace-pre-wrap max-h-[300px] overflow-y-auto">
              {{ session.output || '(空)' }}
            </div>
          </div>
        </div>

        <!-- session ID -->
        <div class="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)] font-mono">
          <span>session: {{ session.session_id }}</span>
        </div>

        <!-- 各 trace -->
        <div class="space-y-5">
          <div v-for="(t, ti) in session.traces" :key="t.trace_id"
            class="border-l-2 pl-3"
            :class="t.scores.length ? 'border-[#3a6b8c]/40' : 'border-[var(--border-light)]'">
            <!-- Trace 头 -->
            <div class="flex items-center gap-2 mb-3 flex-wrap text-[11px] text-[var(--text-tertiary)]">
              <span class="font-mono">#{{ ti + 1 }}</span>
              <span v-if="t.avg_score !== null"
                class="font-semibold tabular-nums ml-1" :class="scoreValueClassFromNum(t.avg_score)">
                均值 {{ t.avg_score.toFixed(2) }}
              </span>
              <span class="font-mono ml-auto">{{ formatTime(t.started_at) }}</span>
              <span v-if="t.trace_id" class="font-mono">trace: {{ t.trace_id.slice(0, 10) }}…</span>
            </div>

            <!-- Trace 详情面板 -->
            <TraceDetailPanel :trace="t" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { ChevronRight, MessageSquareText } from 'lucide-vue-next';
import { scoreValueClassFromNum } from '@/utils/scoreLabels';
import ScoreBadgePills from './ScoreBadgePills.vue';
import TraceDetailPanel from './TraceDetailPanel.vue';
import type { LangfuseScoreSession } from '@/types/langfuse';
import type { ScorePill } from './ScoreBadgePills.vue';

const props = defineProps<{
  session: LangfuseScoreSession;
  linking?: boolean;
}>();

defineEmits<{
  openChat: [session: LangfuseScoreSession];
}>();

const open = ref(false);

function toggle() {
  open.value = !open.value;
}

// 计算会话顶部评分药丸（每个维度的最新评分，最多 4 个）
const sessionPills = computed<ScorePill[]>(() => {
  const latest: Record<string, { value: number; ts: string }> = {};
  for (const t of props.session.traces) {
    for (const sc of t.scores) {
      if (sc.data_type !== 'NUMERIC' || typeof sc.value !== 'number') continue;
      const key = sc.name;
      if (!latest[key] || (sc.timestamp || '') > (latest[key].ts || '')) {
        latest[key] = { value: sc.value as number, ts: sc.timestamp || '' };
      }
    }
  }
  return Object.entries(latest)
    .sort((a, b) => b[1].ts.localeCompare(a[1].ts))
    .slice(0, 4)
    .map(([name, { value }]) => ({ name, value }));
});

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return iso;
  }
}
</script>
