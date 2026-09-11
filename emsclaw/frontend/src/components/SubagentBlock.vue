<template>
  <div class="my-2 w-full">
    <!-- 紧凑卡片头:子 agent 名 + 输入 + 状态 -->
    <div
      @click="toggleCollapse"
      class="flex items-center gap-2.5 px-3.5 py-2.5 pr-3 cursor-pointer rounded-xl transition-all duration-200 w-full select-none group border"
      :class="isRunning
        ? 'bg-gradient-to-r from-purple-50/80 to-fuchsia-50/60 dark:from-purple-950/30 dark:to-fuchsia-950/20 border-purple-200/50 dark:border-purple-800/30 shadow-sm hover:shadow-md'
        : 'bg-white dark:bg-gray-800/50 border-gray-100 dark:border-gray-700/50 hover:border-gray-200 dark:hover:border-gray-600 hover:shadow-sm'"
    >
      <!-- 状态图标 -->
      <div v-if="isRunning" class="relative size-4 flex-shrink-0">
        <div class="absolute inset-0 rounded-full border-2 border-purple-200 dark:border-purple-800"></div>
        <div class="absolute inset-0 rounded-full border-2 border-purple-500 border-t-transparent animate-spin"></div>
      </div>
      <div v-else-if="content.status === 'error'" class="size-4 rounded-full bg-red-400 flex items-center justify-center flex-shrink-0">
        <XIcon class="size-2.5 text-white" />
      </div>
      <div v-else class="size-4 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center flex-shrink-0 shadow-sm shadow-emerald-400/30">
        <svg class="size-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="2 6.5 5 9.5 10 3"/></svg>
      </div>

      <!-- 子 agent 头像 + 名 -->
      <div class="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-100 dark:bg-purple-900/40 flex-shrink-0">
        <Bot class="size-4 text-purple-500 dark:text-purple-300" />
      </div>

      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-1.5">
          <span class="text-[13px] font-semibold truncate"
            :class="isRunning ? 'text-purple-600 dark:text-purple-300' : 'text-[var(--text-primary)]'">
            {{ content.name }}
          </span>
          <span class="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/40 text-purple-500 dark:text-purple-300 flex-shrink-0">
            {{ t('Sub-agent') }}
          </span>
        </div>
        <p v-if="content.input" class="text-[11px] text-[var(--text-tertiary)] truncate mt-px">{{ content.input }}</p>
      </div>

      <!-- 工具计数 -->
      <span v-if="content.tools.length > 0"
        class="text-[10px] font-bold px-2 py-0.5 rounded-full tabular-nums flex-shrink-0"
        :class="isRunning
          ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-300'
          : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400'">
        {{ content.tools.length }} {{ content.tools.length === 1 ? t('tool') : t('tools') }}
      </span>

      <ChevronDownIcon
        class="size-3.5 transition-transform duration-300 flex-shrink-0"
        :class="isCollapsed ? 'text-gray-300 dark:text-gray-600' : 'text-gray-400 dark:text-gray-500 rotate-180'" />
    </div>

    <!-- 展开内容:每个过程 section 独立折叠(单独 toggle,互不影响) -->
    <div v-show="!isCollapsed" class="relative ml-2 pl-4 mt-1.5 space-y-1.5">
      <div class="absolute left-0 top-0 bottom-0 w-0.5 rounded-full"
        :class="isRunning ? 'bg-purple-200/60 dark:bg-purple-800/40' : 'bg-gray-200/60 dark:bg-gray-700/40'"></div>

      <!-- ═══ Thinking section(独立折叠) ═══ -->
      <div v-if="content.thinking" class="rounded-lg bg-gray-50 dark:bg-gray-800/40 overflow-hidden">
        <div @click="thinkingFolded = !thinkingFolded"
          class="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-gray-100/60 dark:hover:bg-gray-800/60 transition-colors">
          <ChevronDownIcon class="size-3 text-gray-400 dark:text-gray-500 transition-transform duration-150 flex-shrink-0"
            :class="{ 'rotate-180': !thinkingFolded }" />
          <Lightbulb class="size-3 text-amber-400 flex-shrink-0" />
          <span class="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wide">{{ t('Thinking') }}</span>
          <span v-if="isRunning" class="flex gap-0.5 ml-0.5">
            <span v-for="d in 3" :key="d" class="w-[3px] h-[3px] rounded-full bg-purple-400 animate-bounce-dot"
              :style="{ 'animation-delay': `${(d-1) * 200}ms` }"></span>
          </span>
        </div>
        <div v-show="!thinkingFolded" class="px-3 pb-2 text-[12px] text-[var(--text-secondary)] whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
          {{ content.thinking }}
        </div>
      </div>

      <!-- ═══ Plan / todo section(独立折叠) ═══ -->
      <div v-if="content.plan && content.plan.length > 0" class="rounded-lg bg-gray-50 dark:bg-gray-800/40 overflow-hidden">
        <div @click="planFolded = !planFolded"
          class="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-gray-100/60 dark:hover:bg-gray-800/60 transition-colors">
          <ChevronDownIcon class="size-3 text-gray-400 dark:text-gray-500 transition-transform duration-150 flex-shrink-0"
            :class="{ 'rotate-180': !planFolded }" />
          <ListChecks class="size-3 text-violet-400 flex-shrink-0" />
          <span class="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wide">{{ t('Plan') }}</span>
          <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full tabular-nums bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 flex-shrink-0">
            {{ content.plan.length }}
          </span>
        </div>
        <div v-show="!planFolded" class="px-3 pb-2 space-y-1">
          <div v-for="(step, i) in content.plan" :key="step.id || i" class="flex items-center gap-2 text-[12px]">
            <span class="size-1.5 rounded-full flex-shrink-0"
              :class="step.status === 'completed' ? 'bg-emerald-400' : step.status === 'running' ? 'bg-purple-400' : 'bg-gray-300 dark:bg-gray-600'"></span>
            <span class="text-[var(--text-secondary)] truncate">{{ step.description }}</span>
          </div>
        </div>
      </div>

      <!-- ═══ Tools section(独立折叠) ═══ -->
      <div v-if="content.tools.length > 0" class="rounded-lg bg-gray-50 dark:bg-gray-800/40 overflow-hidden">
        <div @click="toolsFolded = !toolsFolded"
          class="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-gray-100/60 dark:hover:bg-gray-800/60 transition-colors">
          <ChevronDownIcon class="size-3 text-gray-400 dark:text-gray-500 transition-transform duration-150 flex-shrink-0"
            :class="{ 'rotate-180': !toolsFolded }" />
          <Wrench class="size-3 text-purple-400 flex-shrink-0" />
          <span class="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wide">{{ t('Tools') }}</span>
          <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full tabular-nums bg-purple-100 dark:bg-purple-900/40 text-purple-500 dark:text-purple-300 flex-shrink-0">
            {{ content.tools.length }}
          </span>
        </div>
        <div v-show="!toolsFolded" class="px-3 pb-2 space-y-1.5">
          <!-- ── 并发 batch: 整体一个框(淡紫底+边框+圆角+头部状态条) ── -->
          <div v-for="batch in toolBatches" :key="batch.id">
            <div v-if="batch.tools.length > 1"
              class="rounded-lg border border-purple-300 dark:border-purple-700 bg-purple-100/70 dark:bg-purple-950/40 overflow-hidden">
              <!-- batch 头部 -->
              <div class="flex items-center gap-1.5 px-2.5 py-1 border-b border-purple-300/70 dark:border-purple-700/60 bg-purple-200/60 dark:bg-purple-900/50">
                <div v-if="batchStatus(batch) === 'running'" class="relative size-3 flex-shrink-0">
                  <div class="absolute inset-0 rounded-full border-[1.5px] border-purple-300 dark:border-purple-700"></div>
                  <div class="absolute inset-0 rounded-full border-[1.5px] border-purple-600 border-t-transparent animate-spin"></div>
                </div>
                <div v-else class="size-3 rounded-full bg-gradient-to-br from-purple-500 to-fuchsia-600 flex items-center justify-center flex-shrink-0">
                  <svg class="size-1.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="2 6.5 5 9.5 10 3"/></svg>
                </div>
                <span class="text-[10px] font-bold uppercase tracking-wider text-purple-700 dark:text-purple-300 flex items-center gap-1">
                  <svg class="size-2.5" viewBox="0 0 16 16" fill="currentColor"><path d="M3 4h4v4H3V4zm6 0h4v4H9V4zM3 10h4v4H3v-4zm6 0h4v4H9v-4z"/></svg>
                  {{ t('并发') }} ×{{ batch.tools.length }}
                </span>
                <span class="text-[9px] font-semibold text-purple-600 dark:text-purple-400 ml-auto">
                  {{ batchStatus(batch) === 'running' ? t('Running') : t('Done') }}
                </span>
              </div>
              <!-- batch 工具列表 -->
              <div class="flex flex-col divide-y divide-purple-200/60 dark:divide-purple-800/50">
                <div v-for="tool in batch.tools" :key="tool.tool_call_id"
                  class="px-2.5 py-2">
                  <div class="flex items-center gap-2">
                    <div v-if="tool.status === 'calling'" class="size-3 rounded-full border-2 border-purple-200 dark:border-purple-800 border-t-purple-500 animate-spin flex-shrink-0"></div>
                    <div v-else class="size-3 rounded-full bg-emerald-400 flex items-center justify-center flex-shrink-0">
                      <svg class="size-2 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="2 6.5 5 9.5 10 3"/></svg>
                    </div>
                    <span class="text-[12px] font-medium text-[var(--text-primary)] truncate">{{ tool.function }}</span>
                    <span v-if="tool.duration_ms" class="text-[10px] text-[var(--text-tertiary)] ml-auto flex-shrink-0">{{ tool.duration_ms }}ms</span>
                  </div>
                  <pre v-if="tool.args && Object.keys(tool.args).length"
                    class="mt-1 text-[11px] text-[var(--text-tertiary)] whitespace-pre-wrap break-all bg-gray-50 dark:bg-gray-900/40 rounded px-2 py-1 max-h-32 overflow-y-auto">{{ JSON.stringify(tool.args, null, 2) }}</pre>
                  <div v-if="tool.content != null && tool.content !== ''"
                    class="mt-1 text-[11px] text-[var(--text-secondary)] whitespace-pre-wrap break-words bg-gray-50 dark:bg-gray-900/40 rounded px-2 py-1 max-h-40 overflow-y-auto">{{ formatContent(tool.content) }}</div>
                </div>
              </div>
            </div>
            <!-- 单工具 -->
            <div v-else v-for="tool in batch.tools" :key="tool.tool_call_id"
              class="rounded-lg border border-gray-100 dark:border-gray-700/50 bg-white dark:bg-gray-800/40 px-3 py-2">
              <div class="flex items-center gap-2">
                <div v-if="tool.status === 'calling'" class="size-3 rounded-full border-2 border-purple-200 dark:border-purple-800 border-t-purple-500 animate-spin flex-shrink-0"></div>
                <div v-else class="size-3 rounded-full bg-emerald-400 flex items-center justify-center flex-shrink-0">
                  <svg class="size-2 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="2 6.5 5 9.5 10 3"/></svg>
                </div>
                <span class="text-[12px] font-medium text-[var(--text-primary)] truncate">{{ tool.function }}</span>
                <span v-if="tool.duration_ms" class="text-[10px] text-[var(--text-tertiary)] ml-auto flex-shrink-0">{{ tool.duration_ms }}ms</span>
              </div>
              <pre v-if="tool.args && Object.keys(tool.args).length"
                class="mt-1 text-[11px] text-[var(--text-tertiary)] whitespace-pre-wrap break-all bg-gray-50 dark:bg-gray-900/40 rounded px-2 py-1 max-h-32 overflow-y-auto">{{ JSON.stringify(tool.args, null, 2) }}</pre>
              <div v-if="tool.content != null && tool.content !== ''"
                class="mt-1 text-[11px] text-[var(--text-secondary)] whitespace-pre-wrap break-words bg-gray-50 dark:bg-gray-900/40 rounded px-2 py-1 max-h-40 overflow-y-auto">{{ formatContent(tool.content) }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输出(常显,子 agent 结果直接给人看) -->
      <div v-if="content.result" class="rounded-lg border border-emerald-100 dark:border-emerald-800/30 bg-emerald-50/50 dark:bg-emerald-950/20 px-3 py-2">
        <div class="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 mb-1 uppercase tracking-wide">{{ t('Result') }}</div>
        <div class="text-[12px] text-[var(--text-secondary)] whitespace-pre-wrap break-words max-h-60 overflow-y-auto">{{ content.result }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { Bot, ChevronDown as ChevronDownIcon, X as XIcon, Lightbulb, Wrench, ListChecks } from 'lucide-vue-next';
import type { Message, SubagentContent, ToolContent } from '../types/message';

const props = defineProps<{ message: Message }>();
const { t } = useI18n();

// 顶层折叠(整块内容区收起/展开)
const isCollapsed = ref(false);
const toggleCollapse = () => { isCollapsed.value = !isCollapsed.value; };

// 每个 process section 独立折叠(默认收起,点开看细节;互不影响)
const thinkingFolded = ref(true);
const toolsFolded = ref(true);
const planFolded = ref(true);

const content = computed(() => props.message.content as SubagentContent);
const isRunning = computed(() => content.value.status === 'running');

// 按 batch_id 分组工具:同一次 LLM 响应派生的并发 tool_call 共享 batch_id,
// 同组并排渲染并显示「并发 ×N」标识;无 batch_id 的工具各自成组(保持顺序)。
const toolBatches = computed(() => {
  const batches: { id: string; tools: ToolContent[] }[] = [];
  for (const tool of content.value.tools) {
    const bid = (tool as any).batch_id as string | undefined;
    const last = batches[batches.length - 1];
    if (bid && last && last.id === `batch:${bid}`) {
      last.tools.push(tool);
    } else {
      batches.push({ id: bid ? `batch:${bid}` : `solo:${tool.tool_call_id}`, tools: [tool] });
    }
  }
  return batches;
});

// 并发 batch 整体状态:任一 calling → running; 全部 called → done。
const batchStatus = (batch: { tools: ToolContent[] }): 'running' | 'done' => {
  if (batch.tools.some(t => t.status === 'calling')) return 'running';
  return 'done';
};

const formatContent = (c: ToolContent['content']): string => {
  if (c == null) return '';
  if (typeof c === 'string') return c;
  try { return JSON.stringify(c, null, 2); } catch (_) { return String(c); }
};
</script>
