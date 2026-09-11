<template>
  <div class="bg-[var(--background-card)] rounded-lg border overflow-hidden" :class="borderClass">
    <!-- 头部：维度名 + 分值 -->
    <div class="flex items-center justify-between px-4 py-2.5 border-b" :class="headerBorderClass">
      <span class="text-sm font-semibold text-[var(--text-primary)]">{{ dimensionLabel(dimName) }}</span>
      <span class="text-lg font-bold tabular-nums" :class="scoreValueClassFromNum(score)">{{ score.toFixed(0) }}</span>
    </div>

    <!-- 结构化段 -->
    <div class="px-4 py-3 space-y-3">
      <div v-for="sec in sections" :key="sec.type + sec.title" class="space-y-1.5">
        <!-- 段标题 -->
        <div class="flex items-center gap-1.5">
          <component :is="secIcon(sec.type)" :size="13" :class="secIconColor(sec.type)" />
          <span class="text-xs font-semibold" :class="secTitleClass(sec.type)">{{ sec.title }}</span>
        </div>
        <!-- 条目 -->
        <ul class="space-y-1">
          <li v-for="(item, i) in sec.items" :key="i" class="text-xs leading-relaxed pl-5 relative"
            :class="secItemClass(sec.type)">
            <span class="absolute left-1.5 top-[7px] w-1 h-1 rounded-full" :class="secBulletClass(sec.type)"></span>
            <!-- 问题工具段：高亮 #N -->
            <span v-if="sec.type === 'problems'">
              <span v-for="(part, pi) in highlightSteps(item)" :key="pi">
                <span v-if="part.ref" class="inline-flex items-center gap-0.5 px-1 py-px rounded font-mono text-[10px]"
                  :class="highlightPillClass(part.ref)">
                  #{{ part.ref }}
                </span>
                <span v-else>{{ part.text }}</span>
              </span>
            </span>
            <span v-else>{{ item }}</span>
          </li>
        </ul>
      </div>

      <!-- 无结构化内容时显示原文 -->
      <div v-if="!sections.length && raw" class="text-xs text-[var(--text-secondary)] leading-relaxed">{{ raw }}</div>
      <div v-if="!sections.length && !raw" class="text-xs text-[var(--text-tertiary)] italic">(无评分理由)</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ThumbsUp, AlertTriangle, Lightbulb, Star, FileText } from 'lucide-vue-next';
import { dimensionLabel, scoreValueClassFromNum } from '@/utils/scoreLabels';
import { parseJudgeComment, type CommentSection } from '@/utils/scoreComments';

const props = defineProps<{
  dimName: string;
  score: number; // 1-5
  comment?: string | null;
}>();

const parsed = computed(() => parseJudgeComment(props.comment));
const sections = computed(() => parsed.value.sections.filter(s => s.type !== 'score' && s.type !== 'other'));
const raw = computed(() => parsed.value.raw);

const borderClass = computed(() => {
  const n = props.score / 5;
  if (n >= 0.8) return 'border-emerald-500/20';
  if (n >= 0.5) return 'border-amber-500/20';
  return 'border-red-500/20';
});
const headerBorderClass = computed(() => {
  const n = props.score / 5;
  if (n >= 0.8) return 'border-emerald-500/10';
  if (n >= 0.5) return 'border-amber-500/10';
  return 'border-red-500/10';
});

function secIcon(type: CommentSection['type']) {
  const map: Record<string, any> = { strengths: ThumbsUp, problems: AlertTriangle, suggestions: Lightbulb, score: Star };
  return map[type] || FileText;
}
function secIconColor(type: CommentSection['type']) {
  const map: Record<string, string> = { strengths: 'text-emerald-400', problems: 'text-red-400', suggestions: 'text-amber-400', score: 'text-blue-400' };
  return map[type] || 'text-[var(--text-tertiary)]';
}
function secTitleClass(type: CommentSection['type']) {
  const map: Record<string, string> = { strengths: 'text-emerald-300', problems: 'text-red-300', suggestions: 'text-amber-300', score: 'text-blue-300' };
  return map[type] || 'text-[var(--text-secondary)]';
}
function secBulletClass(type: CommentSection['type']) {
  const map: Record<string, string> = { strengths: 'bg-emerald-400', problems: 'bg-red-400', suggestions: 'bg-amber-400', score: 'bg-blue-400' };
  return map[type] || 'bg-[var(--text-tertiary)]';
}
function secItemClass(type: CommentSection['type']) {
  if (type === 'problems') return 'text-red-200/80';
  return 'text-[var(--text-secondary)]';
}

// ── 问题步骤高亮 ──
interface TextPart { text: string; ref?: number }

function highlightSteps(item: string): TextPart[] {
  const parts: TextPart[] = [];
  const re = /#(\d+)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(item)) !== null) {
    if (m.index > last) parts.push({ text: item.slice(last, m.index) });
    parts.push({ text: m[0], ref: Number(m[1]) });
    last = m.index + m[0].length;
  }
  if (last < item.length) parts.push({ text: item.slice(last) });
  return parts;
}

function highlightPillClass(stepNum: number) {
  // 使用不同的微妙色调区分不同步骤
  const hues = ['bg-red-500/15 text-red-300', 'bg-orange-500/15 text-orange-300', 'bg-amber-500/15 text-amber-300'];
  return hues[(stepNum - 1) % hues.length];
}
</script>
