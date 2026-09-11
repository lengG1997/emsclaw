<template>
  <div class="flex items-center gap-1.5 flex-wrap">
    <span
      v-for="p in pills"
      :key="p.name"
      class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium border"
      :class="pillClass(p)"
    >
      <span class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(p)"></span>
      <span class="text-[var(--text-secondary)]">{{ dimensionLabel(p.name) }}</span>
      <span class="tabular-nums font-semibold" :class="scoreValueClassFromNum(p.value)">{{ p.value.toFixed(1) }}</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import { dimensionLabel, scoreValueClassFromNum, scoreBarClassFromNum } from '@/utils/scoreLabels';

export interface ScorePill {
  name: string;
  value: number; // 1-5
}

defineProps<{
  pills: ScorePill[];
}>();

function pillClass(p: ScorePill) {
  const n = p.value / 5;
  if (n >= 0.8) return 'border-emerald-500/30 bg-emerald-500/5';
  if (n >= 0.5) return 'border-amber-500/30 bg-amber-500/5';
  return 'border-red-500/30 bg-red-500/5';
}

function dotClass(p: ScorePill) {
  return scoreBarClassFromNum(p.value);
}
</script>
