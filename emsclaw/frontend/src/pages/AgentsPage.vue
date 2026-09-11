<template>
  <div class="flex flex-col h-full w-full overflow-hidden agents-page">
    <!-- Hero Header -->
    <div class="flex-shrink-0 relative overflow-hidden">
      <div class="absolute inset-0 bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-700"></div>
      <div class="relative px-6 py-5">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-xl font-bold text-white flex items-center gap-2">
              <span class="inline-flex items-center justify-center size-8 rounded-lg bg-white/15 backdrop-blur-sm">
                <Bot class="size-4 text-white" />
              </span>
              智能体
            </h1>
            <p class="text-white/60 text-xs mt-1">
              {{ agents.length }} 个 agent · 父子结构（Lead 协调 + 领域子 agent）· 提示词已交 Langfuse 版本化管理
            </p>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="langfuseEnabled" class="text-[11px] px-2.5 py-1 rounded-full bg-emerald-400/20 text-emerald-100 border border-emerald-300/30 flex items-center gap-1">
              <span class="size-1.5 rounded-full bg-emerald-300"></span> Langfuse 已启用
            </span>
            <span v-else class="text-[11px] px-2.5 py-1 rounded-full bg-white/10 text-white/60 border border-white/10">Langfuse 未启用</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Body: master-detail -->
    <div class="flex-1 flex overflow-hidden bg-[#f8f9fb] dark:bg-[#111]">
      <!-- Left: agent list -->
      <div class="w-60 flex-shrink-0 border-r border-gray-100 dark:border-gray-800 overflow-y-auto bg-white/60 dark:bg-[#161616]/60">
        <div v-if="loading" class="p-4 space-y-2">
          <div v-for="i in 8" :key="i" class="h-14 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse"></div>
        </div>
        <div v-else class="p-2.5 space-y-1">
          <button
            v-for="a in agents" :key="a.name"
            @click="selected = a"
            class="w-full text-left rounded-xl px-3 py-2.5 transition-all duration-200"
            :class="selected?.name === a.name
              ? 'bg-gradient-to-br from-indigo-500/10 to-violet-500/10 dark:from-indigo-500/20 dark:to-violet-500/20 ring-1 ring-indigo-400/30'
              : 'hover:bg-gray-100 dark:hover:bg-gray-800/60'"
          >
            <div class="flex items-center gap-2.5">
              <div class="size-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0 shadow-sm"
                :style="{ background: getGradient(a.name) }">
                {{ a.kind === 'lead' ? 'L' : a.name.charAt(0) }}
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="text-sm font-semibold text-[var(--text-primary)] truncate">{{ a.label }}</span>
                  <span v-if="a.kind === 'lead'" class="text-[9px] px-1.5 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300 font-medium">Lead</span>
                </div>
                <div class="flex items-center gap-2 mt-0.5 text-[10px] text-[var(--text-tertiary)]">
                  <span class="flex items-center gap-0.5"><Wrench :size="10" />{{ a.tools.length }}</span>
                  <span class="flex items-center gap-0.5"><Blocks :size="10" />{{ a.skills.length }}</span>
                  <span v-if="Object.keys(a.interrupt_on).length" class="flex items-center gap-0.5 text-amber-500"><ShieldCheck :size="10" />{{ Object.keys(a.interrupt_on).length }}</span>
                </div>
              </div>
            </div>
          </button>
        </div>
      </div>

      <!-- Right: detail -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="!selected" class="h-full flex flex-col items-center justify-center text-[var(--text-tertiary)] gap-3">
          <Bot :size="40" class="text-gray-300 dark:text-gray-600" />
          <span class="text-sm">选择左侧的 agent 查看详情</span>
        </div>
        <div v-else class="max-w-5xl mx-auto p-6 space-y-6">
          <!-- 概述 -->
          <section>
            <div class="flex items-start gap-3">
              <div class="size-11 rounded-xl flex items-center justify-center text-white text-sm font-bold flex-shrink-0 shadow-md"
                :style="{ background: getGradient(selected.name) }">
                {{ selected.kind === 'lead' ? 'L' : selected.name.charAt(0) }}
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                  <h2 class="text-lg font-bold text-[var(--text-primary)]">{{ selected.label }}</h2>
                  <span :class="selected.kind === 'lead' ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300' : 'bg-violet-100 dark:bg-violet-900/40 text-violet-600 dark:text-violet-300'"
                    class="text-[10px] px-2 py-0.5 rounded-full font-medium">
                    {{ selected.kind === 'lead' ? '父 Agent · Lead' : '领域子 Agent' }}
                  </span>
                </div>
                <p class="text-sm text-[var(--text-secondary)] mt-1.5 leading-relaxed">{{ selected.description }}</p>
                <div class="flex items-center gap-2 mt-2.5 flex-wrap text-[11px]">
                  <span class="px-2 py-1 rounded-md bg-gray-100 dark:bg-gray-800 text-[var(--text-tertiary)] font-mono flex items-center gap-1">
                    <FileText :size="11" /> 提示词: {{ selected.prompt_name || '-' }}
                  </span>
                  <span v-if="langfuseEnabled" class="px-2 py-1 rounded-md bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                    <span class="size-1.5 rounded-full bg-emerald-400"></span> Langfuse 版本化
                  </span>
                  <span v-if="selected.prompt_is_template" class="px-2 py-1 rounded-md bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400">模板（运行时注入）</span>
                </div>
              </div>
            </div>
          </section>

          <!-- Lead 子 agent 名单 -->
          <section v-if="selected.subagents && selected.subagents.length">
            <SectionTitle icon="users" title="可分派的子 Agent" :count="selected.subagents.length" />
            <div class="flex flex-wrap gap-1.5">
              <span v-for="s in selected.subagents" :key="s"
                class="text-[11px] px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 text-[var(--text-secondary)] font-mono">{{ s }}</span>
            </div>
          </section>

          <!-- 提示词 -->
          <section>
            <SectionTitle icon="prompt" title="提示词" />
            <div class="rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] overflow-hidden">
              <div class="px-3 py-2 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between bg-gray-50/50 dark:bg-gray-900/30">
                <span class="text-[11px] text-[var(--text-tertiary)] font-mono">{{ selected.prompt_name }}</span>
                <span class="text-[10px] text-[var(--text-tertiary)]">{{ selected.prompt.length }} 字符</span>
              </div>
              <pre class="p-4 text-xs leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap break-words max-h-[420px] overflow-y-auto font-mono">{{ selected.prompt || '（无提示词）' }}</pre>
            </div>
          </section>

          <!-- 工具 -->
          <section>
            <SectionTitle icon="tool" title="工具" :count="selected.tools.length" />
            <div v-if="!selected.tools.length" class="text-xs text-[var(--text-tertiary)] py-2">{{ selected.kind === 'lead' ? 'Lead 自身不挂业务工具，靠 task 工具分派子 agent。' : '无工具' }}</div>
            <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div v-for="t in selected.tools" :key="t.name"
                class="rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-[#1e1e1e] p-3.5">
                <div class="flex items-center gap-2 mb-1.5">
                  <div class="size-7 rounded-lg flex items-center justify-center text-white flex-shrink-0" :style="{ background: getGradient(t.name) }">
                    <Wrench :size="13" />
                  </div>
                  <h4 class="text-sm font-semibold text-[var(--text-primary)] font-mono">{{ t.name }}</h4>
                  <ShieldCheck v-if="selected.interrupt_on[t.name]" :size="13" class="text-amber-500 ml-auto" />
                </div>
                <p class="text-xs text-[var(--text-secondary)] leading-relaxed mb-2">{{ t.description || '无描述' }}</p>
                <div v-if="Object.keys(t.args).length" class="flex flex-wrap gap-1">
                  <span v-for="(schema, key) in t.args" :key="key"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[var(--text-tertiary)] font-mono">
                    {{ key }}<span v-if="schema?.type" class="opacity-50">: {{ schema.type }}</span>
                  </span>
                </div>
              </div>
            </div>
          </section>

          <!-- 技能 -->
          <section>
            <SectionTitle icon="skill" title="技能" :count="selected.skills.length" />
            <div v-if="!selected.skills.length" class="text-xs text-[var(--text-tertiary)] py-2">无技能</div>
            <div v-else class="space-y-2.5">
              <div v-for="s in selected.skills" :key="s.name"
                class="rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-[#1e1e1e] p-3.5">
                <div class="flex items-center gap-2 mb-1">
                  <Blocks :size="14" class="text-violet-500 flex-shrink-0" />
                  <h4 class="text-sm font-semibold text-[var(--text-primary)]">{{ s.name }}</h4>
                </div>
                <p class="text-xs text-[var(--text-secondary)] leading-relaxed mb-2">{{ s.description || '无描述' }}</p>
                <div v-if="s.files.length" class="flex flex-wrap gap-1">
                  <span v-for="f in s.files.slice(0, 12)" :key="f"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[var(--text-tertiary)] font-mono truncate max-w-[200px]">{{ f }}</span>
                  <span v-if="s.files.length > 12" class="text-[10px] text-[var(--text-tertiary)] self-center">+{{ s.files.length - 12 }}</span>
                </div>
              </div>
            </div>
          </section>

          <!-- 审批工具 -->
          <section v-if="Object.keys(selected.interrupt_on).length">
            <SectionTitle icon="shield" title="需审批工具（HITL）" :count="Object.keys(selected.interrupt_on).length" />
            <div class="space-y-2">
              <div v-for="(cfg, name) in selected.interrupt_on" :key="name"
                class="rounded-lg border border-amber-200/60 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-900/10 px-3 py-2 flex items-center gap-2">
                <ShieldCheck :size="14" class="text-amber-500 flex-shrink-0" />
                <span class="text-sm font-mono font-semibold text-[var(--text-primary)]">{{ name }}</span>
                <span v-if="cfg?.description" class="text-xs text-[var(--text-tertiary)]">- {{ cfg.description }}</span>
                <div v-if="cfg?.allowed_decisions?.length" class="ml-auto flex gap-1">
                  <span v-for="d in cfg.allowed_decisions" :key="d"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-gray-800 text-amber-600 dark:text-amber-400 font-medium">{{ d }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, defineComponent } from 'vue';
import type { Component } from 'vue';
import { Bot, Wrench, Blocks, ShieldCheck, FileText, Info, Users } from 'lucide-vue-next';
import { getAgents } from '../api/agent';
import type { AgentInfo, AgentRoster } from '../types/response';

const agents = ref<AgentInfo[]>([]);
const langfuseEnabled = ref(false);
const loading = ref(true);
const selected = ref<AgentInfo | null>(null);

const gradientPalette = [
  'linear-gradient(135deg, #6366f1, #8b5cf6)',
  'linear-gradient(135deg, #3b82f6, #6366f1)',
  'linear-gradient(135deg, #06b6d4, #3b82f6)',
  'linear-gradient(135deg, #10b981, #06b6d4)',
  'linear-gradient(135deg, #f59e0b, #ef4444)',
  'linear-gradient(135deg, #ec4899, #8b5cf6)',
  'linear-gradient(135deg, #14b8a6, #22c55e)',
  'linear-gradient(135deg, #f97316, #f59e0b)',
];
const getGradient = (name: string) => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return gradientPalette[Math.abs(hash) % gradientPalette.length];
};

const load = async () => {
  loading.value = true;
  try {
    const roster: AgentRoster = await getAgents();
    agents.value = roster.agents;
    langfuseEnabled.value = roster.langfuse_enabled;
    if (!selected.value && agents.value.length) selected.value = agents.value[0];
  } catch (e) {
    console.error('Failed to load agents', e);
  } finally {
    loading.value = false;
  }
};
onMounted(load);

// 局部小组件：分节标题（图标 + 标题 + 计数 + 分割线）
const _iconMap: Record<string, Component> = { tool: Wrench, skill: Blocks, shield: ShieldCheck, prompt: FileText, users: Users };
const SectionTitle = defineComponent({
  name: 'SectionTitle',
  props: {
    icon: { type: String, default: 'tool' },
    title: { type: String, required: true },
    count: { type: Number, default: undefined },
  },
  setup(props) {
    return () => h('div', { class: 'flex items-center gap-2 mb-3' }, [
      h(_iconMap[props.icon] || Wrench, { size: 14, class: 'text-[var(--text-tertiary)]' }),
      h('h3', { class: 'text-xs font-semibold text-[var(--text-secondary)] tracking-wide' }, props.title),
      props.count !== undefined
        ? h('span', { class: 'text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-[var(--text-tertiary)]' }, String(props.count))
        : null,
      h('div', { class: 'flex-1 h-px bg-gray-100 dark:bg-gray-800' }),
    ]);
  },
});
</script>

<style scoped>
.agents-page :deep(pre) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
</style>
