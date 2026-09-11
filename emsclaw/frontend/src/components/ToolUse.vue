<template>
  <p v-if="tool.name === 'message' && tool.args?.text" class="text-[var(--text-secondary)] text-[14px] overflow-hidden text-ellipsis whitespace-pre-line pl-1">
    {{ tool.args.text }}
  </p>
  <div v-else-if="toolInfo" class="tool-use-card flex flex-col w-full max-w-full">
    <div class="flex items-center group/tool gap-1.5 w-full max-w-full">
      <div
        @click="handleClick"
        class="flex items-center gap-2.5 px-2.5 py-2 rounded-xl transition-all duration-200 cursor-pointer min-w-0 flex-1 border border-transparent hover:border-gray-100 dark:hover:border-gray-700/50 hover:bg-white dark:hover:bg-gray-800/60 hover:shadow-sm"
      >
        <!-- Icon -->
        <div class="flex-shrink-0 size-7 rounded-lg flex items-center justify-center text-sm transition-colors"
          :class="tool.status === 'calling'
            ? 'bg-blue-50 dark:bg-blue-900/30'
            : 'bg-gray-50 dark:bg-gray-800'">
          <span v-if="tool.delegated_to" class="leading-none">🤖</span>
          <span v-else-if="toolMetaIcon" class="leading-none">{{ toolMetaIcon }}</span>
          <div v-else-if="tool.status === 'calling'" class="relative size-3.5">
            <div class="absolute inset-0 rounded-full border-[1.5px] border-blue-200 dark:border-blue-800"></div>
            <div class="absolute inset-0 rounded-full border-[1.5px] border-blue-500 border-t-transparent animate-spin"></div>
          </div>
          <component :is="toolInfo.icon" :size="13" v-else class="text-gray-400 dark:text-gray-500" />
        </div>

        <!-- Loading spinner when calling (alongside emoji icon) -->
        <div v-if="tool.status === 'calling' && (toolMetaIcon || tool.delegated_to)" class="relative size-3 flex-shrink-0">
          <div class="absolute inset-0 rounded-full border-[1.5px] border-blue-200 dark:border-blue-800"></div>
          <div class="absolute inset-0 rounded-full border-[1.5px] border-blue-500 border-t-transparent animate-spin"></div>
        </div>

        <!-- Content -->
        <div class="flex items-center gap-2 min-w-0 flex-1 text-xs font-mono">
          <span class="text-gray-700 dark:text-gray-200 font-semibold flex-shrink-0">{{ toolInfo.function }}</span>
          <!-- Sub-agent delegation badge -->
          <span v-if="tool.delegated_to"
            class="flex-shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 border border-indigo-200/40 dark:border-indigo-800/30">
            🤖 → {{ tool.delegated_to }}
          </span>
          <span v-if="toolInfo.functionArg" class="text-gray-400 dark:text-gray-500 truncate bg-gray-50 dark:bg-gray-800/80 px-1.5 py-0.5 rounded-md border border-gray-100 dark:border-gray-700/50 max-w-full">
            {{ toolInfo.functionArg }}
          </span>
        </div>

        <!-- Duration badge -->
        <span v-if="tool.duration_ms != null && tool.status === 'called'"
          class="flex-shrink-0 text-[10px] font-bold font-mono px-2 py-0.5 rounded-md tabular-nums bg-gradient-to-r from-emerald-50 to-teal-50 dark:from-emerald-900/20 dark:to-teal-900/15 text-emerald-600 dark:text-emerald-400 border border-emerald-200/40 dark:border-emerald-800/30">
          {{ formatDuration(tool.duration_ms) }}
        </span>
      </div>

      <!-- Expand/collapse toggle -->
      <button
        v-if="tool.status === 'called' && (hasArgs || hasResult)"
        @click.stop="toggleExpand"
        class="flex-shrink-0 size-6 flex items-center justify-center rounded-md text-gray-300 dark:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-500 dark:hover:text-gray-300 transition-colors"
        :title="expanded ? '折叠' : '展开详情'"
      >
        <svg class="size-3.5 transition-transform duration-200" :class="{ 'rotate-90': expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      <!-- Timestamp -->
      <div class="flex-shrink-0 text-[10px] text-gray-300 dark:text-gray-600 opacity-0 group-hover/tool:opacity-100 transition-opacity duration-200 font-mono tabular-nums">
        {{ relativeTime(tool.timestamp) }}
      </div>
    </div>

    <!-- Expandable detail panel -->
    <Transition name="tool-detail">
      <div v-if="expanded" class="mt-1 ml-10 mr-2 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50/60 dark:bg-gray-900/40 overflow-hidden">
        <div v-if="hasArgs" class="border-b border-gray-100 dark:border-gray-800 last:border-b-0">
          <div class="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 bg-gray-50/80 dark:bg-gray-900/60">参数</div>
          <pre class="px-3 py-2 text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all">{{ formatJson(tool.args) }}</pre>
        </div>
        <div v-if="hasResult">
          <div class="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 bg-gray-50/80 dark:bg-gray-900/60">结果</div>
          <pre class="px-3 py-2 text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all max-h-64 overflow-auto">{{ formatJson(tool.content) }}</pre>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { ToolContent } from "../types/message";
import { useToolInfo } from "../composables/useTool";
import { useRelativeTime } from "../composables/useTime";

const props = defineProps<{
  tool: ToolContent;
}>();

const emit = defineEmits<{
  (e: "click"): void;
}>();

const { relativeTime } = useRelativeTime();
const { toolInfo } = useToolInfo(ref(props.tool));

const toolMetaIcon = computed(() => props.tool.tool_meta?.icon || '');

// 展开/折叠状态 —— 每个工具卡片独立
const expanded = ref(false);
const toggleExpand = () => {
  // 仅在已有详情可看时才切换（调用中或无参数无结果不展开）
  if (props.tool.status === 'calling') return;
  if (!hasArgs.value && !hasResult.value) return;
  expanded.value = !expanded.value;
};

// 点击卡片主体 → 通知父组件（打开右侧 ToolPanel 详情面板）
const handleClick = () => { emit("click"); };

// 是否有可展示的参数 / 结果
const hasArgs = computed(() => {
  const a = props.tool.args;
  if (a == null) return false;
  if (typeof a === 'object') return Object.keys(a).length > 0;
  return String(a).trim().length > 0;
});
const hasResult = computed(() => {
  const c = props.tool.content;
  if (c == null) return false;
  if (typeof c === 'object') return Object.keys(c).length > 0;
  return String(c).trim().length > 0;
});

// 把任意值格式化为可读字符串（对象走 JSON，字符串原样）
const formatJson = (v: any): string => {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
};

const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
};
</script>

<style scoped>
.tool-detail-enter-active,
.tool-detail-leave-active {
  transition: opacity 0.15s ease, max-height 0.2s ease;
  overflow: hidden;
}
.tool-detail-enter-from,
.tool-detail-leave-to {
  opacity: 0;
  max-height: 0;
}
.tool-detail-enter-to,
.tool-detail-leave-from {
  opacity: 1;
  max-height: 400px;
}
</style>
