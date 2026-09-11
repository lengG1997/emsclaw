<template>
  <div class="rounded-xl border border-[var(--border-main)] bg-[var(--background-card)] overflow-hidden my-2">
    <div class="px-4 py-2.5 border-b border-[var(--border-light)] flex items-center justify-between">
      <div class="text-[13px] font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
        <GitCompare :size="14" class="text-sky-500" /> 多方案对比
        <span class="text-[11px] font-normal text-[var(--text-tertiary)]">
          · {{ plans.length }} 个方案<template v-if="targetDate"> · {{ targetDate }}</template>
        </span>
      </div>
      <span class="text-[11px] text-[var(--text-tertiary)]">✓ = 该指标最优 ｜ 按方案名定位</span>
    </div>

    <!-- 对比表:行=指标,列=方案 -->
    <div class="px-4 py-3 overflow-x-auto">
      <table class="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            <th class="text-left font-medium text-[var(--text-tertiary)] text-[12px] py-1.5 pr-3 whitespace-nowrap">指标</th>
            <th v-for="(p, i) in plans" :key="i" class="text-right font-medium text-[var(--text-primary)] py-1.5 px-3 whitespace-nowrap">
              <div>{{ planTitle(p, i) }}</div>
              <div class="text-[11px] font-normal text-[var(--text-tertiary)] max-w-[150px] truncate">{{ stratText(p) }}</div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key" class="border-t border-[var(--border-light)]">
            <td class="py-1.5 pr-3 text-[var(--text-tertiary)] whitespace-nowrap">{{ row.label }}</td>
            <td
              v-for="(p, i) in plans"
              :key="i"
              class="py-1.5 px-3 text-right tabular-nums whitespace-nowrap"
              :class="isBest(row, i) ? 'font-semibold text-[var(--function-success)]' : 'text-[var(--text-primary)]'"
            >
              {{ fmtValue(p, row) }}<span class="text-[10px] font-normal text-[var(--text-tertiary)] ml-0.5">{{ row.unit }}</span>
              <span v-if="isBest(row, i)" class="ml-1">✓</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 选择入口:点击后作为消息发回后端(回传文本带指标指纹,避免与 LLM 命名错位) -->
    <div class="px-4 pb-3">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="(p, i) in plans"
          :key="i"
          class="px-3 py-1.5 rounded-lg text-[12px] font-medium border border-[var(--border-main)] text-[var(--text-primary)] hover:bg-[var(--background-gray-main)] transition-colors"
          @click="pick(i)"
        >
          采用「{{ planTitle(p, i) }}」<span class="text-[var(--text-tertiary)] font-normal"> · {{ stratText(p) }}</span>
        </button>
      </div>
      <div class="mt-2 text-[11px] text-[var(--text-tertiary)]">
        方案名由 AI 在生成时指定；点击后会连同策略与关键指标一并回传，AI 据此唯一定位（不依赖序号）。
      </div>
    </div>
    <!-- 各方案 24h 曲线(默认折叠) -->
    <div class="px-3 pb-3 space-y-2">
      <details v-for="(p, i) in plans" :key="i" class="rounded-lg border border-[var(--border-light)] overflow-hidden">
        <summary class="cursor-pointer select-none px-3 py-2 text-[12px] text-[var(--text-primary)] bg-[var(--background-gray-main)]">
          方案 {{ i + 1 }} · 24h 充放电曲线
        </summary>
        <DispatchPreview :data="p" />
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { GitCompare } from 'lucide-vue-next';
import DispatchPreview from './DispatchPreview.vue';
import { buildPickText, planTitle, type DispatchPlan as Plan } from '../utils/dispatchPlans';

interface Row {
  key: string;
  label: string;
  unit: string;
  better: 'max' | 'min';
  scale?: number;
}

const props = defineProps<{ plans: Plan[] }>();
const emit = defineEmits<{ (e: 'pick', text: string): void }>();

const plans = computed(() => props.plans || []);
const targetDate = computed(() => plans.value[0]?.target_date || '');
const stratText = (p: Plan) => (p.strategies?.length ? p.strategies.join('+') : '—');

// 指标行:better 决定"最优"方向(数值越大/越小越好)
const rows: Row[] = [
  { key: 'est_savings_yuan', label: '预计节省', unit: '元/日', better: 'max' },
  { key: '__cycle', label: '峰谷循环', unit: 'kWh', better: 'max' },
  { key: 'green_rate', label: '绿电消纳率', unit: '%', better: 'max', scale: 100 },
  { key: 'peak_demand_kw', label: '需量峰值', unit: 'kW', better: 'min' },
];

const rawValue = (p: Plan, row: Row): number => {
  const s = p.summary || {};
  const v = row.key === '__cycle'
    ? (s.charge_kwh || 0) + (s.discharge_kwh || 0)
    : (s[row.key] || 0);
  return row.scale ? v * row.scale : v;
};

const fmtValue = (p: Plan, row: Row) =>
  Number(rawValue(p, row)).toLocaleString('zh-CN', { maximumFractionDigits: 0 });

const isBest = (row: Row, i: number): boolean => {
  const vals = plans.value.map(p => rawValue(p, row));
  if (vals.length < 2) return false;
  const target = row.better === 'max' ? Math.max(...vals) : Math.min(...vals);
  const hits = vals.filter(v => v === target).length;
  return hits === 1 && vals[i] === target;
};

// 回传文本必须带「编号 + 指标指纹」。原因见 utils/dispatchPlans.ts 顶部注释。
const pick = (i: number) => emit('pick', buildPickText(plans.value[i] || {}, i));
</script>
