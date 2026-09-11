<template>
  <div class="flex flex-col h-full w-full overflow-hidden">
    <!-- Masthead -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1800px] mx-auto flex items-end justify-between gap-4 flex-wrap">
        <div class="flex items-end gap-3">
          <div class="flex items-center gap-2.5">
            <span class="size-2 rounded-full" :class="loading ? 'bg-[var(--function-warning)] animate-pulse' : 'bg-[var(--function-success)]'"></span>
            <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">模型总览</h1>
            <MetricInfo v-bind="EXPLAINERS.modelOverviewIntro" />
          </div>
          <div v-if="data" class="text-xs text-[var(--text-tertiary)] pb-0.5 font-mono">
            {{ windowLabel }} · {{ isFiltered ? modelSel : `${data.by_model.length} 个模型` }} · {{ data.kpi?.total_calls ?? 0 }} 次调用
          </div>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <!-- 模型筛选 -->
          <div class="flex items-center gap-1">
            <span class="text-[11px] text-[var(--text-tertiary)]">模型</span>
            <MetricInfo v-bind="EXPLAINERS.modelFilter" />
            <select v-model="modelSel" :disabled="loading"
              class="h-8 rounded-md border border-[var(--border-main)] bg-[var(--background-card)] text-xs text-[var(--text-primary)] px-2 max-w-[180px] disabled:opacity-40 focus:outline-none focus:border-[#3a6b8c]">
              <option value="">全部模型</option>
              <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <!-- 时间窗口 -->
          <div class="flex items-center rounded-md border border-[var(--border-main)] overflow-hidden">
            <button v-for="w in WINDOWS" :key="w[0]" @click="windowSel = w[0]"
              class="px-3 h-8 text-xs transition-colors"
              :class="windowSel === w[0]
                ? 'bg-[#3a6b8c] text-white'
                : 'text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)]'">
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
          模型总览页需要 Langfuse 提供数据。请在启动 backend 时叠加 Langfuse 配置
          (<span class="font-mono">LANGFUSE_ENABLED=true</span> 及 public/secret key、base_url),然后重启。
        </div>
      </div>

      <!-- 加载中且无数据 -->
      <div v-else-if="loading && !hasData" class="flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] gap-3">
        <RefreshCw :size="24" class="animate-spin text-[var(--text-disable)]" />
        <span class="text-xs font-mono">SYNC…</span>
      </div>

      <!-- 无数据(已启用但该窗口/模型无调用) -->
      <div v-else-if="!hasData" class="flex flex-col items-center justify-center h-full text-center gap-2 px-6">
        <BarChart3 :size="28" class="text-[var(--text-disable)]" />
        <div class="text-sm text-[var(--text-secondary)]">该筛选条件下暂无大模型调用记录</div>
        <div class="text-xs text-[var(--text-tertiary)]">换个时间窗口或模型试试,或先和 Agent 聊几句产生数据。</div>
      </div>

      <!-- 数据主体 -->
      <div v-else-if="data" class="max-w-[1800px] mx-auto p-6 pt-4 space-y-4">
        <!-- KPI -->
        <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
          <div v-for="c in kpiCards" :key="c.label"
            class="rounded-lg border bg-[var(--background-card)] p-3 flex flex-col gap-1 relative"
            :class="c.tone === 'danger' ? 'border-[var(--function-error)]/40' : 'border-[var(--border-light)]'">
            <div class="flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
              <span>{{ c.label }}</span>
              <MetricInfo v-bind="c.hint" />
            </div>
            <div class="mt-0.5 flex items-baseline gap-1">
              <span class="text-xl font-semibold tabular-nums text-[var(--text-primary)] leading-none">{{ c.value }}</span>
              <span v-if="c.unit" class="text-[11px] text-[var(--text-tertiary)]">{{ c.unit }}</span>
            </div>
            <div v-if="c.sub" class="text-[10px] text-[var(--text-tertiary)] font-mono">{{ c.sub }}</div>
          </div>
        </div>

        <!-- 模型维度(仅「全部模型」时) -->
        <template v-if="!isFiltered">
          <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <EChartCard :option="modelShareOption" :has-data="byModelHasData" :height="240"
              empty-text="暂无模型数据">
              <template #title>模型调用量占比<MetricInfo v-bind="EXPLAINERS.modelCallShare" /></template>
            </EChartCard>
            <EChartCard :option="modelTokenCostOption" :has-data="byModelHasData" :height="240"
              empty-text="暂无模型数据">
              <template #title>模型 Token &amp; 成本<MetricInfo v-bind="EXPLAINERS.modelTokenCost" /></template>
            </EChartCard>
            <EChartCard :option="modelLatencyOption" :has-data="byModelHasData" :height="240"
              empty-text="暂无模型数据">
              <template #title>模型延迟对比<MetricInfo v-bind="EXPLAINERS.modelLatency" /></template>
              <template #meta>柱: P50 / P95 延迟 (ms)</template>
            </EChartCard>
          </div>

          <!-- 模型明细表 -->
          <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden">
            <div class="flex items-center gap-2 px-4 py-3 border-b border-[var(--border-light)]">
              <span class="text-sm font-semibold text-[var(--text-primary)]">模型明细</span>
              <MetricInfo v-bind="EXPLAINERS.modelTable" />
            </div>
            <div v-if="data.by_model.length" class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead>
                  <tr class="text-[var(--text-tertiary)] text-left border-b border-[var(--border-light)]">
                    <th class="py-2 px-4 font-medium">模型</th>
                    <th class="py-2 px-4 font-medium text-right">调用</th>
                    <th class="py-2 px-4 font-medium text-right">Token</th>
                    <th class="py-2 px-4 font-medium text-right">成本($)</th>
                    <th class="py-2 px-4 font-medium text-right">P50 / P95</th>
                    <th class="py-2 px-4 font-medium text-right">吞吐(tok/s)</th>
                    <th class="py-2 px-4 font-medium text-right">错误率</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in data.by_model" :key="m.model" class="border-b border-[var(--border-light)]/50">
                    <td class="py-2 px-4 font-mono text-[var(--text-primary)]">{{ m.model }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ m.calls }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ fmtNum(m.tokens) }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ m.cost.toFixed(4) }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ fmtMs(m.p50_latency_ms) }} / {{ fmtMs(m.p95_latency_ms) }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ m.tokens_per_sec }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right" :class="m.error_rate > 0 ? 'text-[var(--function-error)]' : 'text-[var(--text-tertiary)]'">{{ (m.error_rate * 100).toFixed(2) }}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- 趋势 -->
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <EChartCard :option="trendCallsOption" :has-data="trendHasData" :height="200"
            empty-text="暂无趋势数据">
            <template #title>调用量趋势<MetricInfo v-bind="EXPLAINERS.trendCalls" /></template>
          </EChartCard>
          <EChartCard :option="trendTokensCostOption" :has-data="trendHasData" :height="200"
            empty-text="暂无趋势数据">
            <template #title>Token 与成本趋势<MetricInfo v-bind="EXPLAINERS.trendTokens" /></template>
          </EChartCard>
          <EChartCard :option="trendLatencyOption" :has-data="trendHasData" :height="200"
            empty-text="暂无趋势数据">
            <template #title>延迟趋势<MetricInfo v-bind="EXPLAINERS.trendLatency" /></template>
            <template #meta>P50 延迟 (ms)</template>
          </EChartCard>
          <EChartCard :option="trendErrorOption" :has-data="trendHasData" :height="200"
            empty-text="暂无趋势数据">
            <template #title>错误率趋势<MetricInfo v-bind="EXPLAINERS.trendError" /></template>
            <template #meta>每日出错比例 (%)</template>
          </EChartCard>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { RefreshCw, AlertTriangle, BarChart3 } from 'lucide-vue-next';
import type { EChartsOption } from 'echarts';
import EChartCard from '@/components/EChartCard.vue';
import MetricInfo from '@/components/MetricInfo.vue';
import { EXPLAINERS } from '@/constants/explainers';
import { getLangfuseStatus, getLangfuseOverview } from '@/api/langfuse';
import type { LangfuseOverview, LangfuseStatus } from '@/types/langfuse';
import { showErrorToast } from '@/utils/toast';

const AXIS = '#6b7280';
const SPLIT = 'rgba(107,114,128,0.15)';
const PALETTE = ['#3a6b8c', '#e85d2a', '#e8b62a', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f43f5e'];
const WINDOWS: [string, string][] = [['today', '今日'], ['7d', '7天'], ['30d', '30天']];

const loading = ref(false);
const status = ref<LangfuseStatus | null>(null);
const data = ref<LangfuseOverview | null>(null);
const windowSel = ref('7d');
const modelSel = ref(''); // '' = 全部模型
const modelOptions = ref<string[]>([]); // 下拉候选(并集累积)

const isFiltered = computed(() => !!modelSel.value);
const windowLabel = computed(() => WINDOWS.find((w) => w[0] === windowSel.value)?.[1] ?? windowSel.value);
const disabledState = computed(() => status.value && (!status.value.enabled || !status.value.configured));
const hasData = computed(() => !!data.value?.kpi && (data.value.kpi.total_calls > 0 || data.value.by_model.length > 0));

// ── 格式化 ──
function fmtNum(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}
function fmtMs(ms: number): string {
  if (!ms) return '-';
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
  return Math.round(ms) + 'ms';
}

// ── KPI 卡片 ──
const kpiCards = computed(() => {
  const k = data.value?.kpi;
  if (!k) return [];
  return [
    { label: '总调用', value: fmtNum(k.total_calls), unit: '次', hint: EXPLAINERS.totalCalls, tone: 'idle', sub: '' },
    { label: '会话数', value: fmtNum(k.session_count), unit: '个', hint: EXPLAINERS.sessionCount, tone: 'idle', sub: '' },
    { label: '总 Token', value: fmtNum(k.total_tokens), unit: '', hint: EXPLAINERS.totalTokens, tone: 'idle', sub: `入 ${fmtNum(k.input_tokens)} / 出 ${fmtNum(k.output_tokens)}` },
    { label: '总成本', value: '$' + k.total_cost.toFixed(2), unit: '', hint: EXPLAINERS.totalCost, tone: 'idle', sub: '' },
    { label: 'P50 延迟', value: fmtMs(k.p50_latency_ms), unit: '', hint: EXPLAINERS.p50Latency, tone: 'idle', sub: '' },
    { label: 'P95 延迟', value: fmtMs(k.p95_latency_ms), unit: '', hint: EXPLAINERS.p95Latency, tone: 'idle', sub: '' },
    { label: '平均首字', value: fmtMs(k.avg_ttft_ms), unit: '', hint: EXPLAINERS.avgTtft, tone: 'idle', sub: '' },
    { label: '错误率', value: (k.error_rate * 100).toFixed(2) + '%', unit: '', hint: EXPLAINERS.errorRate, tone: k.error_rate > 0.05 ? 'danger' : 'idle', sub: '' },
  ];
});

const byModelHasData = computed(() => (data.value?.by_model.length ?? 0) > 0);
const trendHasData = computed(() => (data.value?.daily.some((d) => d.calls > 0) ?? false));

// ── 图表 option ──
const modelShareOption = computed<EChartsOption>(() => {
  const rows = data.value?.by_model ?? [];
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 次 ({d}%)' },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: AXIS, fontSize: 10 } },
    color: PALETTE,
    series: [{
      type: 'pie', radius: ['38%', '68%'], center: ['50%', '44%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: 'var(--background-card)', borderWidth: 2 },
      label: { show: false },
      labelLine: { show: false },
      data: rows.map((m) => ({ name: m.model, value: m.calls })),
    }],
  };
});

const modelTokenCostOption = computed<EChartsOption>(() => {
  const rows = data.value?.by_model ?? [];
  const names = rows.map((m) => m.model);
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Token', '成本($)'], textStyle: { color: AXIS, fontSize: 10 }, top: 0 },
    color: ['#3a6b8c', '#e85d2a'],
    grid: { left: 8, right: 8, bottom: 8, top: 30, containLabel: true },
    xAxis: {
      type: 'category', data: names,
      axisLabel: { color: AXIS, fontSize: 10, interval: 0, rotate: names.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: SPLIT } },
    },
    yAxis: [
      { type: 'value', name: 'Token', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
      { type: 'value', name: '$', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { show: false } },
    ],
    series: [
      { name: 'Token', type: 'bar', data: rows.map((m) => m.tokens), itemStyle: { color: '#3a6b8c' } },
      { name: '成本($)', type: 'bar', yAxisIndex: 1, data: rows.map((m) => Number(m.cost.toFixed(4))), itemStyle: { color: '#e85d2a' } },
    ],
  };
});

const modelLatencyOption = computed<EChartsOption>(() => {
  const rows = data.value?.by_model ?? [];
  const names = rows.map((m) => m.model);
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMs(Number(v)) },
    legend: { data: ['P50', 'P95'], textStyle: { color: AXIS, fontSize: 10 }, top: 0 },
    color: ['#3a6b8c', '#e85d2a'],
    grid: { left: 8, right: 8, bottom: 8, top: 30, containLabel: true },
    xAxis: {
      type: 'category', data: names,
      axisLabel: { color: AXIS, fontSize: 10, interval: 0, rotate: names.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: SPLIT } },
    },
    yAxis: { type: 'value', axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [
      { name: 'P50', type: 'bar', data: rows.map((m) => Math.round(m.p50_latency_ms)), itemStyle: { color: '#3a6b8c' } },
      { name: 'P95', type: 'bar', data: rows.map((m) => Math.round(m.p95_latency_ms)), itemStyle: { color: '#e85d2a' } },
    ],
  };
});

function shortDate(d: string): string {
  return d.length >= 10 ? d.slice(5) : d; // MM-DD
}

const trendCallsOption = computed<EChartsOption>(() => {
  const rows = data.value?.daily ?? [];
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 16, bottom: 8, top: 16, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: rows.map((d) => shortDate(d.date)), axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { lineStyle: { color: SPLIT } } },
    yAxis: { type: 'value', axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [{ type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: rows.map((d) => d.calls), itemStyle: { color: '#3a6b8c' }, areaStyle: { opacity: 0.12 } }],
  };
});

const trendTokensCostOption = computed<EChartsOption>(() => {
  const rows = data.value?.daily ?? [];
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Token', '成本($)'], textStyle: { color: AXIS, fontSize: 10 }, top: 0 },
    color: ['#3a6b8c', '#e85d2a'],
    grid: { left: 8, right: 8, bottom: 8, top: 30, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: rows.map((d) => shortDate(d.date)), axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { lineStyle: { color: SPLIT } } },
    yAxis: [
      { type: 'value', name: 'Token', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
      { type: 'value', name: '$', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { show: false } },
    ],
    series: [
      { name: 'Token', type: 'line', smooth: true, symbol: 'none', data: rows.map((d) => d.tokens), itemStyle: { color: '#3a6b8c' } },
      { name: '成本($)', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none', data: rows.map((d) => Number(d.cost.toFixed(4))), itemStyle: { color: '#e85d2a' } },
    ],
  };
});

const trendLatencyOption = computed<EChartsOption>(() => {
  const rows = data.value?.daily ?? [];
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v) => fmtMs(Number(v)) },
    grid: { left: 8, right: 16, bottom: 8, top: 16, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: rows.map((d) => shortDate(d.date)), axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { lineStyle: { color: SPLIT } } },
    yAxis: { type: 'value', axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [{ type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: rows.map((d) => Math.round(d.p50_latency_ms)), itemStyle: { color: '#10b981' }, areaStyle: { opacity: 0.1 } }],
  };
});

const trendErrorOption = computed<EChartsOption>(() => {
  const rows = data.value?.daily ?? [];
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v) => Number(v).toFixed(2) + '%' },
    grid: { left: 8, right: 16, bottom: 8, top: 16, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: rows.map((d) => shortDate(d.date)), axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { lineStyle: { color: SPLIT } } },
    yAxis: { type: 'value', axisLabel: { color: AXIS, fontSize: 10, formatter: '{value}%' }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [{ type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: rows.map((d) => Number((d.error_rate * 100).toFixed(2))), itemStyle: { color: '#f43f5e' }, areaStyle: { opacity: 0.1 } }],
  };
});

// ── 取数 ──
async function refresh() {
  loading.value = true;
  try {
    data.value = await getLangfuseOverview(windowSel.value, modelSel.value || null);
    // 累积模型下拉候选(只在「全部模型」时由 by_model 补充)
    if (!modelSel.value && data.value.by_model.length) {
      const set = new Set(modelOptions.value);
      data.value.by_model.forEach((m) => set.add(m.model));
      modelOptions.value = [...set].sort();
    }
    if (data.value.error) {
      showErrorToast(data.value.error);
    }
  } catch (e: any) {
    showErrorToast(e?.message ?? '加载模型总览失败');
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

watch(windowSel, () => refresh());
watch(modelSel, () => refresh());

onMounted(async () => {
  await loadStatus();
  if (!disabledState.value) await refresh();
});
</script>
