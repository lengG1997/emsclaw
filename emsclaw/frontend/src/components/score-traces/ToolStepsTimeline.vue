<template>
  <div>
    <!-- 折叠态：一行色块 -->
    <div v-if="!expanded" class="flex items-center gap-0.5 flex-wrap cursor-pointer" @click="expanded = true">
      <span
        v-for="(step, si) in steps"
        :key="step.observation_id"
        class="inline-block rounded-sm transition-opacity hover:opacity-80"
        :class="[stepClass(step, si), problemSteps.has(si + 1) ? 'ring-1 ring-red-500/60' : '']"
        :style="{ width: Math.max(4, 100 / steps.length) + '%', minWidth: '6px', height: '4px' }"
        :title="stepTooltip(step, si)"
      ></span>
    </div>

    <!-- 展开态：竖直时间线 -->
    <div v-else class="space-y-0">
      <div class="flex items-center gap-2 mb-2">
        <button @click="expanded = false"
          class="text-[11px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1">
          <ChevronDown :size="12" />
          <span>收起工具调用 ({{ steps.length }} 步)</span>
        </button>
      </div>

      <div v-for="(step, si) in steps" :key="step.observation_id"
        class="relative pl-5 pb-2.5 border-l-2"
        :class="[si < steps.length - 1 ? 'border-[var(--border-light)]' : 'border-transparent', problemSteps.has(si + 1) ? 'bg-red-500/[0.03] -mx-1 px-[calc(1.25rem+4px)] rounded-r' : '']">
        <!-- 圆点：问题步骤红色 + 脉冲 -->
        <div class="absolute left-[-5px] top-1 size-[9px] rounded-full border-2 border-[var(--background-card)]"
          :class="[stepDotClass(step), problemSteps.has(si + 1) ? '!bg-red-500 ring-2 ring-red-500/30' : '']">
        </div>

        <!-- 步骤信息 -->
        <div class="flex items-start gap-2 flex-wrap">
          <span class="text-[10px] font-mono text-[var(--text-tertiary)] w-5 flex-shrink-0">#{{ si + 1 }}</span>
          <span class="text-xs font-medium" :class="problemSteps.has(si + 1) ? 'text-red-300' : 'text-[var(--text-primary)]'">
            {{ toolLabel(step.name) }}
          </span>
          <span v-if="toolStepParamSummary(step)" class="text-[10px] text-[var(--text-tertiary)] truncate max-w-[220px] font-mono" :title="step.input">
            {{ toolStepParamSummary(step) }}
          </span>
          <span v-if="step.latency != null" class="text-[10px] text-[var(--text-disable)] font-mono ml-auto flex-shrink-0">
            {{ step.latency < 0.01 ? (step.latency * 1000).toFixed(0) + 'ms' : step.latency.toFixed(2) + 's' }}
          </span>
        </div>

        <!-- 问题标记 -->
        <div v-if="problemSteps.has(si + 1)" class="mt-1.5 space-y-1">
          <div v-for="mark in problemSteps.get(si + 1)!" :key="mark.dim"
            class="flex items-start gap-1.5 text-[11px] text-red-300/80 bg-red-500/[0.06] rounded px-2 py-1">
            <AlertTriangle :size="11" class="flex-shrink-0 mt-[2px] text-red-400" />
            <span>
              <span class="font-medium text-red-300">{{ dimensionLabel(mark.dim) }}</span>
              <span class="text-red-400/60 mx-1">·</span>
              <span>{{ mark.desc }}</span>
            </span>
          </div>
        </div>

        <!-- 该步骤的维度评分 -->
        <div v-if="step.scores && step.scores.length" class="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span v-for="sc in step.scores" :key="sc.id"
            class="inline-flex items-center gap-0.5 text-[10px]">
            <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="scoreBarClass(sc)"></span>
            <span class="text-[var(--text-tertiary)]">{{ dimensionLabel(sc.name) }}</span>
            <span class="font-semibold tabular-nums" :class="scoreValueClass(sc)">{{ formatScoreValue(sc) }}</span>
          </span>
        </div>
      </div>
    </div>

    <!-- 展开按钮（折叠态） -->
    <button v-if="!expanded && steps.length > 0"
      @click="expanded = true"
      class="flex items-center gap-1 text-[11px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors mt-1">
      <ChevronRight :size="12" />
      <span>展开工具调用 ({{ steps.length }} 步)</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { ChevronRight, ChevronDown, AlertTriangle } from 'lucide-vue-next';
import { dimensionLabel, scoreValueClassFromNum, scoreBarClassFromNum, toolLabel } from '@/utils/scoreLabels';
import { traceProblemSteps } from '@/utils/scoreComments';
import type { ToolCallStep, LangfuseScoreItem } from '@/types/langfuse';

const props = defineProps<{
  steps: ToolCallStep[];
  allScores: LangfuseScoreItem[]; // trace-level scores for problem step extraction
}>();

const expanded = ref(false);

const problemSteps = traceProblemSteps(props.allScores);

function stepDotClass(step: ToolCallStep) {
  const avg = toolStepScoreAvg(step.scores);
  if (avg === null) return 'bg-[var(--border-light)]';
  return scoreBarClassFromNum(avg);
}

function stepClass(step: ToolCallStep, _si: number) {
  const avg = toolStepScoreAvg(step.scores);
  if (avg === null) return 'bg-[var(--border-light)]';
  return scoreBarClassFromNum(avg);
}

function stepTooltip(step: ToolCallStep, si: number): string {
  const parts = [`Step ${si + 1}: ${toolLabel(step.name)}`];
  if (step.latency != null) parts.push(`${(step.latency * 1000).toFixed(0)}ms`);
  if (step.scores.length) parts.push(step.scores.map(s => `${dimensionLabel(s.name)}=${formatScoreValue(s)}`).join(', '));
  return parts.join(' · ');
}

// ── ToolCallStep helpers (mirrored from ScoreTracesPage) ──

function toolStepScoreAvg(scores: LangfuseScoreItem[]): number | null {
  const nums = scores.filter(s => s.data_type === 'NUMERIC' && typeof s.value === 'number').map(s => s.value as number);
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function isNumeric(s: LangfuseScoreItem): boolean {
  return s.data_type === 'NUMERIC' && typeof s.value === 'number';
}

function formatScoreValue(s: LangfuseScoreItem): string {
  if (isNumeric(s)) return (s.value as number).toFixed(2);
  if (s.data_type === 'BOOLEAN') return s.value ? '✓' : '✗';
  if (s.value === null || s.value === undefined) return '—';
  return String(s.value);
}

function scoreValueClass(s: LangfuseScoreItem): string {
  if (!isNumeric(s)) return 'text-[var(--text-secondary)]';
  return scoreValueClassFromNum(s.value as number);
}

function scoreBarClass(s: LangfuseScoreItem): string {
  if (!isNumeric(s)) return 'bg-[var(--border-light)]';
  return scoreBarClassFromNum(s.value as number);
}

function toolStepParamSummary(step: ToolCallStep): string {
  try {
    const obj = typeof step.input === 'string' ? JSON.parse(step.input) : step.input;
    if (!obj || typeof obj !== 'object') return '';
    if (obj.file_path) return String(obj.file_path).split('/').pop() || String(obj.file_path);
    if (obj.command) return String(obj.command).slice(0, 60);
    if (obj.pattern) return String(obj.pattern);
    if (obj.path) return String(obj.path).split('/').pop() || String(obj.path);
    for (const v of Object.values(obj as Record<string, unknown>)) {
      if (v !== null && v !== undefined && String(v).trim()) return String(v).slice(0, 60);
    }
    return '';
  } catch {
    return String(step.input || '').slice(0, 60);
  }
}
</script>
