<template>
  <div class="flex flex-col items-center gap-3 select-none">
    <div class="text-[13px] font-semibold text-[var(--text-secondary)]">用一句话告诉我你的用电场景,我来出策略</div>
    <!-- 上面一行:2 张操作类卡片 -->
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2.5 w-full">
      <button
        v-for="c in topCards"
        :key="c.key"
        @click="$emit('select', c.prompt)"
        class="group rounded-xl border border-[var(--border-main)] bg-[var(--background-card)] p-3 text-left transition-all duration-150 cursor-pointer hover:-translate-y-0.5 hover:shadow-[0_4px_14px_rgba(0,0,0,0.08)]"
      >
        <div class="flex items-center gap-2">
          <span class="size-8 rounded-lg inline-flex items-center justify-center" :style="{ background: c.bg, color: c.color }">
            <component :is="c.icon" :size="16" />
          </span>
          <span class="text-[13px] font-semibold text-[var(--text-primary)]">{{ c.label }}</span>
        </div>
        <div class="mt-2 text-[11px] leading-relaxed text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)]">
          {{ c.desc }}
        </div>
      </button>
    </div>
    <!-- 下面一行:日常用电场景卡片 -->
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2.5 w-full">
      <button
        v-for="c in bottomCards"
        :key="c.key"
        @click="$emit('select', c.prompt)"
        class="group rounded-xl border border-[var(--border-main)] bg-[var(--background-card)] p-3 text-left transition-all duration-150 cursor-pointer hover:-translate-y-0.5 hover:shadow-[0_4px_14px_rgba(0,0,0,0.08)]"
      >
        <div class="flex items-center gap-2">
          <span class="size-8 rounded-lg inline-flex items-center justify-center" :style="{ background: c.bg, color: c.color }">
            <component :is="c.icon" :size="16" />
          </span>
          <span class="text-[13px] font-semibold text-[var(--text-primary)]">{{ c.label }}</span>
        </div>
        <div class="mt-2 text-[11px] leading-relaxed text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)]">
          {{ c.desc }}
        </div>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { RotateCcw, Cpu, BarChart3, Factory, PiggyBank, Sun, BatteryCharging, Gauge, ClipboardCheck } from 'lucide-vue-next';

defineEmits<{ select: [prompt: string] }>();

const topCards = [
  {
    key: 'reset_station',
    label: '重置场站',
    icon: RotateCcw,
    bg: '#6366f114',
    color: '#6366f1',
    desc: '清除设备与调度,恢复初始',
    prompt: '请帮我重置场站,清除所有设备数据和调度计划,恢复到初始状态。',
  },
  {
    key: 'add_pcs_bms',
    label: '新增PCS/BMS',
    icon: Cpu,
    bg: '#f59e0b14',
    color: '#f59e0b',
    desc: '添加变流器与电池管理设备',
    prompt: '请帮我新增一套PCS和BMS设备,配置设备参数、通信地址和挂载关系。',
  },
  {
    key: 'station_analysis',
    label: '场站分析',
    icon: BarChart3,
    bg: '#10b98114',
    color: '#10b981',
    desc: '分析运行数据、SOC与收益',
    prompt: '请帮我分析当前场站的运行数据,包括储能SOC、光伏出力、负荷曲线和收益情况。',
  },
];

const bottomCards = [
  {
    key: 'production_priority',
    label: '赶产保供',
    icon: Factory,
    bg: '#e85d2a14',
    color: '#e85d2a',
    desc: '订单多、负荷大,保生产用电不断',
    prompt: '明天产线订单多、负荷大,帮我生成充放电策略,优先保证生产用电不断,关口表需量别超过申报值。',
  },
  {
    key: 'save_money',
    label: '峰谷省钱',
    icon: PiggyBank,
    bg: '#3a6b8c14',
    color: '#3a6b8c',
    desc: '低谷充电、高峰放电,降电费',
    prompt: '帮我优化明天的充放电,低谷充电、高峰放电,把电费降到最低。',
  },
  {
    key: 'pv_consume',
    label: '光伏消纳',
    icon: Sun,
    bg: '#4c8a5a14',
    color: '#4c8a5a',
    desc: '晴天多发,尽量消纳、别上网',
    prompt: '明天晴天光伏大发,帮我尽量消纳光伏、少弃光,并控制不向电网反送电。',
  },
  {
    key: 'battery_life',
    label: '保电池延寿',
    icon: BatteryCharging,
    bg: '#6b8e4e14',
    color: '#6b8e4e',
    desc: '少循环,延长电池寿命',
    prompt: '这段时间少折腾电池,帮我生成少循环的充放电策略,延长电池寿命。',
  },
  {
    key: 'demand_cap',
    label: '压需量',
    icon: Gauge,
    bg: '#8b5cf614',
    color: '#8b5cf6',
    desc: '需量快超标,压下来别罚款',
    prompt: '最近关口表需量快超标了,帮我生成充放电策略把需量压下来,别被罚款。',
  },
  {
    key: 'execution_check',
    label: '执行检查',
    icon: ClipboardCheck,
    bg: '#0ea5e914',
    color: '#0ea5e9',
    desc: '今天的计划执行得怎么样',
    prompt: '今天的充放电计划执行得怎么样,有没有跟计划的偏差?',
  },
];
</script>
