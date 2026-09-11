<template>
  <div class="rounded-xl border border-[var(--border-main)] bg-[var(--background-card)] overflow-hidden my-2">
    <div class="px-4 py-2.5 border-b border-[var(--border-light)] flex items-center justify-between">
      <div class="text-[13px] font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
        <Zap :size="14" class="text-amber-500" /> 24h 充放电策略预览
        <span v-if="data.strategies?.length" class="text-[11px] font-normal text-[var(--text-tertiary)]">
          · {{ data.strategies.join('+') }} · {{ data.target_date }}
        </span>
      </div>
    </div>

    <!-- 关键数字卡 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 px-4 py-3">
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">预计节省</div>
        <div class="text-[15px] font-semibold text-[var(--function-success)] tabular-nums">{{ fmt(summary.est_savings_yuan) }}<span class="text-[11px] font-normal ml-0.5">元/日</span></div>
      </div>
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">峰谷循环</div>
        <div class="text-[15px] font-semibold text-[var(--text-primary)] tabular-nums">{{ fmt(summary.charge_kwh + summary.discharge_kwh) }}<span class="text-[11px] font-normal ml-0.5">kWh</span></div>
      </div>
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">绿电消纳率</div>
        <div class="text-[15px] font-semibold text-[var(--function-success)] tabular-nums">{{ (summary.green_rate * 100).toFixed(0) }}<span class="text-[11px] font-normal ml-0.5">%</span></div>
      </div>
      <div class="rounded-lg bg-[var(--background-gray-main)] px-3 py-2">
        <div class="text-[11px] text-[var(--text-tertiary)]">需量峰值</div>
        <div class="text-[15px] font-semibold text-[var(--text-primary)] tabular-nums">{{ fmt(summary.peak_demand_kw) }}<span class="text-[11px] font-normal ml-0.5">kW</span></div>
      </div>
    </div>

    <!-- 24h 图:充放功率柱状 + SOC 折线 -->
    <div class="px-2 pb-2">
      <v-chart :option="option" :autoresize="true" class="w-full" style="height: 220px" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { Zap } from 'lucide-vue-next';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import type { EChartsOption } from 'echarts';

use([CanvasRenderer, BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent]);

const props = defineProps<{
  data: {
    schedule?: Array<{
      hour: number;
      mode: 'charge' | 'discharge' | 'standby';
      power_kw: number;
      soc_target_pct: number;
      period?: string;
    }>;
    summary?: Record<string, number>;
    strategies?: string[];
    target_date?: string;
  };
}>();

const schedule = computed(() => props.data.schedule || []);
const summary = computed(() => (props.data.summary || {}) as Record<string, number>);

const fmt = (v: number | undefined | null) => {
  if (v === undefined || v === null) return '0';
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
};

const option = computed<EChartsOption>(() => {
  const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);
  const charge = schedule.value.map(s => (s.mode === 'charge' ? s.power_kw : 0));
  const discharge = schedule.value.map(s => (s.mode === 'discharge' ? -s.power_kw : 0));
  const soc = schedule.value.map(s => (s.soc_target_pct ?? 0) * 100);

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        if (!Array.isArray(params)) return '';
        const i = params[0].dataIndex;
        const seg = schedule.value[i];
        const lines = [`<b>${hours[i]}</b>`];
        if (seg?.period) lines.push(`时段:${seg.period}`);
        if (seg?.mode !== 'standby') lines.push(`模式:${seg.mode === 'charge' ? '充电' : '放电'} ${seg.power_kw.toFixed(0)}kW`);
        else lines.push('模式:待机');
        if (seg) lines.push(`计划SOC末:${(seg.soc_target_pct * 100).toFixed(0)}%`);
        return lines.join('<br/>');
      },
    },
    legend: { data: ['充电', '放电', 'SOC'], top: 0, right: 0, textStyle: { color: '#94a3b8', fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
    grid: { left: 44, right: 12, top: 28, bottom: 24 },
    xAxis: {
      type: 'category', data: hours,
      axisLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } },
      axisLabel: { color: '#94a3b8', fontSize: 10, interval: 2 },
    },
    yAxis: [
      { type: 'value', name: 'kW', axisLabel: { color: '#94a3b8', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.1)' } } },
      { type: 'value', name: 'SOC%', min: 0, max: 100, axisLabel: { color: '#6b8e4e', fontSize: 10 }, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: 0 }],
    series: [
      { name: '充电', type: 'bar', stack: 'p', data: charge, itemStyle: { color: '#e85d2a' }, barWidth: 8 },
      { name: '放电', type: 'bar', stack: 'p', data: discharge, itemStyle: { color: '#3a6b8c' }, barWidth: 8 },
      { name: 'SOC', type: 'line', yAxisIndex: 1, data: soc, smooth: true, symbol: 'circle', symbolSize: 4,
        lineStyle: { color: '#6b8e4e', width: 2 }, itemStyle: { color: '#6b8e4e' } },
    ],
  };
});
</script>
