<template>
  <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden flex flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--border-light)] gap-3">
      <div class="min-w-0">
        <div class="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <slot name="title" />
        </div>
        <div v-if="$slots.meta" class="text-[11px] text-[var(--text-tertiary)] mt-0.5 font-mono">
          <slot name="meta" />
        </div>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <slot name="header-extra" />
        <button
          @click="openModal"
          class="size-8 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center justify-center disabled:opacity-40"
          :disabled="!hasData"
          title="放大"
        >
          <Maximize2 :size="13" />
        </button>
      </div>
    </div>

    <!-- Description bar -->
    <div v-if="description" class="px-4 py-2 text-[11px] text-[var(--text-tertiary)] border-b border-[var(--border-light)] bg-[var(--background-gray-main)] leading-relaxed">{{ description }}</div>

    <!-- Chart -->
    <div class="px-3 pt-2 pb-3">
      <div v-if="hasData" :style="{ height: height + 'px' }" class="w-full">
        <v-chart :option="option" :autoresize="true" class="w-full h-full" />
      </div>
      <div v-else class="flex items-center justify-center text-xs text-[var(--text-disable)]" :style="{ height: height + 'px' }">{{ emptyText }}</div>
    </div>

    <!-- Fullscreen modal -->
    <Teleport to="body">
      <div v-if="modalOpen" class="fixed inset-0 z-[100] flex items-center justify-center p-6 bg-black/50" @click.self="closeModal">
        <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] shadow-2xl w-full max-w-5xl h-[80vh] flex flex-col overflow-hidden">
          <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--border-light)] gap-3">
            <div class="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2 min-w-0">
              <slot name="title" />
            </div>
            <button @click="closeModal" class="size-8 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center justify-center flex-shrink-0" title="关闭">
              <X :size="15" />
            </button>
          </div>
          <div class="flex-1 p-4 min-h-0">
            <v-chart :option="option" :autoresize="true" class="w-full h-full" />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue';
import { Maximize2, X } from 'lucide-vue-next';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart, BarChart, ScatterChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import type { EChartsOption } from 'echarts';

use([CanvasRenderer, LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent]);

withDefaults(
  defineProps<{
    option: EChartsOption;
    height?: number;
    description?: string;
    hasData?: boolean;
    emptyText?: string;
  }>(),
  { height: 180, hasData: true, emptyText: '暂无数据' },
);

const modalOpen = ref(false);
const openModal = () => { modalOpen.value = true; };
const closeModal = () => { modalOpen.value = false; };

const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeModal(); };
watch(modalOpen, (open) => {
  if (open) window.addEventListener('keydown', onKey);
  else window.removeEventListener('keydown', onKey);
});
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));
</script>
