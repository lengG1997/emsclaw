import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';

// 桩掉 echarts 渲染(jsdom 无 canvas),只验证对比表/最优标记/选择按钮契约。
vi.mock('vue-echarts', () => ({
  default: defineComponent({
    name: 'VChart',
    props: { option: Object, autoresize: Boolean },
    setup: () => () => h('div', { class: 'v-chart-mock' }),
  }),
}));
vi.mock('echarts/core', () => ({ use: vi.fn() }));

import DispatchCompare from '../DispatchCompare.vue';
import { buildPickText, planTitle } from '../../utils/dispatchPlans';

// 故意让两个方案各赢两项,验证"最优"按指标方向分别判定
// (节省/循环/绿电越大越好;需量峰值越小越好)
const plans = [
  {
    plan_label: '省钱优先',
    target_date: '2026-09-11',
    strategies: ['省钱'],
    schedule: [],
    summary: { est_savings_yuan: 1200, charge_kwh: 100, discharge_kwh: 200, green_rate: 0.5, peak_demand_kw: 380 },
  },
  {
    plan_label: '保供少循环',
    target_date: '2026-09-11',
    strategies: ['保供'],
    schedule: [],
    summary: { est_savings_yuan: 1000, charge_kwh: 200, discharge_kwh: 200, green_rate: 0.6, peak_demand_kw: 400 },
  },
];

describe('DispatchCompare', () => {
  it('渲染对比表:标题/方案名/指标行/数值', () => {
    const wrapper = mount(DispatchCompare, { props: { plans } });
    const text = wrapper.text();
    expect(text).toContain('多方案对比');
    expect(text).toContain('2 个方案');
    // 列标题用 LLM 给的 plan_label,而不是"方案 1/2"
    expect(text).toContain('省钱优先');
    expect(text).toContain('保供少循环');
    expect(text).toContain('省钱');
    expect(text).toContain('保供');
    for (const label of ['预计节省', '峰谷循环', '绿电消纳率', '需量峰值']) {
      expect(text).toContain(label);
    }
    expect(text).toContain('1,200'); // est_savings_yuan 方案1
    expect(text).toContain('1,000'); // est_savings_yuan 方案2
    expect(text).toContain('300');   // 循环 100+200
    expect(text).toContain('400');   // 循环 200+200 / 峰值 400
    expect(text).toContain('50');    // green_rate 0.5 -> 50
    expect(text).toContain('60');    // green_rate 0.6 -> 60
  });

  it('四个指标各标出唯一最优(✓ 共 4 个)', () => {
    const wrapper = mount(DispatchCompare, { props: { plans } });
    const marks = wrapper.findAll('span').filter(s => s.text() === '✓');
    expect(marks.length).toBe(4);
  });

  it('点击「采用「方案名」」emit 带方案名+指标指纹的回传文本', async () => {
    const wrapper = mount(DispatchCompare, { props: { plans } });
    const btns = wrapper.findAll('button');
    expect(btns.length).toBe(2);
    // 按钮用 plan_label 命名,而不是"方案 N"
    expect(btns[0].text()).toContain('采用「省钱优先」');
    expect(btns[0].text()).toContain('省钱'); // 按钮带策略名

    await btns[1].trigger('click');
    const text = wrapper.emitted('pick')?.[0]?.[0] as string;
    // 契约:必须能被 LLM 唯一定位 —— 方案名 + 策略 + 关键指标都必须在
    expect(text).toContain('保供少循环');
    expect(text).toContain('策略=保供');
    expect(text).toContain('1,000');          // est_savings_yuan 方案2
    expect(text).toContain('400');            // 峰谷循环 200+200
    expect(text).toContain('60%');            // green_rate 0.6
    expect(text).toContain('直接下发执行');
  });

  it('buildPickText 对不同方案产出可区分文本(按方案名,不按序号)', () => {
    const t0 = buildPickText(plans[0], 0);
    const t1 = buildPickText(plans[1], 1);
    expect(t0).not.toEqual(t1);
    expect(t0).toContain('省钱优先');
    expect(t1).toContain('保供少循环');
    expect(t0).toContain('1,200');
    // 关键回归:回传文本不得再出现位置序号 —— 并行求解下卡片序号不稳定
    expect(t0).not.toContain('方案 1');
    expect(t1).not.toContain('方案 2');
  });

  it('plan_label 缺失时回退到「方案 N」,仍可下发', () => {
    const noLabel = [{ ...plans[0], plan_label: undefined }];
    expect(planTitle(noLabel[0], 0)).toBe('方案 1');
    const t = buildPickText(noLabel[0], 0);
    expect(t).toContain('方案 1');
    expect(t).toContain('直接下发执行');
  });

  it('无方案时不崩', () => {
    const wrapper = mount(DispatchCompare, { props: { plans: [] } });
    expect(wrapper.text()).toContain('多方案对比');
  });
});
