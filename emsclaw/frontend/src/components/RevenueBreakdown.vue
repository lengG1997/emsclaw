<template>
  <div class="rounded-xl border border-[var(--border-main)] bg-[var(--background-card)] overflow-hidden my-2">
    <div class="px-4 py-2.5 border-b border-[var(--border-light)] flex items-center justify-between">
      <div class="text-[13px] font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
        <Coins :size="14" class="text-[#6b8e4e]" /> 收益核算
        <span v-if="data.date" class="text-[11px] font-normal text-[var(--text-tertiary)]">· {{ data.date }}</span>
      </div>
    </div>

    <!-- 总收益 -->
    <div class="px-4 pt-3 flex items-end gap-2">
      <span class="text-2xl font-bold text-[var(--function-success)] tabular-nums">{{ fmt(sources.total_yuan) }}</span>
      <span class="text-xs text-[var(--text-tertiary)] mb-1">元 / 日</span>
    </div>

    <!-- 收益来源 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 px-4 py-3">
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">峰谷套利</div>
        <div class="text-[14px] font-semibold text-[var(--text-primary)] tabular-nums">{{ fmt(sources.arbitrage_yuan) }}</div>
      </div>
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">光伏自用节省</div>
        <div class="text-[14px] font-semibold text-[var(--text-primary)] tabular-nums">{{ fmt(sources.pv_self_use_savings_yuan) }}</div>
      </div>
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">需量节省</div>
        <div class="text-[14px] font-semibold text-[var(--text-primary)] tabular-nums">{{ fmt(sources.demand_savings_yuan) }}</div>
      </div>
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">碳减排</div>
        <div class="text-[14px] font-semibold text-[#3a6b8c] tabular-nums">{{ fmt(carbon.reduction_kg) }}<span class="text-[11px] font-normal ml-0.5">kg</span></div>
      </div>
    </div>

    <!-- 收益来源构成图 -->
    <div class="px-2 pb-1">
      <v-chart :option="sourceChart" :autoresize="true" class="w-full" style="height: 140px" />
    </div>

    <!-- 电量概览 + 时段分解 -->
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 px-4 pb-3">
      <div class="text-[11px] text-[var(--text-tertiary)] leading-relaxed">
        <div class="flex justify-between py-0.5"><span>充电量</span><b class="tabular-nums text-[var(--text-primary)]">{{ fmt(energy.charge_kwh) }} kWh</b></div>
        <div class="flex justify-between py-0.5"><span>放电量</span><b class="tabular-nums text-[var(--text-primary)]">{{ fmt(energy.discharge_kwh) }} kWh</b></div>
        <div class="flex justify-between py-0.5"><span>购电量</span><b class="tabular-nums text-[var(--text-primary)]">{{ fmt(energy.import_kwh) }} kWh</b></div>
        <div class="flex justify-between py-0.5"><span>光伏自用</span><b class="tabular-nums text-[var(--text-primary)]">{{ fmt(energy.pv_self_use_kwh) }} kWh</b></div>
        <div class="flex justify-between py-0.5"><span>需量峰值</span><b class="tabular-nums text-[var(--text-primary)]">{{ fmt(demand.actual_peak_kw) }} kW</b></div>
      </div>
      <div>
        <div class="text-[11px] text-[var(--text-tertiary)] mb-1">分时段收支</div>
        <v-chart :option="periodChart" :autoresize="true" class="w-full" style="height: 150px" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { Coins } from 'lucide-vue-next';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import type { EChartsOption } from 'echarts';

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent]);

const props = defineProps<{
  data: {
    date?: string;
    sources?: Record<string, number>;
    energy?: Record<string, number>;
    demand?: Record<string, number>;
    carbon?: Record<string, number>;
    period_breakdown?: Record<string, Record<string, number>>;
  };
}>();

const sources = computed(() => (props.data.sources || {}) as Record<string, number>);
const energy = computed(() => (props.data.energy || {}) as Record<string, number>);
const demand = computed(() => (props.data.demand || {}) as Record<string, number>);
const carbon = computed(() => (props.data.carbon || {}) as Record<string, number>);

const periodRows = computed(() => (props.data.period_breakdown || {}) as Record<string, Record<string, number>>);

const fmt = (v: number | undefined | null) => {
  if (v === undefined || v === null) return '0';
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
};

// 收益来源构成(横向柱状):峰谷套利 / 光伏自用节省 / 需量节省(碳为 kg,口径不同,不混入)
const sourceChart = computed<EChartsOption>(() => {
  const items = [
    { name: '峰谷套利', value: Number(sources.value.arbitrage_yuan || 0) },
    { name: '光伏自用节省', value: Number(sources.value.pv_self_use_savings_yuan || 0) },
    { name: '需量节省', value: Number(sources.value.demand_savings_yuan || 0) },
  ].filter((d) => d.value !== 0);
  const names = items.map((d) => d.name);
  const vals = items.map((d) => d.value);
  return {
    grid: { left: 88, right: 48, top: 10, bottom: 18 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: any) => `${fmt(v)} 元` },
    xAxis: { type: 'value', axisLine: { lineStyle: { color: 'var(--border-light)' } }, splitLine: { lineStyle: { color: 'var(--border-light)' } } },
    yAxis: { type: 'category', data: names, inverse: true, axisTick: { show: false }, axisLine: { show: false } },
    series: [{
      type: 'bar', data: vals, barWidth: 14,
      itemStyle: { color: '#6b8e4e', borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', formatter: (p: any) => `${fmt(p.value)} 元`, fontSize: 11 },
    }],
  };
});

// 分时段收支(分组柱状:充电/放电/收益,按尖峰平谷)
const periodChart = computed<EChartsOption>(() => {
  const rows = periodRows.value;
  const order = ['尖', '峰', '平', '谷'].filter((p) => p in rows);
  const names = Object.keys(rows).filter((p) => !order.includes(p)).reduce((acc: string[], p) => acc.concat(p), order);
  const num = (v: any) => Number(v || 0);
  return {
    grid: { left: 40, right: 16, top: 28, bottom: 24 },
    legend: { data: ['充电', '放电', '收益'], top: 0, textStyle: { fontSize: 11 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: any) => fmt(v) },
    xAxis: { type: 'category', data: names, axisLine: { lineStyle: { color: 'var(--border-light)' } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'var(--border-light)' } } },
    series: [
      { name: '充电', type: 'bar', data: names.map((p) => num(rows[p]?.charge_kwh)), itemStyle: { color: '#3a6b8c' } },
      { name: '放电', type: 'bar', data: names.map((p) => num(rows[p]?.discharge_kwh)), itemStyle: { color: '#e8b62a' } },
      { name: '收益', type: 'bar', data: names.map((p) => num(rows[p]?.revenue)), itemStyle: { color: '#6b8e4e' } },
    ],
  };
});
</script>
