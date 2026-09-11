<template>
  <div class="flex flex-col h-full w-full overflow-hidden">
    <!-- Masthead -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1800px] mx-auto flex items-end justify-between gap-4 flex-wrap">
        <div class="flex items-end gap-3">
          <div class="flex items-center gap-2.5">
            <span class="size-2 rounded-full"
              :class="loading ? 'bg-[var(--function-warning)] animate-pulse' : (data?.enabled ? 'bg-[var(--function-success)]' : 'bg-[var(--function-danger)]')"></span>
            <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">技能评估</h1>
            <span class="text-[11px] text-[var(--text-tertiary)]">离线 dataset + Code evaluator</span>
            <MetricInfo v-bind="EXPLAINERS.evalOverall" />
          </div>
          <div v-if="data" class="text-xs text-[var(--text-tertiary)] pb-0.5 font-mono">
            {{ data?.runs?.length ?? 0 }} 个版本 · {{ datasetSel || '全部' }}
          </div>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <!-- dataset 选择器 -->
          <div class="flex items-center gap-1">
            <span class="text-[11px] text-[var(--text-tertiary)]">dataset</span>
            <select v-model="datasetSel" :disabled="loading || !datasets?.length"
              class="h-8 rounded-md border border-[var(--border-main)] bg-[var(--background-card)] text-xs text-[var(--text-primary)] px-2 max-w-[220px] disabled:opacity-40 focus:outline-none focus:border-[#3a6b8c]">
              <option value="">全部</option>
              <option v-for="d in datasets" :key="d.name" :value="d.name">{{ d.name }} ({{ d.items_count }})</option>
            </select>
          </div>
          <button @click="openPromptModal" :disabled="promptLoading"
            class="h-8 px-2.5 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1.5 disabled:opacity-40 text-xs"
            title="查看 Lead 提示词各版本">
            <FileText :size="13" />
            <span>查看提示词</span>
            <span v-if="promptLoading" class="size-3 border-2 border-[var(--text-tertiary)] border-t-transparent rounded-full animate-spin"></span>
          </button>
          <button @click="refresh" :disabled="loading"
            class="size-8 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center justify-center disabled:opacity-40"
            title="刷新">
            <RefreshCw :size="13" :class="{ 'animate-spin': loading }" />
          </button>
        </div>
      </div>
    </div>

    <!-- 禁用态 -->
    <div v-if="!loading && data && !data.enabled" class="flex-1 flex items-center justify-center text-sm text-[var(--text-tertiary)]">
      Langfuse 未启用,无法查看评估数据
    </div>

    <!-- 空态 -->
    <div v-else-if="!loading && data && data.runs.length === 0" class="flex-1 flex items-center justify-center text-sm text-[var(--text-tertiary)]">
      {{ datasetSel ? `dataset "${datasetSel}" 暂无 experiment run` : '暂无 experiment run,先跑一次 `python -m emsclaw_backend.observability.eval.cli run --dataset <name> --run-name <v1>`' }}
    </div>

    <!-- 主区:版本卡片列表 + 趋势图 -->
    <div v-else class="flex-1 overflow-auto p-6 max-w-[1800px] mx-auto w-full">
      <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <!-- 左:版本卡片列表 -->
        <div class="xl:col-span-2 space-y-3">
          <div v-for="run in data?.runs || []" :key="run.experiment_id"
            class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] p-4">
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <div class="text-sm font-semibold text-[var(--text-primary)]">{{ run.experiment_name }}</div>
                <div class="text-[11px] text-[var(--text-tertiary)] mt-0.5 font-mono">
                  {{ run.started_at ? formatTime(run.started_at) : '—' }} · {{ run.scored_count }}/{{ run.item_count }} scored
                </div>
              </div>
              <div class="text-right">
                <div class="text-2xl font-bold tabular-nums"
                  :class="run.overall_pass_rate >= 0.8 ? 'text-[var(--function-success)]' : (run.overall_pass_rate >= 0.5 ? 'text-[var(--function-warning)]' : 'text-[var(--function-danger)]')">
                  {{ (run.overall_pass_rate * 100).toFixed(1) }}%
                </div>
                <div class="text-[10px] text-[var(--text-tertiary)] flex items-center gap-1 justify-end">
                  overall pass rate
                  <MetricInfo v-bind="EXPLAINERS.evalOverall" />
                </div>
              </div>
            </div>

            <!-- 维度条形图 -->
            <div class="mt-3 grid grid-cols-1 md:grid-cols-5 gap-2">
              <div v-for="dim in run.dimensions" :key="dim.name"
                class="bg-[var(--background-gray-main)] rounded-md border border-[var(--border-light)] p-2">
                <div class="flex items-center justify-between text-[11px] mb-1">
                  <span class="text-[var(--text-secondary)] flex items-center gap-1">
                    <span class="font-mono">{{ dim.name }}</span>
                    <MetricInfo v-bind="DIM_META[dim.name]?.explainer ?? { title: dim.name, explain: '' }" />
                  </span>
                  <span class="text-[var(--text-tertiary)] tabular-nums">{{ dim.passed }}/{{ dim.total }}</span>
                </div>
                <div class="h-1.5 rounded-full bg-[var(--border-main)] overflow-hidden">
                  <div class="h-full rounded-full transition-all"
                    :class="dim.pass_rate >= 0.8 ? 'bg-[var(--function-success)]' : (dim.pass_rate >= 0.5 ? 'bg-[var(--function-warning)]' : 'bg-[var(--function-danger)]')"
                    :style="{ width: (dim.pass_rate * 100) + '%' }"></div>
                </div>
                <div class="text-[10px] text-[var(--text-tertiary)] mt-1 tabular-nums">{{ (dim.pass_rate * 100).toFixed(0) }}%</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 右:版本对比趋势图 -->
        <div class="space-y-3">
          <EChartCard description="各版本 overall 通过率趋势(按时间正序)"
            :option="trendOption" :has-data="trendHasData" :height="320" empty-text="需要 ≥ 1 个 run">
            <template #title>版本趋势</template>
            <template #meta>{{ trendMeta }}</template>
          </EChartCard>

          <EChartCard description="各 run 各维度通过率(柱状,0~1)"
            :option="barOption" :has-data="barHasData" :height="280" empty-text="需要 ≥ 1 个 run">
            <template #title>维度对比</template>
            <template #meta>{{ barMeta }}</template>
          </EChartCard>
        </div>
      </div>
    </div>

    <!-- 提示词版本 Modal -->
    <Dialog :open="promptModalOpen" @update:open="(v: boolean) => { promptModalOpen = v }">
      <DialogContent class="w-[900px] max-w-[95vw]">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2 text-base">
            <FileText :size="15" class="text-[var(--text-secondary)]" />
            <span class="font-mono">business_lead 提示词</span>
            <span v-if="promptVersions?.length" class="text-xs font-normal text-[var(--text-tertiary)]">
              {{ promptVersions.length }} 个版本 · production=v{{ promptProductionVersion ?? '-' }}
            </span>
          </DialogTitle>
        </DialogHeader>
        <div class="px-6 pb-6 space-y-3 max-h-[78vh] overflow-y-auto">
          <!-- 评估维度说明 + 命名约定 -->
          <div class="bg-[var(--background-gray-main)] rounded-md border border-[var(--border-light)] p-3 text-[11px] leading-relaxed text-[var(--text-secondary)]">
            <div class="font-semibold text-[var(--text-primary)] mb-1.5">如何对照 run ↔ 提示词版本?</div>
            <p class="mb-2">命名约定:<code class="text-[var(--text-primary)]">station-analysis-vN</code> 对应 Langfuse prompt <code class="text-[var(--text-primary)]">business_lead vN</code>(每次 sync 后新建一版 prompt,紧接跑一次 experiment)。Langfuse 不强绑,需要按跑的时间手动对照。</p>
            <div class="font-semibold text-[var(--text-primary)] mb-1.5 mt-2">5 个评估维度规则</div>
            <ul class="space-y-1 list-disc pl-4">
              <li><b>tool_set</b>:Lead 实际用的工具集 = 预期必用 + 不碰禁用工具。</li>
              <li><b>tool_order</b>:预期顺序是实际调用序列的子序列(允许中间插别的)。</li>
              <li><b>subagent</b>:Lead 把任务委派给了正确的领域专家(EmsStationExpert/PowerMarketExpert 等)。</li>
              <li><b>tool_count</b>:工具调用次数 ≤ max_tool_calls(每条样本标的预算)。</li>
              <li><b>repeat_rate</b>:相邻重复调用对数 / max(总次数-1, 1) ≤ max_repeat_ratio。</li>
            </ul>
            <p class="mt-2 text-[var(--text-tertiary)]">所有 pass_rate 都是「这一版样本中通过的比例」,分数越高越好。</p>
          </div>

          <!-- 版本选择 -->
          <div v-if="promptVersions && promptVersions.length > 0" class="flex items-center gap-2 flex-wrap">
            <span class="text-[11px] text-[var(--text-tertiary)]">版本:</span>
            <button v-for="v in promptVersions" :key="v.version"
              @click="selectedPromptVersion = v.version"
              :class="selectedPromptVersion === v.version
                ? 'bg-[#3a6b8c] text-white border-[#3a6b8c]'
                : 'bg-[var(--background-card)] text-[var(--text-secondary)] border-[var(--border-main)] hover:bg-[var(--background-gray-main)]'"
              class="h-7 px-2.5 rounded-md border text-xs font-mono transition-colors flex items-center gap-1.5">
              v{{ v.version }}
              <span v-if="v.labels?.includes('production')" class="px-1 rounded text-[9px] bg-emerald-500/15 text-emerald-500 border border-emerald-500/30">prod</span>
            </button>
          </div>

          <!-- 选中版本的 prompt 内容 -->
          <div v-if="selectedPromptObj">
            <div class="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] mb-1 flex items-center justify-between">
              <span>v{{ selectedPromptObj.version }} 提示词原文</span>
              <span class="text-[var(--text-tertiary)] normal-case tracking-normal">{{ selectedPromptObj.prompt.length }} 字符</span>
            </div>
            <pre class="text-xs text-[var(--text-secondary)] whitespace-pre-wrap break-all bg-[var(--background-gray-main)] rounded px-3 py-2 max-h-[50vh] overflow-y-auto">{{ selectedPromptObj.prompt || '(空)' }}</pre>
            <div v-if="selectedPromptObj.error" class="text-[11px] text-[var(--function-danger)] mt-1">拉取失败:{{ selectedPromptObj.error }}</div>
          </div>
          <div v-else-if="promptLoading" class="text-xs text-[var(--text-tertiary)] py-4 text-center">加载中...</div>
          <div v-else-if="promptError" class="text-xs text-[var(--function-danger)] py-4 text-center">{{ promptError }}</div>
          <div v-else class="text-xs text-[var(--text-tertiary)] py-4 text-center">暂无版本数据</div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { RefreshCw, FileText } from 'lucide-vue-next';
import EChartCard from '@/components/EChartCard.vue';
import MetricInfo from '@/components/MetricInfo.vue';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getLangfuseDatasets, getLangfuseExperiments, getLangfusePromptVersions } from '@/api/langfuse';
import type { LangfusePromptVersion } from '@/api/langfuse';
import { EXPLAINERS, type Explainer } from '@/constants/explainers';
import type { LangfuseDataset, LangfuseExperimentsOverview } from '@/types/langfuse';
import type { EChartsOption } from 'echarts';

// 8 个评估维度名 -> 中文 + 通俗讲解 EXPLAINERS 条目
const DIM_META: Record<string, { zh: string; explainer: Explainer }> = {
  tool_set:            { zh: '工具集',   explainer: EXPLAINERS.evalToolSet },
  tool_order:          { zh: '调用顺序', explainer: EXPLAINERS.evalToolOrder },
  subagent:            { zh: '子 agent', explainer: EXPLAINERS.evalSubagent },
  tool_count:          { zh: '调用次数', explainer: EXPLAINERS.evalToolCount },
  repeat_rate:         { zh: '重复率',   explainer: EXPLAINERS.evalRepeatRate },
  tool_result_quality: { zh: '结果质量', explainer: EXPLAINERS.evalToolResult },
  tool_args_validity:  { zh: '参数有效', explainer: EXPLAINERS.evalToolArgs },
  tool_efficiency:     { zh: '调用效率', explainer: EXPLAINERS.evalToolEfficiency },
};

// 提示词版本 Modal 状态
const promptModalOpen = ref(false);
const promptLoading = ref(false);
const promptError = ref<string | null>(null);
const promptVersions = ref<LangfusePromptVersion[]>([]);
const promptProductionVersion = ref<number | null>(null);
const selectedPromptVersion = ref<number | null>(null);

const selectedPromptObj = computed<LangfusePromptVersion | null>(() => {
  if (!promptVersions.value.length || selectedPromptVersion.value === null) return null;
  return promptVersions.value.find((v) => v.version === selectedPromptVersion.value) ?? null;
});

async function openPromptModal() {
  promptModalOpen.value = true;
  if (promptVersions.value.length > 0) return; // 已加载过,直接显示
  promptLoading.value = true;
  promptError.value = null;
  try {
    const res = await getLangfusePromptVersions('business_lead');
    promptVersions.value = res.versions || [];
    promptProductionVersion.value = res.production_version ?? null;
    // 默认选中 production 版本(否则选最大版本号)
    const defaultV = promptProductionVersion.value
      ?? (promptVersions.value.length ? Math.max(...promptVersions.value.map((v) => v.version)) : null);
    selectedPromptVersion.value = defaultV;
    if (!promptVersions.value.length) {
      promptError.value = 'Langfuse 中无 business_lead 提示词;先 `python -m emsclaw_backend.observability.prompts sync` 同步一次。';
    }
  } catch (e: any) {
    promptError.value = e?.message || String(e);
  } finally {
    promptLoading.value = false;
  }
}

const loading = ref(false);
const datasets = ref<LangfuseDataset[]>([]);
const data = ref<LangfuseExperimentsOverview | null>(null);
const datasetSel = ref<string>('');

async function loadDatasets() {
  try {
    const res = await getLangfuseDatasets();
    datasets.value = res.datasets || [];
    if (!datasetSel.value && datasets.value.length > 0) {
      datasetSel.value = datasets.value[0].name;
    }
  } catch (e) {
    console.error('[experiments] loadDatasets failed:', e);
  }
}

async function loadExperiments() {
  loading.value = true;
  try {
    data.value = await getLangfuseExperiments(datasetSel.value || null);
  } catch (e) {
    console.error('[experiments] loadExperiments failed:', e);
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  await loadDatasets();
  await loadExperiments();
}

watch(datasetSel, () => { loadExperiments(); });
onMounted(refresh);

const DIM_ORDER = ['tool_set', 'tool_order', 'subagent', 'tool_count', 'repeat_rate', 'tool_result_quality', 'tool_args_validity', 'tool_efficiency'];
const runsSorted = computed(() => {
  return [...(data.value?.runs || [])].sort((a, b) => {
    const ta = a.started_at || '';
    const tb = b.started_at || '';
    return ta.localeCompare(tb);
  });
});

const trendHasData = computed(() => runsSorted.value.length > 0);
const trendMeta = computed(() => `${runsSorted.value.length} 个 run`);
const barHasData = computed(() => trendHasData.value);
const barMeta = computed(() => `${runsSorted.value.length} 个 run · ${DIM_ORDER.length} 维度`);

// 趋势图:折线,x=run 名(时间正序),y=overall_pass_rate
const trendOption = computed<EChartsOption>(() => {
  const runs = runsSorted.value;
  return {
    grid: { top: 24, right: 24, bottom: 60, left: 48 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        const v = typeof p.value === 'number' ? (p.value * 100).toFixed(1) + '%' : String(p.value);
        return `${p.name}<br/>overall: ${v}`;
      },
    },
    xAxis: {
      type: 'category',
      data: runs.map(r => r.experiment_name),
      axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 30, interval: 0 },
      axisLine: { lineStyle: { color: '#475569' } },
    },
    yAxis: {
      type: 'value',
      min: 0, max: 1,
      axisLabel: {
        color: '#94a3b8', fontSize: 10,
        formatter: (v: number) => (v * 100).toFixed(0) + '%',
      },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: [{
      type: 'line',
      data: runs.map(r => r.overall_pass_rate),
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 2, color: '#3a6b8c' },
      itemStyle: { color: '#3a6b8c' },
      areaStyle: { color: 'rgba(58, 107, 140, 0.15)' },
    }],
  };
});

// 柱状图:grouped bar,每个 run 一组,5 个维度各 1 柱
const barOption = computed<EChartsOption>(() => {
  const runs = runsSorted.value;
  // 每个 run 的 dimensions 按 DIM_ORDER 对齐(缺维度 → 0)
  const seriesByDim = DIM_ORDER.map(dname => ({
    name: dname,
    type: 'bar' as const,
    data: runs.map(r => {
      const d = r.dimensions.find(x => x.name === dname);
      return d ? d.pass_rate : 0;
    }),
    itemStyle: { color: dimColor(dname) },
  }));
  return {
    grid: { top: 36, right: 16, bottom: 60, left: 48 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return '';
        let s = params[0].name + '<br/>';
        for (const p of params) {
          const v = typeof p.value === 'number' ? (p.value * 100).toFixed(0) + '%' : String(p.value);
          s += `${p.marker} ${p.seriesName}: ${v}<br/>`;
        }
        return s;
      },
    },
    legend: {
      data: DIM_ORDER,
      top: 4,
      textStyle: { color: '#94a3b8', fontSize: 10 },
      itemWidth: 10, itemHeight: 10,
    },
    xAxis: {
      type: 'category',
      data: runs.map(r => r.experiment_name),
      axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 30, interval: 0 },
      axisLine: { lineStyle: { color: '#475569' } },
    },
    yAxis: {
      type: 'value',
      min: 0, max: 1,
      axisLabel: {
        color: '#94a3b8', fontSize: 10,
        formatter: (v: number) => (v * 100).toFixed(0) + '%',
      },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: seriesByDim,
  };
});

function dimColor(name: string): string {
  const m: Record<string, string> = {
    tool_set: '#3a6b8c',
    tool_order: '#0ea5e9',
    subagent: '#a78bfa',
    tool_count: '#f59e0b',
    repeat_rate: '#10b981',
  };
  return m[name] || '#64748b';
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  } catch {
    return iso;
  }
}
</script>
