<template>
  <div class="flex flex-col h-full w-full overflow-hidden">
    <!-- Masthead -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1800px] mx-auto flex items-end justify-between gap-4 flex-wrap">
        <div class="flex items-end gap-3">
          <div class="flex items-center gap-2.5">
            <span class="size-2 rounded-full" :class="loading ? 'bg-[var(--function-warning)] animate-pulse' : 'bg-[var(--function-success)]'"></span>
            <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">质量评分</h1>
            <MetricInfo v-bind="EXPLAINERS.scoreOverviewIntro" />
            <!-- B3: 评分 / 工具调用 tab -->
            <div class="flex items-center gap-1 ml-2 rounded-lg border border-[var(--border-main)] overflow-hidden">
              <button @click="activeTab = 'scores'"
                class="px-3 h-7 text-xs transition-colors"
                :class="activeTab === 'scores' ? 'bg-[#3a6b8c] text-white' : 'text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)]'">质量评分</button>
              <button @click="activeTab = 'tools'"
                class="px-3 h-7 text-xs transition-colors"
                :class="activeTab === 'tools' ? 'bg-[#3a6b8c] text-white' : 'text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)]'">工具调用</button>
            </div>
          </div>
          <div v-if="data" class="text-xs text-[var(--text-tertiary)] pb-0.5 font-mono">
            {{ windowLabel }} · {{ isFiltered ? nameSel : `${data.kpi?.score_name_count ?? 0} 个维度` }} · {{ data.kpi?.score_count ?? 0 }} 次评分
          </div>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <!-- 评分维度筛选 -->
          <div class="flex items-center gap-1">
            <span class="text-[11px] text-[var(--text-tertiary)]">维度</span>
            <MetricInfo v-bind="EXPLAINERS.scoreNameFilter" />
            <select v-model="nameSel" :disabled="loading"
              class="h-8 rounded-md border border-[var(--border-main)] bg-[var(--background-card)] text-xs text-[var(--text-primary)] px-2 max-w-[180px] disabled:opacity-40 focus:outline-none focus:border-[#3a6b8c]">
              <option value="">全部维度</option>
              <option v-for="n in nameOptions" :key="n" :value="n">{{ dimensionLabel(n) }}</option>
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
      <!-- 评分 tab -->
      <div v-if="activeTab === 'scores'">
      <!-- 未启用 -->
      <div v-if="disabledState" class="flex flex-col items-center justify-center h-full text-center gap-3 px-6">
        <AlertTriangle :size="28" class="text-[var(--function-warning)]" />
        <div class="text-sm text-[var(--text-secondary)]">Langfuse 可观测性未启用</div>
        <div class="text-xs text-[var(--text-tertiary)] max-w-md leading-relaxed">
          质量评分页需要 Langfuse 提供数据。请在启动 backend 时叠加 Langfuse 配置
          (<span class="font-mono">LANGFUSE_ENABLED=true</span> 及 public/secret key、base_url),然后重启。
        </div>
      </div>

      <!-- 加载中且无数据 -->
      <div v-else-if="loading && !hasData" class="flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] gap-3">
        <RefreshCw :size="24" class="animate-spin text-[var(--text-disable)]" />
        <span class="text-xs font-mono">SYNC…</span>
      </div>

      <!-- 无评分数据(引导配 evaluator) -->
      <div v-else-if="!hasData" class="flex flex-col items-center justify-center h-full text-center gap-3 px-6">
        <Award :size="28" class="text-[var(--text-disable)]" />
        <div class="text-sm text-[var(--text-secondary)]">还没有评分数据</div>
        <div class="text-xs text-[var(--text-tertiary)] max-w-lg leading-relaxed text-left">
          评分由 Langfuse 的 LLM-as-judge evaluator 自动产生。配置步骤:
          <ol class="list-decimal ml-5 mt-1.5 space-y-1">
            <li>打开 <span class="font-mono text-[var(--text-secondary)]">http://localhost:3000</span> 登录 Langfuse。</li>
            <li>先在 <span class="text-[var(--text-secondary)]">Settings → LLM 连接</span> 配一个 OpenAI 兼容端点(可用你们的 DeepSeek)。</li>
            <li>在 <span class="text-[var(--text-secondary)]">Evaluators</span> 新建 LLM-as-judge,配置工具调用质量维度(tool_selection/tool_order_reasoning/argument_quality/result_utilization)。详见 <code class="text-[11px]">docs/langfuse-judge-setup.md</code>。</li>
            <li>和 Agent 聊几句,新对话会自动被打分,回本页即可看到。</li>
          </ol>
        </div>
        <MetricInfo v-bind="EXPLAINERS.judgeHow" />
      </div>

      <!-- 数据主体 -->
      <div v-else-if="data" class="max-w-[1800px] mx-auto p-6 pt-4 space-y-4">
        <!-- KPI -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div v-for="c in kpiCards" :key="c.label"
            class="rounded-lg border border-[var(--border-light)] bg-[var(--background-card)] p-3 flex flex-col gap-1 relative">
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

        <!-- 各维度平均分 + 分布 (仅全部维度时) -->
        <template v-if="!isFiltered">
          <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <EChartCard :option="byNameOption" :has-data="byNameHasData" :height="240" empty-text="暂无评分维度数据">
              <template #title>各维度平均分<MetricInfo v-bind="EXPLAINERS.scoreByDimension" /></template>
              <template #meta>柱: 平均分</template>
            </EChartCard>
            <EChartCard :option="distributionOption" :has-data="distHasData" :height="240" empty-text="暂无评分分布数据">
              <template #title>评分分布<MetricInfo v-bind="EXPLAINERS.scoreDistribution" /></template>
              <template #meta>柱: 该分值出现次数</template>
            </EChartCard>
          </div>

          <!-- 评分维度明细表 -->
          <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden">
            <div class="flex items-center gap-2 px-4 py-3 border-b border-[var(--border-light)]">
              <span class="text-sm font-semibold text-[var(--text-primary)]">评分维度明细</span>
              <MetricInfo v-bind="EXPLAINERS.scoreTable" />
            </div>
            <div v-if="data.by_name.length" class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead>
                  <tr class="text-[var(--text-tertiary)] text-left border-b border-[var(--border-light)]">
                    <th class="py-2 px-4 font-medium">评分维度</th>
                    <th class="py-2 px-4 font-medium text-right">评分次数</th>
                    <th class="py-2 px-4 font-medium text-right">平均分</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="n in data.by_name" :key="n.name" class="border-b border-[var(--border-light)]/50">
                    <td class="py-2 px-4 text-[var(--text-primary)]">{{ dimensionLabel(n.name) }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ n.count }}</td>
                    <td class="py-2 px-4 font-mono tabular-nums text-right text-[var(--text-secondary)]">{{ n.avg_value.toFixed(3) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- 趋势 + 按模型 -->
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <EChartCard :option="trendOption" :has-data="trendHasData" :height="220" empty-text="暂无趋势数据">
            <template #title>评分趋势<MetricInfo v-bind="EXPLAINERS.scoreTrend" /></template>
            <template #meta>线: 平均分(左) / 评分次数(右)</template>
          </EChartCard>
          <EChartCard :option="byModelOption" :has-data="byModelHasData" :height="220" empty-text="暂无按模型评分数据">
            <template #title>按模型平均分<MetricInfo v-bind="EXPLAINERS.scoreByModel" /></template>
            <template #meta>柱: 平均分(评分挂在会话级未绑模型时为空)</template>
          </EChartCard>
        </div>
      </div>
      </div>
      <!-- 工具调用 tab -->
      <div v-else-if="activeTab === 'tools'" class="p-6 max-w-[1800px] mx-auto">
        <ToolsOverviewPanel :window="windowSel" :status="status" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { RefreshCw, AlertTriangle, Award } from 'lucide-vue-next';
import type { EChartsOption } from 'echarts';
import EChartCard from '@/components/EChartCard.vue';
import MetricInfo from '@/components/MetricInfo.vue';
import ToolsOverviewPanel from '@/components/ToolsOverviewPanel.vue';
import { EXPLAINERS } from '@/constants/explainers';
import { dimensionLabel } from '@/utils/scoreLabels';
import { getLangfuseStatus, getLangfuseScores } from '@/api/langfuse';
import type { LangfuseScoresOverview, LangfuseStatus } from '@/types/langfuse';
import { showErrorToast } from '@/utils/toast';

const AXIS = '#6b7280';
const SPLIT = 'rgba(107,114,128,0.15)';
const PALETTE = ['#3a6b8c', '#e85d2a', '#e8b62a', '#10b981', '#8b5cf6', '#ec4899'];
const WINDOWS: [string, string][] = [['today', '今日'], ['7d', '7天'], ['30d', '30天']];

const loading = ref(false);
const status = ref<LangfuseStatus | null>(null);
const data = ref<LangfuseScoresOverview | null>(null);
const windowSel = ref('7d');
const nameSel = ref(''); // '' = 全部维度
const nameOptions = ref<string[]>([]);
const activeTab = ref<'scores' | 'tools'>('scores');

const isFiltered = computed(() => !!nameSel.value);
const windowLabel = computed(() => WINDOWS.find((w) => w[0] === windowSel.value)?.[1] ?? windowSel.value);
const disabledState = computed(() => status.value && (!status.value.enabled || !status.value.configured));
const hasData = computed(() => !!data.value?.kpi && (data.value.kpi.score_count > 0 || data.value.by_name.length > 0));

// ── KPI 卡片 ──
const kpiCards = computed(() => {
  const k = data.value?.kpi;
  if (!k) return [];
  return [
    { label: '评分次数', value: String(k.score_count), unit: '次', hint: EXPLAINERS.scoreCount, sub: '' },
    { label: '平均分', value: k.avg_score.toFixed(2), unit: '', hint: EXPLAINERS.avgScore, sub: '' },
    { label: '评分维度数', value: String(isFiltered.value ? 1 : k.score_name_count), unit: '个', hint: EXPLAINERS.scoreNameCount, sub: '' },
    { label: '评分模型数', value: String(k.score_model_count), unit: '个', hint: EXPLAINERS.scoreModelCount, sub: byModelHasData.value ? '' : '未绑模型' },
  ];
});

const byNameHasData = computed(() => (data.value?.by_name.length ?? 0) > 0);
const distHasData = computed(() => (data.value?.distribution.length ?? 0) > 0);
const trendHasData = computed(() => (data.value?.daily.some((d) => d.count > 0) ?? false));
const byModelHasData = computed(() => (data.value?.by_model.length ?? 0) > 0);

// ── 图表 option ──
const byNameOption = computed<EChartsOption>(() => {
  const rows = data.value?.by_name ?? [];
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v) => Number(v).toFixed(3) },
    grid: { left: 8, right: 16, bottom: 8, top: 20, containLabel: true },
    xAxis: {
      type: 'category', data: rows.map((r) => dimensionLabel(r.name)),
      axisLabel: { color: AXIS, fontSize: 10, interval: 0, rotate: rows.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: SPLIT } },
    },
    yAxis: { type: 'value', axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [{
      type: 'bar', data: rows.map((r) => Number(r.avg_value.toFixed(4))),
      itemStyle: { color: '#3a6b8c' }, barMaxWidth: 40,
      label: { show: true, position: 'top', color: AXIS, fontSize: 10, formatter: (p: any) => Number(p.value).toFixed(2) },
    }],
  };
});

const distributionOption = computed<EChartsOption>(() => {
  const rows = data.value?.distribution ?? [];
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 16, bottom: 8, top: 20, containLabel: true },
    xAxis: {
      type: 'category', data: rows.map((r) => String(r.value)),
      axisLabel: { color: AXIS, fontSize: 10, rotate: rows.length > 8 ? 30 : 0 },
      axisLine: { lineStyle: { color: SPLIT } },
    },
    yAxis: { type: 'value', name: '次数', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [{ type: 'bar', data: rows.map((r) => r.count), itemStyle: { color: '#e8b62a' }, barMaxWidth: 30 }],
    color: PALETTE,
  };
});

function shortDate(d: string): string {
  return d.length >= 10 ? d.slice(5) : d;
}

const trendOption = computed<EChartsOption>(() => {
  const rows = data.value?.daily ?? [];
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['平均分', '评分次数'], textStyle: { color: AXIS, fontSize: 10 }, top: 0 },
    color: ['#10b981', '#3a6b8c'],
    grid: { left: 8, right: 8, bottom: 8, top: 30, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: rows.map((d) => shortDate(d.date)), axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { lineStyle: { color: SPLIT } } },
    yAxis: [
      { type: 'value', name: '平均分', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
      { type: 'value', name: '次数', nameTextStyle: { color: AXIS, fontSize: 10 }, axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { show: false } },
    ],
    series: [
      { name: '平均分', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: rows.map((d) => Number(d.avg_value.toFixed(4))), itemStyle: { color: '#10b981' }, areaStyle: { opacity: 0.1 } },
      { name: '评分次数', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'circle', symbolSize: 5, data: rows.map((d) => d.count), itemStyle: { color: '#3a6b8c' } },
    ],
  };
});

const byModelOption = computed<EChartsOption>(() => {
  const rows = data.value?.by_model ?? [];
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v) => Number(v).toFixed(3) },
    grid: { left: 8, right: 16, bottom: 8, top: 20, containLabel: true },
    xAxis: {
      type: 'category', data: rows.map((r) => r.model),
      axisLabel: { color: AXIS, fontSize: 10, interval: 0, rotate: rows.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: SPLIT } },
    },
    yAxis: { type: 'value', axisLabel: { color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: SPLIT } } },
    series: [{
      type: 'bar', data: rows.map((r) => Number(r.avg_value.toFixed(4))),
      itemStyle: { color: '#8b5cf6' }, barMaxWidth: 40,
      label: { show: true, position: 'top', color: AXIS, fontSize: 10, formatter: (p: any) => Number(p.value).toFixed(2) },
    }],
  };
});

// ── 取数 ──
async function refresh() {
  loading.value = true;
  try {
    data.value = await getLangfuseScores(windowSel.value, nameSel.value || null);
    if (!nameSel.value && data.value.by_name.length) {
      const set = new Set(nameOptions.value);
      data.value.by_name.forEach((n) => set.add(n.name));
      nameOptions.value = [...set].sort();
    }
    if (data.value.error) showErrorToast(data.value.error);
  } catch (e: any) {
    showErrorToast(e?.message ?? '加载评分数据失败');
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
watch(nameSel, () => refresh());

onMounted(async () => {
  await loadStatus();
  if (!disabledState.value) await refresh();
});
</script>
