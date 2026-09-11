<template>
  <div class="my-2 w-full rounded-xl border-2 border-amber-300 dark:border-amber-700/60 bg-amber-50/80 dark:bg-amber-950/20 overflow-hidden">
    <!-- 头部 -->
    <div class="flex items-center gap-2 px-4 py-2.5 bg-amber-100/70 dark:bg-amber-900/30">
      <ShieldAlert class="size-4 text-amber-600 dark:text-amber-400 flex-shrink-0" />
      <span class="text-[13px] font-bold text-amber-700 dark:text-amber-300">{{ t('Approval Required') }}</span>
      <span v-if="resuming" class="ml-auto flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
        <div class="size-3 rounded-full border-2 border-amber-200 dark:border-amber-800 border-t-amber-500 animate-spin"></div>
        {{ t('Resuming...') }}
      </span>
    </div>

    <div class="px-4 py-3 space-y-3">
      <!-- 每个 action_request:工具名 + description + args 预览 -->
      <div v-for="(req, i) in actionRequests" :key="i"
        class="rounded-lg border border-amber-200/70 dark:border-amber-800/40 bg-white/70 dark:bg-gray-900/30 px-3 py-2">
        <div class="flex items-center gap-2">
          <Terminal class="size-3.5 text-amber-600 dark:text-amber-400 flex-shrink-0" />
          <span class="text-[13px] font-semibold text-[var(--text-primary)]">{{ req.name }}</span>
        </div>
        <p v-if="req.description" class="mt-1 text-[11px] text-[var(--text-secondary)]">{{ req.description }}</p>
        <pre v-if="req.args && Object.keys(req.args).length"
          class="mt-1.5 text-[11px] text-[var(--text-tertiary)] whitespace-pre-wrap break-all bg-gray-50 dark:bg-gray-900/50 rounded px-2 py-1 max-h-40 overflow-y-auto">{{ JSON.stringify(req.args, null, 2) }}</pre>
      </div>

      <!-- review_configs 的人读描述 -->
      <div v-for="(rc, i) in reviewConfigs" :key="`rc-${i}`" v-show="rc.description">
        <p class="text-[11px] text-[var(--text-tertiary)] flex items-start gap-1.5">
          <Info class="size-3 flex-shrink-0 mt-px" />
          <span>{{ rc.description }}</span>
        </p>
      </div>

      <!-- 决策按钮(按 allowed_decisions 渲染)-->
      <div class="flex flex-wrap items-center gap-2 pt-1">
        <button v-if="allowedDecisions.includes('approve')" @click="onDecision('approve')" :disabled="resuming"
          class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[13px] font-semibold rounded-lg bg-emerald-500 text-white hover:bg-emerald-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
          <Check class="size-3.5" /> {{ t('Approve') }}
        </button>
        <button v-if="allowedDecisions.includes('reject')" @click="onDecision('reject')" :disabled="resuming"
          class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[13px] font-semibold rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
          <X class="size-3.5" /> {{ t('Reject') }}
        </button>
        <button v-if="allowedDecisions.includes('edit')" @click="onDecision('edit')" :disabled="resuming"
          class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[13px] font-semibold rounded-lg bg-blue-500 text-white hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
          <Edit3 class="size-3.5" /> {{ t('Edit') }}
        </button>
        <button v-if="allowedDecisions.includes('respond')" @click="onDecision('respond')" :disabled="resuming"
          class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[13px] font-semibold rounded-lg bg-blue-500 text-white hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
          <MessageSquare class="size-3.5" /> {{ t('Respond') }}
        </button>

        <!-- 全部自动审批开关 -->
        <button v-if="!autoApprove" @click="$emit('toggle-auto')" :disabled="resuming"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg border border-amber-300 dark:border-amber-700 text-amber-600 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors disabled:opacity-50 ml-auto">
          <Zap class="size-3.5" /> {{ t('Auto-approve all') }}
        </button>
        <span v-else class="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 ml-auto">
          <Zap class="size-3.5" /> {{ t('Auto-approve ON') }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { ShieldAlert, Terminal, Info, Check, X, Edit3, MessageSquare, Zap } from 'lucide-vue-next';
import type { ApprovalEventData } from '../types/event';

const props = defineProps<{
  approval: ApprovalEventData;
  resuming: boolean;
  autoApprove: boolean;
}>();

const emit = defineEmits<{
  (e: 'submit', interruptId: string, decision: string): void;
  (e: 'toggle-auto'): void;
}>();

const { t } = useI18n();

const interruptId = computed(() => props.approval.interrupt_id || '');
const actionRequests = computed(() => props.approval.action_requests || []);
const reviewConfigs = computed(() => props.approval.review_configs || []);

// 允许的决策类型:union of review_configs.allowed_decisions,fallback approve/reject
const allowedDecisions = computed<string[]>(() => {
  const sets = reviewConfigs.value.map(rc => rc.allowed_decisions || []).flat();
  const unique = Array.from(new Set(sets));
  return unique.length > 0 ? unique : ['approve', 'reject'];
});

const onDecision = (decision: string) => {
  if (props.resuming) return;
  emit('submit', interruptId.value, decision);
};
</script>
