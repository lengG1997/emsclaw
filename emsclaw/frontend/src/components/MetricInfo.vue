<template>
  <PopoverRoot v-model:open="open">
    <PopoverTrigger as-child>
      <button
        type="button"
        class="metric-info-trigger inline-flex items-center justify-center size-4 rounded-full text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--background-gray-main)] transition-colors align-middle"
        :aria-label="title"
        @click.stop
      >
        <Info :size="12" />
      </button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        :side-offset="6"
        align="center"
        side="top"
        class="metric-info-content w-72 p-3 rounded-lg bg-[var(--background-card)] border border-[var(--border-main)] shadow-lg text-[var(--text-secondary)] z-[200] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
      >
        <div class="text-xs font-semibold text-[var(--text-primary)] mb-1 flex items-center gap-1.5">
          <Info :size="12" class="text-[#3a6b8c] flex-shrink-0" />
          <span>{{ title }}</span>
        </div>
        <div class="text-[11px] leading-relaxed text-[var(--text-secondary)]">{{ explain }}</div>
        <div v-if="formula" class="text-[10px] mt-1.5 pt-1.5 border-t border-[var(--border-light)] text-[var(--text-tertiary)] font-mono leading-relaxed">{{ formula }}</div>
        <PopoverArrow class="fill-[var(--background-card)]" :width="8" :height="6" />
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { Info } from 'lucide-vue-next';
import {
  PopoverRoot,
  PopoverTrigger,
  PopoverContent,
  PopoverPortal,
  PopoverArrow,
} from 'reka-ui';

defineProps<{
  title: string;
  explain: string;
  formula?: string;
}>();

const open = ref(false);
</script>
