<template>
  <div class="rounded-xl border border-[var(--border-main)] bg-[var(--background-card)] overflow-hidden my-2">
    <div class="px-4 py-2.5 border-b border-[var(--border-light)] flex items-center justify-between">
      <div class="text-[13px] font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
        <Activity :size="14" class="text-[#0ea5e9]" /> 执行状态
        <span v-if="data.date" class="text-[11px] font-normal text-[var(--text-tertiary)]">· {{ data.date }} {{ String(data.current_hour ?? '').padStart(2, '0') }}:00</span>
      </div>
      <span class="text-[11px] px-2 py-0.5 rounded-full font-medium"
        :class="data.on_track ? 'bg-[var(--function-success)]/10 text-[var(--function-success)]' : 'bg-[var(--function-danger)]/10 text-[var(--function-danger)]'">
        {{ data.on_track ? '跟得上' : '有偏差' }}
      </span>
    </div>

    <div class="px-4 py-3 space-y-3">
      <!-- 当前小时计划 -->
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-[var(--text-tertiary)]">当前小时计划</span>
        <span class="font-medium text-[var(--text-primary)]">
          <span :class="modeColor(data.current_hour_plan?.mode)">{{ modeLabel(data.current_hour_plan?.mode) }}</span>
          <span v-if="data.current_hour_plan?.power_kw" class="tabular-nums ml-1">{{ Math.round(data.current_hour_plan.power_kw) }} kW</span>
          <span v-if="!data.current_hour_plan" class="text-[var(--text-tertiary)]">无</span>
        </span>
      </div>

      <!-- 计划 SOC vs 实际 SOC 双条 -->
      <div class="space-y-1.5">
        <div class="flex items-center justify-between text-[11px] text-[var(--text-tertiary)]">
          <span>计划 SOC</span>
          <b class="tabular-nums text-[var(--text-secondary)]">{{ pct(data.planned_soc_pct) }}</b>
        </div>
        <div class="h-2 rounded-full bg-[var(--background-gray-main)] overflow-hidden">
          <div class="h-full rounded-full bg-[#3a6b8c]" :style="{ width: barW(data.planned_soc_pct) }"></div>
        </div>

        <div class="flex items-center justify-between text-[11px] text-[var(--text-tertiary)] pt-0.5">
          <span>实际 SOC</span>
          <b class="tabular-nums" :class="data.on_track ? 'text-[var(--function-success)]' : 'text-[var(--function-danger)]'">{{ pct(data.actual_soc_pct) }}</b>
        </div>
        <div class="h-2 rounded-full bg-[var(--background-gray-main)] overflow-hidden">
          <div class="h-full rounded-full" :class="data.on_track ? 'bg-[var(--function-success)]' : 'bg-[var(--function-danger)]'" :style="{ width: barW(data.actual_soc_pct) }"></div>
        </div>
      </div>

      <!-- 偏差 -->
      <div class="flex items-center justify-between text-[12px] pt-1 border-t border-[var(--border-light)]">
        <span class="text-[var(--text-tertiary)]">SOC 偏差</span>
        <b class="tabular-nums" :class="data.on_track ? 'text-[var(--function-success)]' : 'text-[var(--function-danger)]'">
          {{ Number(data.deviation_pct) >= 0 ? '+' : '' }}{{ pct(data.deviation_pct) }}
        </b>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Activity } from 'lucide-vue-next';

defineProps<{
  data: {
    date?: string;
    current_hour?: number;
    current_hour_plan?: { hour: number; mode: string; power_kw?: number } | null;
    actual_soc_pct?: number;
    planned_soc_pct?: number;
    deviation_pct?: number;
    on_track?: boolean;
  };
}>();

const pct = (v: number | undefined | null) => {
  if (v === undefined || v === null) return '—';
  return `${(Number(v) * 100).toFixed(1)}%`;
};
const barW = (v: number | undefined | null) => {
  if (v === undefined || v === null) return '0%';
  return `${Math.max(0, Math.min(100, Number(v) * 100))}%`;
};
const modeLabel = (m?: string) => ({ charge: '充电', discharge: '放电', standby: '待机' }[m || ''] || m || '—');
const modeColor = (m?: string) => ({
  charge: 'text-[#3a6b8c]',
  discharge: 'text-[#e8b62a]',
  standby: 'text-[var(--text-tertiary)]',
}[m || ''] || '');
</script>
