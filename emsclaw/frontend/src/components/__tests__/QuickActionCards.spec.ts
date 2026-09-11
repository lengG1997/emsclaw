import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import QuickActionCards from '../QuickActionCards.vue';

describe('QuickActionCards', () => {
  it('渲染全部 9 张卡片(上方 3 张操作类 + 下方 6 张日常场景)', () => {
    const wrapper = mount(QuickActionCards);
    const buttons = wrapper.findAll('button');
    expect(buttons.length).toBe(9);
    expect(wrapper.text()).toContain('重置场站');
    expect(wrapper.text()).toContain('PCS/BMS');
    expect(wrapper.text()).toContain('场站分析');
    expect(wrapper.text()).toContain('赶产保供');
    expect(wrapper.text()).toContain('峰谷省钱');
    expect(wrapper.text()).toContain('光伏消纳');
    expect(wrapper.text()).toContain('保电池延寿');
    expect(wrapper.text()).toContain('压需量');
    expect(wrapper.text()).toContain('执行检查');
  });

  it('点击卡片 emit select 并携带对应场景 prompt', async () => {
    const wrapper = mount(QuickActionCards);
    const buttons = wrapper.findAll('button');

    await buttons[0].trigger('click');
    expect(wrapper.emitted('select')?.[0]?.[0]).toContain('重置场站');

    await buttons[1].trigger('click');
    expect(wrapper.emitted('select')?.[1]?.[0]).toContain('PCS');

    await buttons[2].trigger('click');
    expect(wrapper.emitted('select')?.[2]?.[0]).toContain('运行数据');

    // 下方场景卡(index 3..8)
    await buttons[3].trigger('click');
    expect(wrapper.emitted('select')?.[3]?.[0]).toContain('订单多');
    expect(wrapper.emitted('select')?.[3]?.[0]).toContain('生产用电');

    await buttons[4].trigger('click');
    expect(wrapper.emitted('select')?.[4]?.[0]).toContain('低谷充电');
    expect(wrapper.emitted('select')?.[4]?.[0]).toContain('电费');

    await buttons[5].trigger('click');
    expect(wrapper.emitted('select')?.[5]?.[0]).toContain('光伏');
    expect(wrapper.emitted('select')?.[5]?.[0]).toContain('反送电');

    await buttons[6].trigger('click');
    expect(wrapper.emitted('select')?.[6]?.[0]).toContain('少循环');
    expect(wrapper.emitted('select')?.[6]?.[0]).toContain('电池寿命');

    await buttons[7].trigger('click');
    expect(wrapper.emitted('select')?.[7]?.[0]).toContain('需量');

    await buttons[8].trigger('click');
    expect(wrapper.emitted('select')?.[8]?.[0]).toContain('执行');
    expect(wrapper.emitted('select')?.[8]?.[0]).toContain('偏差');
  });
});
