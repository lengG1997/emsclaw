<template>
  <div class="space-y-4">
    <!-- 对话摘要：用户问 + Agent 答（折叠） -->
    <div v-if="trace.query || trace.output" class="grid grid-cols-1 gap-2">
      <div v-if="trace.query">
        <div class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wide">用户问</div>
        <div class="text-xs text-[var(--text-primary)] bg-[var(--background-card)] border border-[var(--border-light)] rounded-md p-2.5 leading-relaxed whitespace-pre-wrap max-h-[120px] overflow-y-auto">
          {{ trace.query }}
        </div>
      </div>
      <div v-if="trace.output">
        <button @click="showOutput = !showOutput"
          class="text-[10px] text-[var(--text-tertiary)] mb-1 uppercase tracking-wide hover:text-[var(--text-secondary)] transition-colors flex items-center gap-1">
          Agent 答
          <ChevronRight :size="10" class="transition-transform" :class="{ 'rotate-90': showOutput }" />
        </button>
        <div v-if="showOutput"
          class="text-xs text-[var(--text-primary)] bg-[var(--background-card)] border border-[var(--border-light)] rounded-md p-2.5 leading-relaxed whitespace-pre-wrap max-h-[200px] overflow-y-auto">
          {{ trace.output }}
        </div>
      </div>
    </div>

    <!-- 工具时间轴 -->
    <div v-if="trace.tool_steps && trace.tool_steps.length">
      <ToolStepsTimeline :steps="trace.tool_steps" :all-scores="trace.scores" />
    </div>

    <!-- 评分理由：已评分⇄未评分 -->
    <div v-if="trace.scores.length" class="space-y-3">
      <div class="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide">评分详情</div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <JudgeCommentCard
          v-for="sc in trace.scores"
          :key="sc.id"
          :dim-name="sc.name"
          :score="typeof sc.value === 'number' ? sc.value : 0"
          :comment="sc.comment"
        />
      </div>
    </div>
    <div v-else class="text-xs text-[var(--text-tertiary)] italic py-2">该次 Agent 调用暂无评分</div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { ChevronRight } from 'lucide-vue-next';
import ToolStepsTimeline from './ToolStepsTimeline.vue';
import JudgeCommentCard from './JudgeCommentCard.vue';
import type { LangfuseScoreTrace } from '@/types/langfuse';

defineProps<{
  trace: LangfuseScoreTrace;
}>();

const showOutput = ref(false);
</script>
