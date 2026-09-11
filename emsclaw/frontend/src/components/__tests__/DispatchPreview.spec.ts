import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';

// 桩掉 echarts 渲染(jsdom 无 canvas),只验证组件自身的数字卡/标题/图表容器契约。
vi.mock('vue-echarts', () => ({
  default: defineComponent({
    name: 'VChart',
    props: { option: Object, autoresize: Boolean },
    setup: () => () => h('div', { class: 'v-chart-mock' }),
  }),
}));
vi.mock('echarts/core', () => ({ use: vi.fn() }));

import DispatchPreview from '../DispatchPreview.vue';

function makeSchedule() {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    mode: (i < 8 ? 'charge' : i < 16 ? 'discharge' : 'standby') as 'charge' | 'discharge' | 'standby',
    power_kw: 100 + i,
    soc_target_pct: 0.5 + i * 0.01,
    period: i < 8 ? '谷' : i < 16 ? '峰' : '平',
  }));
}

const summary = {
  est_savings_yuan: 1234.5,
  charge_kwh: 900,
  discharge_kwh: 800,
  green_rate: 0.65,
  peak_demand_kw: 456,
};

describe('DispatchPreview', () => {
  it('渲染标题、策略组合、关键数字卡与图表容器', () => {
    const wrapper = mount(DispatchPreview, {
      props: {
        data: {
          schedule: makeSchedule(),
          summary,
          strategies: ['省钱', '保电池'],
          target_date: '2026-08-07',
        },
      },
    });
    expect(wrapper.text()).toContain('24h 充放电策略预览');
    expect(wrapper.text()).toContain('省钱+保电池');
    expect(wrapper.text()).toContain('预计节省');
    expect(wrapper.text()).toContain('1,235'); // est_savings_yuan
    expect(wrapper.text()).toContain('绿电消纳率');
    expect(wrapper.text()).toContain('65'); // green_rate * 100
    expect(wrapper.text()).toContain('需量峰值');
    expect(wrapper.find('.v-chart-mock').exists()).toBe(true);
  });
});
