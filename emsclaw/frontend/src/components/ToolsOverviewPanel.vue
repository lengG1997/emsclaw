<template>
  <div class="flex flex-col gap-4">
    <!-- 未启用 -->
    <div v-if="!status?.enabled" class="flex flex-col items-center justify-center py-16 text-center gap-3">
      <AlertTriangle :size="28" class="text-[var(--function-warning)]" />
      <div class="text-sm text-[var(--text-secondary)]">Langfuse 可观测性未启用</div>
    </div>

    <template v-else>
      <!-- 加载中且无数据 -->
      <div v-if="loading && !data" class="flex flex-col items-center justify-center py-16 text-[var(--text-tertiary)] gap-3">
        <RefreshCw :size="24" class="animate-spin text-[var(--text-disable)]" />
        <span class="text-xs font-mono">SYNC…</span>
      </div>

      <!-- KPI -->
      <div v-if="data" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="kpi-card">
          <div class="text-[11px] text-[var(--text-tertiary)]">工具调用数</div>
          <div class="text-xl font-semibold text-[var(--text-primary)] font-mono">{{ data.kpi?.tool_call_count ?? 0 }}</div>
        </div>
        <div class="kpi-card">
          <div class="text-[11px] text-[var(--text-tertiary)]">平均耗时</div>
          <div class="text-xl font-semibold text-[var(--text-primary)] font-mono">{{ formatMs(data.kpi?.avg_latency_ms) }}</div>
        </div>
        <div class="kpi-card">
          <div class="text-[11px] text-[var(--text-tertiary)]">P95 耗时</div>
          <div class="text-xl font-semibold text-[var(--text-primary)] font-mono">{{ formatMs(data.kpi?.p95_latency_ms) }}</div>
        </div>
        <div class="kpi-card">
          <div class="text-[11px] text-[var(--text-tertiary)]">错误率</div>
          <div class="text-xl font-semibold font-mono" :class="errorColor(data.kpi?.error_rate)">{{ formatRate(data.kpi?.error_rate) }}</div>
        </div>
      </div>

      <!-- 不支持 -->
      <div v-if="data?.supported === false" class="text-xs text-[var(--text-tertiary)] py-8 text-center">
        Langfuse 未提供工具级 observation 数据
      </div>

      <!-- by_tool 表 -->
      <div v-if="data?.by_tool?.length" class="rounded-lg border border-[var(--border-main)] overflow-hidden">
        <table class="w-full text-xs">
          <thead class="bg-[var(--background-card)] text-[var(--text-tertiary)]">
            <tr>
              <th class="text-left px-3 py-2 font-medium">工具</th>
              <th class="text-right px-3 py-2 font-medium">调用数</th>
              <th class="text-right px-3 py-2 font-medium">平均耗时</th>
              <th class="text-right px-3 py-2 font-medium">P95</th>
              <th class="text-right px-3 py-2 font-medium">错误率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in data.by_tool" :key="r.tool" class="border-t border-[var(--border-main)]">
              <td class="px-3 py-2 font-mono text-[var(--text-primary)]">{{ r.tool }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ r.calls }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ formatMs(r.avg_latency_ms) }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ formatMs(r.p95_latency_ms) }}</td>
              <td class="px-3 py-2 text-right font-mono" :class="errorColor(r.error_rate)">{{ formatRate(r.error_rate) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { AlertTriangle, RefreshCw } from 'lucide-vue-next';
import { getLangfuseToolsOverview } from '../api/langfuse';
import { showErrorToast } from '@/utils/toast';
import type { LangfuseToolsOverview, LangfuseStatus } from '../types/langfuse';

const props = defineProps<{ window: string; status: LangfuseStatus | null }>();
const data = ref<LangfuseToolsOverview | null>(null);
const loading = ref(false);

const formatMs = (ms?: number) => (ms == null ? '-' : ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`);
const formatRate = (r?: number) => (r == null ? '-' : `${(r * 100).toFixed(1)}%`);
const errorColor = (r?: number) => (!r ? '' : r > 0.05 ? 'text-[var(--function-error)]' : 'text-[var(--function-success)]');

async function load() {
  if (!props.status?.enabled) return;
  loading.value = true;
  try {
    data.value = await getLangfuseToolsOverview(props.window);
  } catch (e: any) {
    showErrorToast(e?.message ?? '加载工具数据失败');
  } finally {
    loading.value = false;
  }
}
watch(() => [props.window, props.status?.enabled], load, { immediate: true });
</script>

<style scoped>
.kpi-card {
  @apply rounded-lg border border-[var(--border-main)] bg-[var(--background-card)] px-3 py-2;
}
</style>
