<template>
  <div class="flex flex-col h-full w-full overflow-hidden station-overview-page">
    <!-- Masthead -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1800px] mx-auto flex items-end justify-between gap-4 flex-wrap">
        <div class="flex items-end gap-4">
          <div class="flex flex-col gap-0.5">
            <div class="flex items-center gap-2.5">
              <span class="size-2 rounded-full" :class="loading ? 'bg-[var(--function-warning)] animate-pulse' : 'bg-[var(--function-success)]'"></span>
              <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">场站总览</h1>
              <MetricInfo v-bind="EXPLAINERS.whatIsEms" />
            </div>
            <span class="text-[11px] text-[var(--text-tertiary)] ml-[18px]">源网荷储充协同调度 · Agent 决策中枢</span>
          </div>
          <div class="flex items-baseline gap-2 pb-0.5">
            <span class="font-mono text-base tabular-nums text-[var(--text-primary)] leading-none">{{ clockLabel }}</span>
            <span class="text-xs text-[var(--text-tertiary)]">· {{ onlineCount }} / {{ items.length }} PCS 在线 · {{ devices.length }} 设备</span>
          </div>
        </div>
        <div class="flex items-center gap-1.5 flex-wrap">
          <button @click="runAgent('场站分析')" :disabled="analyzing" class="strategy-btn bg-gradient-to-r from-[#3a6b8c] to-[#2f5a7a] text-white">
            <Sparkles :size="13" /><span>场站分析</span>
          </button>
          <button @click="runAgent('请帮我重置场站,清除所有设备数据和调度计划,恢复到初始状态。')" :disabled="analyzing" class="strategy-btn bg-gradient-to-r from-[#6366f1] to-[#4f46e5] text-white">
            <RotateCcw :size="13" /><span>重置场站</span>
          </button>
          <button @click="runAgent('请帮我新增一套PCS和BMS设备,配置设备参数、通信地址和挂载关系。')" :disabled="analyzing" class="strategy-btn bg-gradient-to-r from-[#f59e0b] to-[#d97706] text-white">
            <Cpu :size="13" /><span>新增PCS/BMS</span>
          </button>
          <button @click="runAgent('明天产线订单多、负荷大,帮我生成充放电策略,优先保证生产用电不断,关口表需量别超过申报值。')" :disabled="analyzing" class="strategy-btn border border-[var(--border-main)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <Factory :size="13" /><span>赶产保供</span>
          </button>
          <button @click="runAgent('帮我优化明天的充放电,低谷充电、高峰放电,把电费降到最低。')" :disabled="analyzing" class="strategy-btn border border-[var(--border-main)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <PiggyBank :size="13" /><span>峰谷省钱</span>
          </button>
          <button @click="runAgent('明天晴天光伏大发,帮我尽量消纳光伏、少弃光,并控制不向电网反送电。')" :disabled="analyzing" class="strategy-btn border border-[var(--border-main)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <Sun :size="13" /><span>光伏消纳</span>
          </button>
          <button @click="runAgent('这段时间少折腾电池,帮我生成少循环的充放电策略,延长电池寿命。')" :disabled="analyzing" class="strategy-btn border border-[var(--border-main)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <BatteryCharging :size="13" /><span>保电池延寿</span>
          </button>
          <button @click="runAgent('请生成今天的收益报告,按来源(峰谷套利/需量节省/光伏自用/碳减排)核算收益。')" :disabled="analyzing" class="strategy-btn bg-gradient-to-r from-[#e85d2a] to-[#c94f1f] text-white">
            <Coins :size="13" /><span>收益报告</span>
          </button>
          <button @click="openConfigModal" class="strategy-btn border border-[var(--border-main)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]" title="修改申报需量/防逆流阈值/电价">
            <Settings :size="13" /><span>站配置</span>
          </button>
          <button @click="refresh" :disabled="loading" class="size-8 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:bg-[var(--background-gray-main)] hover:text-[var(--text-primary)] transition-colors flex items-center justify-center disabled:opacity-40" title="刷新">
            <RefreshCw :size="13" :class="{ 'animate-spin': loading }" />
          </button>
        </div>
      </div>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto bg-[var(--background-gray-main)]">
      <div v-if="loading && !hasData" class="flex flex-col items-center justify-center h-full text-[var(--text-tertiary)] gap-3">
        <RefreshCw :size="24" class="animate-spin text-[var(--text-disable)]" />
        <span class="text-xs font-mono">SYNC…</span>
      </div>
      <div v-else class="max-w-[1800px] mx-auto p-6 pt-4 space-y-4">

        <!-- ── EMS 导览条:这个场站是什么、EMS 在干什么 ── -->
        <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden">
          <div class="flex items-center gap-2 px-4 py-3 border-b border-[var(--border-light)]">
            <span class="text-sm font-semibold text-[var(--text-primary)]">这个场站在干什么</span>
            <span class="text-[11px] text-[var(--text-tertiary)] font-mono">1MW/2MWh 储能 + 2MWp 光伏 · 工商业光储站</span>
            <MetricInfo v-bind="EXPLAINERS.whatIsEms" />
          </div>
          <div class="px-4 py-3.5">
            <!-- 能量流图示 -->
            <div class="flex items-center gap-2 flex-wrap text-[11px] text-[var(--text-secondary)]">
              <div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-[#e8b62a]/10 text-[#b8860b]">
                <Sun :size="14" /><span>光伏发电</span>
              </div>
              <ArrowRight :size="13" class="text-[var(--text-disable)]" />
              <div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-[var(--background-gray-main)]">
                <Factory :size="14" /><span>供负荷(用电)</span>
              </div>
              <ArrowRight :size="13" class="text-[var(--text-disable)]" />
              <div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-[#3a6b8c]/10 text-[#3a6b8c]">
                <BatteryCharging :size="14" /><span>多的充电池 / 少的买电</span>
              </div>
              <ArrowRight :size="13" class="text-[var(--text-disable)]" />
              <div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-[#e85d2a]/10 text-[#e85d2a]">
                <Zap :size="14" /><span>峰段放电省钱</span>
              </div>
              <ArrowRight :size="13" class="text-[var(--text-disable)]" />
              <div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-[var(--background-gray-main)]">
                <ArrowDownUp :size="14" /><span>关口表盯需量/防逆流</span>
              </div>
            </div>
            <p class="text-[12px] text-[var(--text-tertiary)] mt-2.5 leading-relaxed">
              EMS 是场站的"大脑":盯着光伏、负荷、电池、关口表,在互相打架的目标间算最优——
              <span class="text-[var(--text-secondary)]">省钱(谷充峰放套利)</span>、
              <span class="text-[var(--text-secondary)]">保电池(少循环延寿)</span>、
              <span class="text-[var(--text-secondary)]">绿电优先(多用光伏少买电)</span>、
              <span class="text-[var(--text-secondary)]">防逆流(不向电网反送)</span>。传统规则 EMS 拍脑袋定不了这种权衡,这正是用 Agent 当大脑的理由。说人话就行——"明天保产线别断电""少折腾电池",系统自己翻译成充放电指令。
            </p>
            <!-- 数据项逐项拆解:每项盯什么 / 为什么盯 / 处理哪个场景 -->
            <div class="mt-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 text-[11px]">
              <div class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-1.5">
                <div class="flex items-center gap-1.5 font-medium text-[var(--text-primary)]"><Sun :size="12" class="text-[#e8b62a]" />光伏出力</div>
                <div class="text-[var(--text-tertiary)] mt-0.5 leading-relaxed"><b class="text-[var(--text-secondary)]">盯什么</b>:发了多少电(kW)。 <b class="text-[var(--text-secondary)]">为什么</b>:光伏是免费电,发的要尽量用掉。 <b class="text-[var(--text-secondary)]">场景</b>:中午发猛了超过用电 → 多的充电池(防逆流);下午发电降下来 → 电池接着顶上。</div>
              </div>
              <div class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-1.5">
                <div class="flex items-center gap-1.5 font-medium text-[var(--text-primary)]"><Factory :size="12" class="text-[var(--text-secondary)]" />负荷(用电)</div>
                <div class="text-[var(--text-tertiary)] mt-0.5 leading-relaxed"><b class="text-[var(--text-secondary)]">盯什么</b>:场站用了多少电(kW),呈午峰+晚峰双峰。 <b class="text-[var(--text-secondary)]">为什么</b>:用电高峰电价贵,这是花钱大头。 <b class="text-[var(--text-secondary)]">场景</b>:高峰时电池放电顶上(削峰省钱);预测明天多高,提前定充放电计划。</div>
              </div>
              <div class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-1.5">
                <div class="flex items-center gap-1.5 font-medium text-[var(--text-primary)]"><BatteryCharging :size="12" class="text-[#3a6b8c]" />电池 SOC / 有功</div>
                <div class="text-[var(--text-tertiary)] mt-0.5 leading-relaxed"><b class="text-[var(--text-secondary)]">盯什么</b>:电池剩多少电(SOC)、此刻在充还是放(有功功率)。 <b class="text-[var(--text-secondary)]">为什么</b>:电池是调度本钱,得知道还有多少弹药。 <b class="text-[var(--text-secondary)]">场景</b>:SOC<20% 别再放(防过放),>90% 别再充(防过充);有功正=充电负=放电。</div>
              </div>
              <div class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-1.5">
                <div class="flex items-center gap-1.5 font-medium text-[var(--text-primary)]"><ArrowDownUp :size="12" class="text-[#e85d2a]" />关口表(下网/上网)</div>
                <div class="text-[var(--text-tertiary)] mt-0.5 leading-relaxed"><b class="text-[var(--text-secondary)]">盯什么</b>:从电网买多少(下网)、卖给电网多少(上网)。 <b class="text-[var(--text-secondary)]">为什么</b>:这是和电网结算的总表。 <b class="text-[var(--text-secondary)]">场景</b>:下网超申报需量→罚款(需量控制);上网超阈值→违规(防逆流)。</div>
              </div>
              <div class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-1.5">
                <div class="flex items-center gap-1.5 font-medium text-[var(--text-primary)]"><Gauge :size="12" class="text-[var(--text-secondary)]" />需量(15min 均值)</div>
                <div class="text-[var(--text-tertiary)] mt-0.5 leading-relaxed"><b class="text-[var(--text-secondary)]">盯什么</b>:近 15 分钟买电平均功率,跟"申报档位"比。 <b class="text-[var(--text-secondary)]">为什么</b>:超档位按超出部分罚款,按月结。 <b class="text-[var(--text-secondary)]">场景</b>:快超线时电池赶紧放电顶上,把下网压回线内,就免罚。</div>
              </div>
              <div class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-1.5">
                <div class="flex items-center gap-1.5 font-medium text-[var(--text-primary)]"><Zap :size="12" class="text-[#6b8e4e]" />电价时段 / 日收益</div>
                <div class="text-[var(--text-tertiary)] mt-0.5 leading-relaxed"><b class="text-[var(--text-secondary)]">盯什么</b>:此刻尖/峰/平/谷哪档;今日赚了多少(放电卖钱−充电花钱)。 <b class="text-[var(--text-secondary)]">为什么</b>:电价差是套利来源,决定何时充放最划算。 <b class="text-[var(--text-secondary)]">场景</b>:谷段(便宜)充电、峰/尖段(贵)放电,赚中间差价。</div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── KPI 指标卡 ── -->
        <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
          <KpiCard :value="fmt(kpi.totalPower)" unit="kW" label="储能功率" :hint="EXPLAINERS.totalPower" :tone="kpi.totalPower > 0 ? 'charge' : kpi.totalPower < 0 ? 'discharge' : 'idle'" :sub="kpi.totalPower > 0 ? '充电中' : kpi.totalPower < 0 ? '放电中' : '待机'" />
          <KpiCard :value="fmt(kpi.totalCapacity)" unit="kWh" label="总容量" :hint="EXPLAINERS.totalCapacity" sub="额定" />
          <KpiCard :value="fmt(kpi.weightedSoc * 100)" unit="%" label="加权 SOC" :hint="EXPLAINERS.weightedSoc" :tone="socTone(kpi.weightedSoc)" :color="socColor(kpi.weightedSoc)" />
          <KpiCard :value="String(kpi.onlineCount)" :unit="`/ ${items.length}`" label="在线 PCS" :hint="EXPLAINERS.onlinePcs" />
          <KpiCard :value="fmt(overview?.meter?.import_kw ?? 0)" unit="kW" label="当前下网" :hint="EXPLAINERS.importPower" tone="demand" />
          <KpiCard :value="fmt(demand?.current_demand_kw ?? 0)" unit="kW" :label="`当前需量 ${fmt((demand?.demand_ratio ?? 0) * 100)}%`" :hint="EXPLAINERS.demand" :tone="(demand?.current_demand_kw ?? 0) > (demand?.contract_demand_kw ?? Infinity) ? 'danger' : 'idle'" />
          <KpiCard :value="fmt(overview?.energy_today?.revenue ?? 0)" unit="元" label="今日收益" :hint="EXPLAINERS.revenue" :tone="(overview?.energy_today?.revenue ?? 0) >= 0 ? 'success' : 'danger'" />
          <KpiCard :value="overview?.tariff_current ? `${TARIFF_PERIOD_LABEL[overview.tariff_current.period_type]}·${overview.tariff_current.energy_price}元` : '-'" :label="overview?.tariff_current ? `${overview.tariff_current.start}-${overview.tariff_current.end}` : '当前电价'" :hint="EXPLAINERS.tariffCurrent" />
        </div>

        <!-- ── 预测区(叠加电价时段背景带) ── -->
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <EChartCard
            :option="loadOption"
            :has-data="hasLoadData"
            :height="200"
            description="24h 负荷预测(橙)+ 净负荷(绿,负荷−光伏)。背景色带=电价时段(尖/峰/平/谷),决定储能何时充放电。"
            empty-text="暂无负荷预测数据"
          >
            <template #title>
              <span class="inline-block size-2.5 rounded-sm" style="background:#e85d2a"></span>负荷预测
              <span class="text-[10px] text-[var(--text-tertiary)] font-mono font-normal">(kW)</span>
              <MetricInfo v-bind="EXPLAINERS.loadForecast" />
            </template>
            <template #meta>
              峰 <span class="text-[var(--text-primary)]">{{ fmt(loadStats.peak) }}</span>
              · 谷 <span class="text-[var(--text-primary)]">{{ fmt(loadStats.valley) }}</span>
              · 均 <span class="text-[var(--text-primary)]">{{ fmt(loadStats.avg) }}</span>
              <span class="ml-1 text-[var(--text-disable)]">背景:尖峰平谷电价</span>
            </template>
          </EChartCard>

          <EChartCard
            :option="pvOption"
            :has-data="hasPvData"
            :height="200"
            description="24h 光伏出力预测(金)+ 净负荷(绿)。光伏过剩(净负荷为负)时段有逆流风险。背景为电价时段。"
            empty-text="暂无光伏预测数据"
          >
            <template #title>
              <span class="inline-block size-2.5 rounded-sm" style="background:#e8b62a"></span>光伏预测
              <span class="text-[10px] text-[var(--text-tertiary)] font-mono font-normal">(kW)</span>
              <MetricInfo v-bind="EXPLAINERS.pvForecast" />
            </template>
            <template #meta>
              峰 <span class="text-[var(--text-primary)]">{{ fmt(pvStats.peak) }}</span>
              · 日发电 <span class="text-[var(--text-primary)]">{{ fmt(forecastDay?.pv_energy_kwh ?? 0) }}</span>kWh
              · 季节 <span class="text-[var(--text-primary)]">{{ fmt(forecastDay?.seasonal_factor ?? 0) }}</span>
            </template>
          </EChartCard>
        </div>

        <!-- ── 关口表能量流(需量/防逆流核心) ── -->
        <EChartCard
          :option="meterOption"
          :has-data="hasMeterData"
          :height="240"
          :description="`近 24h 关口表:下网(进口)、上网(出口)、负荷。虚线=申报需量 ${fmt(demand?.contract_demand_kw ?? 0)}kW(下网超了罚款)与防逆流阈值 ${fmt(overview?.station_config?.anti_reverse_export_setpoint_kw ?? 0)}kW(上网超了违规);红点=逆流告警。`"
          empty-text="近 24h 无关口表数据"
        >
          <template #title>
            <span class="inline-block size-2.5 rounded-sm" style="background:#e85d2a"></span>关口表能量流
            <span class="text-[10px] text-[var(--text-tertiary)] font-mono font-normal">(kW)</span>
            <MetricInfo v-bind="EXPLAINERS.meterFlow" />
          </template>
          <template #meta>
            下网峰 <span class="text-[var(--text-primary)]">{{ fmt(meterStats.peakImport) }}</span>
            · 上网峰 <span class="text-[var(--text-primary)]">{{ fmt(meterStats.peakExport) }}</span>
            · 逆流 <span class="text-[var(--function-error)]">{{ meterStats.reverseCount }}</span> 次
          </template>
        </EChartCard>

        <!-- ── 储能运行:KPI + PCS-BMS 绑定表 ── -->
        <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden">
          <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--border-light)] gap-3">
            <div>
              <div class="text-sm font-semibold text-[var(--text-primary)]">储能运行</div>
              <div class="text-[11px] text-[var(--text-tertiary)] mt-0.5 font-mono">PCS · BMS 实时状态与绑定关系</div>
            </div>
          </div>
          <div v-if="items.length" class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead>
                <tr class="text-[var(--text-tertiary)] text-left border-b border-[var(--border-light)]">
                  <th class="py-2 px-4 font-medium">PCS</th>
                  <th class="py-2 px-4 font-medium">绑定电池</th>
                  <th class="py-2 px-4 font-medium">SOC<MetricInfo v-bind="EXPLAINERS.soc" /></th>
                  <th class="py-2 px-4 font-medium">SOH<MetricInfo v-bind="EXPLAINERS.soh" /></th>
                  <th class="py-2 px-4 font-medium">有功 (kW)</th>
                  <th class="py-2 px-4 font-medium">模式</th>
                  <th class="py-2 px-4 font-medium">温度 (℃)</th>
                  <th class="py-2 px-4 font-medium">效率<MetricInfo v-bind="EXPLAINERS.efficiency" /></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="it in items" :key="it.pcs.id" class="border-b border-[var(--border-light)]/50">
                  <td class="py-2 px-4 font-mono text-[var(--text-primary)]">{{ it.pcs.device_id }}</td>
                  <td class="py-2 px-4 font-mono text-[var(--text-secondary)]">{{ it.battery ? it.battery.device_id : '-' }}</td>
                  <td class="py-2 px-4 font-mono tabular-nums" :style="{ color: socColor(currentSoc(it)) }">{{ fmt(currentSoc(it) * 100) }}%</td>
                  <td class="py-2 px-4 font-mono tabular-nums text-[var(--text-secondary)]">{{ it.battery ? fmt(it.battery.soh * 100) + '%' : '-' }}</td>
                  <td class="py-2 px-4 font-mono tabular-nums text-[var(--text-primary)]">{{ it.latest_pcs_snapshot ? fmt(it.latest_pcs_snapshot.active_power_kw) : '-' }}</td>
                  <td class="py-2 px-4">
                    <span class="inline-block px-1.5 py-0.5 rounded text-[10px]" :class="modeBadge(it)">{{ modeLabel(it) }}</span>
                  </td>
                  <td class="py-2 px-4 font-mono tabular-nums text-[var(--text-secondary)]">{{ it.latest_battery_snapshot ? fmt(it.latest_battery_snapshot.temperature) : '-' }}</td>
                  <td class="py-2 px-4 font-mono tabular-nums text-[var(--text-secondary)]">{{ it.latest_pcs_snapshot ? fmt(it.latest_pcs_snapshot.efficiency * 100) + '%' : '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="py-6 text-center text-xs text-[var(--text-disable)]">无 PCS 设备</div>
        </div>

        <!-- ── 24h 功率 / SOC 曲线 ── -->
        <EChartCard
          :option="powerSocOpt"
          :has-data="hasPowerData"
          :height="240"
          description="近 24h 储能实际充放电功率(橙,正充负放)与电池 SOC(蓝)。评估实际运行与调度计划的吻合度、SOC 是否越红线。"
          empty-text="近 24h 无运行快照"
        >
          <template #title>
            <span class="inline-block size-2.5 rounded-sm" style="background:#e85d2a"></span>有功功率
            <span class="text-[10px] text-[var(--text-tertiary)] font-mono font-normal">(kW)</span>
            <span class="mx-1 text-[var(--text-disable)]">·</span>
            <span class="inline-block size-2.5 rounded-sm" style="background:#3a6b8c"></span>
            <span class="text-[10px] text-[var(--text-tertiary)] font-mono font-normal">SOC (%)</span>
            <MetricInfo v-bind="EXPLAINERS.powerSocCurve" />
          </template>
          <template #meta>
            峰 <span class="text-[var(--text-primary)]">{{ fmt(powerStats.peak) }}</span>
            · 谷 <span class="text-[var(--text-primary)]">{{ fmt(powerStats.valley) }}</span>
            · 近 24h
          </template>
          <template #header-extra>
            <select v-model="selectedPcsId" :disabled="items.length === 0" class="appearance-none bg-[var(--background-gray-main)] border border-[var(--border-main)] rounded-md pl-3 pr-7 py-1 text-xs text-[var(--text-primary)] focus:outline-none disabled:opacity-40">
              <option value="__all__">全部合计</option>
              <option v-for="it in items" :key="it.pcs.id" :value="it.pcs.id">{{ it.pcs.device_id }}</option>
            </select>
          </template>
        </EChartCard>

        <!-- ── 未来一周调度计划 ── -->
        <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden">
          <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--border-light)] gap-3">
            <div>
              <div class="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-1.5">未来一周调度计划<MetricInfo v-bind="EXPLAINERS.chargeSchedule" /></div>
              <div class="text-[11px] text-[var(--text-tertiary)] mt-0.5 font-mono">总额定 {{ fmt(schedule?.total_rated_power_kw ?? 0) }} kW</div>
            </div>
          </div>
          <div class="p-4 space-y-2.5">
            <!-- 时间刻度头 -->
            <div class="flex items-center gap-3">
              <div class="w-[88px] flex-shrink-0 text-right text-[9px] text-[var(--text-tertiary)]">时间(h)</div>
              <div class="flex-1 min-w-0 flex text-[9px] text-[var(--text-tertiary)] font-mono">
                <span v-for="h in 24" :key="h" class="flex-1 text-center">{{ h - 1 }}h</span>
              </div>
              <div class="w-[120px] flex-shrink-0" />
            </div>
            <div
              v-for="(day, idx) in weekSchedules"
              :key="idx"
              class="flex items-center gap-3"
            >
              <!-- 日期标签 -->
              <div class="w-[88px] flex-shrink-0 text-right">
                <div class="text-xs font-semibold" :class="idx === 0 ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)]'">
                  {{ dayLabel(idx) }}
                  <span v-if="idx === 0" class="ml-1 text-[10px] text-[#3a6b8c] font-medium">今天</span>
                </div>
                <div class="text-[10px] text-[var(--text-tertiary)] font-mono tabular-nums">{{ day?.date ?? weekDates[idx] }}</div>
              </div>
              <!-- 24 段彩色条 -->
              <div class="flex-1 min-w-0">
                <div v-if="day?.segments?.length" class="flex h-6 rounded-sm overflow-hidden border border-[var(--border-light)] text-[9px]">
                  <div
                    v-for="(seg, si) in day.segments"
                    :key="si"
                    :style="{ flexGrow: 1, background: segColor(seg.mode) }"
                    class="flex items-center justify-center text-white font-medium"
                    :class="seg.mode === 'standby' ? 'text-[var(--text-tertiary)]' : ''"
                    :title="`${seg.start}–${seg.end} ${seg.label} ${seg.power_kw}kW`"
                  >
                    <span v-if="seg.mode !== 'standby'" class="truncate px-0.5">{{ seg.power_kw ? seg.power_kw + 'kW' : seg.label }}</span>
                  </div>
                </div>
                <div v-else class="flex h-6 rounded-sm border border-dashed border-[var(--border-light)] items-center justify-center">
                  <span class="text-[10px] text-[var(--text-disable)]">暂无计划</span>
                </div>
              </div>
              <!-- 策略组合标签 + 会话链接 -->
              <div class="w-[120px] flex-shrink-0 flex items-center justify-end gap-1.5">
                <span v-if="day?.strategies?.length" class="text-[10px] px-1.5 py-0.5 rounded text-[var(--text-tertiary)] bg-[var(--background-gray-main)]">{{ day.strategies.join('+') }}</span>
                <button
                  v-if="day?.created_by && day.created_by !== 'unknown' && day.created_by !== 'agent'"
                  @click="openScheduleSession(day.created_by)"
                  class="text-[10px] text-[#3a6b8c] hover:text-[#2f5a7a] hover:underline flex items-center gap-0.5 flex-shrink-0"
                  title="打开创建该计划的会话"
                >
                  <Sparkles :size="10" /><span>会话</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- ── 日电量与收益 ── -->
        <EChartCard
          :option="dailyEnergyOption"
          :has-data="dailyEnergy.length > 0"
          :height="220"
          description="近 7 天每日充电量(蓝)、放电量(橙)与套利收益(绿线)。看储能是否稳定赚钱、有没有异常天。"
          empty-text="暂无日电量数据"
        >
          <template #title>
            <span class="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-1.5">日电量与收益<MetricInfo v-bind="EXPLAINERS.dailyEnergy" /></span>
          </template>
          <template #meta>
            累计收益 <span class="text-[var(--function-success)]">{{ fmt(dailyEnergyTotal) }}</span> 元
            · 日均 <span class="text-[var(--text-primary)]">{{ fmt(dailyEnergyTotal / (dailyEnergy.length || 1)) }}</span> 元
          </template>
        </EChartCard>

        <!-- ── 设备清单 ── -->
        <div class="bg-[var(--background-card)] rounded-lg border border-[var(--border-main)] overflow-hidden">
          <div class="flex items-center justify-between px-4 py-3 border-b border-[var(--border-light)] gap-3">
            <div>
              <div class="text-sm font-semibold text-[var(--text-primary)]">设备清单</div>
              <div class="text-[11px] text-[var(--text-tertiary)] mt-0.5 font-mono">共 {{ devices.length }} 台</div>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table v-if="devices.length" class="w-full text-xs">
              <thead>
                <tr class="text-[var(--text-tertiary)] text-left border-b border-[var(--border-light)]">
                  <th class="py-2 px-4 font-medium">名称</th>
                  <th class="py-2 px-4 font-medium">类型</th>
                  <th class="py-2 px-4 font-medium">状态</th>
                  <th class="py-2 px-4 font-medium">登记时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in devices" :key="d.id" class="border-b border-[var(--border-light)]/50">
                  <td class="py-2 px-4 text-[var(--text-primary)]">{{ d.name }}<span class="ml-2 text-[10px] text-[var(--text-disable)] font-mono">{{ d.id }}</span></td>
                  <td class="py-2 px-4">
                    <span class="inline-block px-1.5 py-0.5 rounded text-[10px]" :class="deviceTypeBadge(d.device_type)">{{ deviceTypeLabel(d.device_type) }}</span>
                  </td>
                  <td class="py-2 px-4">
                    <span class="inline-flex items-center gap-1">
                      <span class="size-1.5 rounded-full" :class="statusDot(d.status)"></span>
                      <span class="text-[var(--text-secondary)]">{{ statusLabel(d.status) }}</span>
                    </span>
                  </td>
                  <td class="py-2 px-4 font-mono tabular-nums text-[var(--text-tertiary)]">{{ fmtDate(d.created_at) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="py-6 text-center text-xs text-[var(--text-disable)]">暂无设备</div>
          </div>
        </div>

      </div>
    </div>

    <!-- Toast -->
    <Teleport to="body">
      <div v-if="toast" class="fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-md shadow-lg text-xs font-medium border-l-2" :class="toastClass">
        {{ toast.text }}
      </div>
    </Teleport>

    <!-- ── 站配置编辑弹窗 ── -->
    <Dialog :open="configModalOpen" @update:open="(v: boolean) => { configModalOpen = v }">
      <DialogContent class="w-[420px] max-w-[95vw]">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2 text-base">
            <Settings :size="15" />站配置
          </DialogTitle>
        </DialogHeader>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-[var(--text-secondary)] mb-1">申报需量 (kW)</label>
            <input v-model.number="configForm.contract_demand_kw" type="number" min="0" step="50"
                   class="w-full h-9 px-2.5 rounded-md border border-[var(--border-main)] bg-[var(--background-gray-main)] text-[var(--text-primary)] outline-none focus:border-[var(--function-success)]" />
            <p class="text-[10px] text-[var(--text-tertiary)] mt-1">基本电费(需量)计费基准,关口表下网超过申报需量按超出部分 2 倍计收。调度优化"尊重申报需量"以此为上限。</p>
          </div>
          <div>
            <label class="block text-[var(--text-secondary)] mb-1">防逆流上网阈值 (kW)</label>
            <input v-model.number="configForm.anti_reverse_export_setpoint_kw" type="number" min="0" step="10"
                   class="w-full h-9 px-2.5 rounded-md border border-[var(--border-main)] bg-[var(--background-gray-main)] text-[var(--text-primary)] outline-none focus:border-[var(--function-success)]" />
            <p class="text-[10px] text-[var(--text-tertiary)] mt-1">关口表上网功率超过该阈值判为逆流违规。</p>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-[var(--text-secondary)] mb-1">容量电价 (元/kW·月)</label>
              <input v-model.number="configForm.capacity_price_yuan_per_kw_month" type="number" min="0" step="1"
                     class="w-full h-9 px-2.5 rounded-md border border-[var(--border-main)] bg-[var(--background-gray-main)] text-[var(--text-primary)] outline-none focus:border-[var(--function-success)]" />
            </div>
            <div>
              <label class="block text-[var(--text-secondary)] mb-1">需量电价 (元/kW·月)</label>
              <input v-model.number="configForm.demand_price_yuan_per_kw_month" type="number" min="0" step="1"
                     class="w-full h-9 px-2.5 rounded-md border border-[var(--border-main)] bg-[var(--background-gray-main)] text-[var(--text-primary)] outline-none focus:border-[var(--function-success)]" />
            </div>
          </div>
          <p class="text-[10px] text-[var(--text-tertiary)]">更新立即生效:需量状态、调度优化(申报需量上限)、收益核算读到新值。只更新有改动的字段。</p>
        </div>
        <div class="flex items-center justify-end gap-2 pt-1">
          <button @click="configModalOpen = false" class="h-8 px-3 rounded-md border border-[var(--border-main)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs">取消</button>
          <button @click="saveConfig" :disabled="configSaving" class="h-8 px-3 rounded-md bg-gradient-to-r from-[#3a6b8c] to-[#2f5a7a] text-white text-xs disabled:opacity-50">
            {{ configSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import {
  RefreshCw, Sparkles, PiggyBank, Coins, RotateCcw, Cpu,
  Sun, BatteryCharging, Zap, Factory, ArrowRight, Settings,
} from 'lucide-vue-next';
import { listPcs, getPcsSnapshots, getBatterySnapshots, getChargeSchedule } from '@/api/pcs';
import {
  getStationForecastDay, getStationOverview, getStationDemand,
  getStationMeterSnapshots, getStationTariff, getStationDailyEnergy,
  updateStationConfig,
} from '@/api/station';
import { listDevices } from '@/api/devices';
import { createSession } from '@/api/agent';
import { setPendingChat } from '@/composables/usePendingChat';
import type { PcsStatusItem, PcsSnapshot, BatterySnapshot, ChargeSchedule, PcsMode } from '@/types/pcs';
import type {
  StationForecastDay, StationOverview, DemandStatus, TariffRow,
  MeterSnapshotPoint, DailyEnergy, StationConfigUpdate,
} from '@/types/station';
import { TARIFF_PERIOD_LABEL } from '@/types/station';
import type { Device, DeviceType, DeviceStatus } from '@/types/device';
import type { EChartsOption } from 'echarts';
import EChartCard from '@/components/EChartCard.vue';
import MetricInfo from '@/components/MetricInfo.vue';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { EXPLAINERS, type Explainer } from '@/constants/explainers';

// KPI 卡片(内联,带 MetricInfo)
import { defineComponent as _dc, h } from 'vue';

const AXIS = '#6b7280';
const SPLIT = 'rgba(107,114,128,0.15)';

// 电价时段背景色(柔和)
const TARIFF_BG: Record<string, string> = {
  sharp: 'rgba(232,93,42,0.10)',
  peak: 'rgba(232,182,42,0.10)',
  flat: 'rgba(107,114,128,0.05)',
  valley: 'rgba(58,107,140,0.10)',
};

// ── 状态 ──
const loading = ref(false);
const items = ref<PcsStatusItem[]>([]);
const forecastDay = ref<StationForecastDay | null>(null);
const schedule = ref<ChargeSchedule | null>(null);
const weekSchedules = ref<(ChargeSchedule | null)[]>([]);
const weekDates = ref<string[]>([]);
const devices = ref<Device[]>([]);
const pcsSnaps = ref<PcsSnapshot[]>([]);
const batSnaps = ref<BatterySnapshot[]>([]);
const selectedPcsId = ref('__all__');
const overview = ref<StationOverview | null>(null);
const demand = ref<DemandStatus | null>(null);
const tariff = ref<TariffRow[]>([]);
const meterSnaps = ref<MeterSnapshotPoint[]>([]);
const dailyEnergy = ref<DailyEnergy[]>([]);
const toast = ref<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
const analyzing = ref(false);

// ── 站配置编辑 ──
const configModalOpen = ref(false);
const configSaving = ref(false);
const configForm = ref<Required<StationConfigUpdate>>({
  contract_demand_kw: 0,
  anti_reverse_export_setpoint_kw: 0,
  capacity_price_yuan_per_kw_month: 0,
  demand_price_yuan_per_kw_month: 0,
});

function openConfigModal() {
  const ov = overview.value?.station_config;
  const dem = demand.value;
  configForm.value = {
    contract_demand_kw: dem?.contract_demand_kw ?? ov?.contract_demand_kw ?? 0,
    anti_reverse_export_setpoint_kw: ov?.anti_reverse_export_setpoint_kw ?? 0,
    capacity_price_yuan_per_kw_month: ov?.capacity_price_yuan_per_kw_month ?? 0,
    demand_price_yuan_per_kw_month: dem?.demand_price_yuan_per_kw_month ?? ov?.demand_price_yuan_per_kw_month ?? 0,
  };
  configModalOpen.value = true;
}

async function saveConfig() {
  configSaving.value = true;
  try {
    await updateStationConfig(configForm.value);
    showToast('success', '站配置已更新');
    configModalOpen.value = false;
    await refresh();
  } catch (e: any) {
    showToast('error', e?.response?.data?.detail ?? e?.message ?? '保存失败');
  } finally {
    configSaving.value = false;
  }
}

const hasData = computed(() => items.value.length > 0 || !!forecastDay.value || !!schedule.value || devices.value.length > 0 || !!overview.value);

const todayStr = () => new Date().toISOString().slice(0, 10);

// 未来 7 天日期列表(含今天)
const DAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
function weekDateList(): string[] {
  const dates: string[] = [];
  const now = new Date();
  for (let i = 0; i < 7; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() + i);
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates;
}
function dayLabel(idx: number): string {
  const now = new Date();
  const d = new Date(now);
  d.setDate(d.getDate() + idx);
  return DAY_NAMES[d.getDay()];
}
function openScheduleSession(sessionId: string) {
  router.push(`/chat/${sessionId}`);
}

// ── Agent 发起 ──
const router = useRouter();
async function runAgent(message: string, _hint?: keyof typeof EXPLAINERS) {
  if (analyzing.value) return;
  analyzing.value = true;
  try {
    const session = await createSession({ mode: 'business' });
    setPendingChat({ message, files: [], mode: 'business' });
    router.push(`/chat/${session.session_id}`);
  } catch (e: any) {
    showToast('error', e?.response?.data?.detail ?? e?.message ?? '创建会话失败,请稍后重试');
  } finally {
    analyzing.value = false;
  }
}

const clockLabel = computed(() => {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
});

// ── KPI ──
const kpi = computed(() => {
  let totalPower = 0;
  let totalCapacity = 0;
  let socWeighted = 0;
  let onlineCnt = 0;
  let hasPower = false;
  for (const it of items.value) {
    const snap = it.latest_pcs_snapshot;
    if (snap) {
      totalPower += snap.active_power_kw;
      hasPower = true;
      onlineCnt += 1;
    }
    if (it.battery) {
      totalCapacity += it.battery.rated_capacity_kwh;
      if (it.battery.soc != null) socWeighted += it.battery.soc * it.battery.rated_capacity_kwh;
    }
  }
  return {
    totalPower: hasPower ? totalPower : 0,
    totalCapacity,
    weightedSoc: totalCapacity > 0 ? socWeighted / totalCapacity : 0,
    onlineCount: onlineCnt,
  };
});

const onlineCount = computed(() => items.value.filter((it) => it.latest_pcs_snapshot != null).length);

function socTone(soc: number) {
  if (soc < 0.2 || soc > 0.9) return 'danger';
  if (soc < 0.4) return 'warning';
  return 'success';
}

// ── 通用统计 ──
function stats(values: number[]) {
  if (!values.length) return { peak: 0, valley: 0, avg: 0 };
  return {
    peak: Math.max(...values),
    valley: Math.min(...values),
    avg: values.reduce((a, b) => a + b, 0) / values.length,
  };
}

// ── 电价时段 markArea(24h 类目轴,按小时索引) ──
function tariffMarkAreas(rows: TariffRow[]) {
  if (!rows.length) return undefined;
  return {
    silent: true,
    data: rows.map((r) => [
      { xAxis: r.start_hour, itemStyle: { color: TARIFF_BG[r.period_type] || TARIFF_BG.flat } },
      { xAxis: r.end_hour >= 24 ? 23.999 : r.end_hour },
    ]),
  };
}

// ── 图表 tooltip 通俗讲解:每个系列名 → 一句大白话说明(复用 EXPLAINERS 单一真相源) ──
// 鼠标悬停某个数据点时,tooltip 在「数值」后面再给一句解释,让不懂 EMS 的人也能看懂这根线在说什么。
const SERIES_EXPLAIN: Record<string, string> = {
  '负荷': '场站用电负荷(kW),双峰=午峰+晚峰;预测图是预计值,关口表图是实测值',
  '净负荷': '负荷−光伏。正=还要从电网买,负=光伏多出来了可能逆流',
  '光伏出力': '光伏预计发多少电(kW),中午高夜间 0,多了要先充电池',
  '下网(进口)': '从电网买的电(kW),越大电费越高,储能/光伏会把它压下来',
  '上网(出口)': '往电网送的电(kW),光伏过剩才会上网,超防逆流阈值=违规',
  '关口净功率': '关口表净有功(带符号)=下网−上网。正=从电网受电,负=往电网送电',
  '逆流告警': '这一刻上网超了防逆流阈值,红点=违规告警',
  '有功功率': '储能实际充放电功率(kW)。正=充电(往电池存),负=放电(往外送)',
  'SOC': '电池当前电量百分比。低于 20% 或高于 90% 越红线',
  '充电': '今天充进电池的电量(kWh),谷段充得多=低买',
  '放电': '今天电池放出的电量(kWh),峰段放得多=高卖',
  '收益': '今天峰谷套利赚的钱(元)=放电卖的钱−充电花的钱',
};

// 把「系列名 → 数值 单位」渲染成「系列名: 数值 单位\n说明」的统一格式,所有图表复用。
function renderTip(params: any, unit: string): string {
  const arr = Array.isArray(params) ? params : [params];
  if (!arr.length) return '';
  // 时间轴类用 value[0]=时间戳;类目轴用 axisValueLabel。两种都兼容。
  const first = arr[0];
  let head = '';
  if (first.value instanceof Array && typeof first.value[0] === 'number' && first.value[0] > 1e12) {
    const t = new Date(first.value[0]);
    head = `${String(t.getMonth() + 1).padStart(2, '0')}/${String(t.getDate()).padStart(2, '0')} ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
  } else if (first.axisValueLabel) {
    head = first.axisValueLabel;
  }
  let s = head;
  for (const it of arr) {
    const name = it.seriesName ?? it.name;
    const raw = it.value instanceof Array ? it.value[1] : it.value;
    const explain = SERIES_EXPLAIN[name];
    s += `<br/>${it.marker}<b>${name}</b>: ${fmt(Number(raw))} ${unit}`;
    if (explain) s += `<br/><span style="margin-left:18px;color:#9ca3af;font-size:11px">${explain}</span>`;
  }
  return s;
}

// ── 预测曲线 option(24h 类目轴,叠加电价背景) ──
function forecastOption(series: { data: number[]; color: string; name?: string; area?: boolean }[], unit: string, withTariff = false): EChartsOption {
  if (!series.length || !series[0].data.length) return {};
  const n = series[0].data.length;
  const hours = Array.from({ length: n }, (_, i) => `${String(i).padStart(2, '0')}:00`);
  const baseSeries: any[] = series.map((s, idx) => ({
    name: s.name, type: 'line' as const, data: s.data, smooth: true, symbol: 'none',
    lineStyle: { color: s.color, width: 2 },
    areaStyle: s.area ? { color: s.color, opacity: 0.1 } : undefined,
    markArea: withTariff && idx === 0 ? tariffMarkAreas(tariff.value) : undefined,
  }));
  return {
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    tooltip: { trigger: 'axis', confine: true, formatter: (p: any) => renderTip(p, unit) },
    legend: series.length > 1 ? {
      data: series.map((s) => s.name).filter(Boolean) as string[],
      top: 2, right: 8, textStyle: { color: AXIS, fontSize: 11 }, itemWidth: 12, itemHeight: 8,
    } : undefined,
    xAxis: {
      type: 'category', data: hours, boundaryGap: false,
      axisLine: { lineStyle: { color: AXIS } },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace', interval: 6 },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
      splitLine: { lineStyle: { color: SPLIT } },
    },
    series: baseSeries,
  };
}

// ── 关口表能量流 option(时间轴 + 需量/防逆流标线 + 逆流红点 + 总有功) ──
const meterOption = computed<EChartsOption>(() => {
  if (!meterSnaps.value.length) return {};
  const importData = meterSnaps.value.map((s) => [s.timestamp * 1000, s.import_kw]);
  const exportData = meterSnaps.value.map((s) => [s.timestamp * 1000, s.export_kw]);
  const loadData = meterSnaps.value.map((s) => [s.timestamp * 1000, s.load_kw]);
  // 关口表一级有功:带符号(正=下网,负=上网);后端缺失时由 import-export 推导
  const totalPData = meterSnaps.value.map((s) => [
    s.timestamp * 1000,
    s.total_active_power_kw ?? (s.import_kw - s.export_kw),
  ]);
  const reverseData = meterSnaps.value
    .filter((s) => s.reverse_flow)
    .map((s) => [s.timestamp * 1000, s.export_kw]);
  const contract = demand.value?.contract_demand_kw ?? 0;
  const setpoint = overview.value?.station_config?.anti_reverse_export_setpoint_kw ?? 0;
  return {
    grid: { left: 52, right: 16, top: 32, bottom: 28 },
    tooltip: { trigger: 'axis', confine: true, formatter: (p: any) => renderTip(p, 'kW') },
    legend: { data: ['下网(进口)', '上网(出口)', '负荷', '关口净功率'], top: 4, right: 8, textStyle: { color: AXIS, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: AXIS } },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
    },
    yAxis: {
      type: 'value', name: 'kW',
      nameTextStyle: { color: AXIS, fontSize: 10 },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
      splitLine: { lineStyle: { color: SPLIT } },
    },
    series: [
      {
        name: '下网(进口)', type: 'line', data: importData, symbol: 'none', smooth: true,
        lineStyle: { color: '#e85d2a', width: 2 },
        areaStyle: { color: '#e85d2a', opacity: 0.08 },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { color: 'rgba(232,93,42,0.5)', type: 'dashed' },
          label: { formatter: `申报需量 ${fmt(contract)}`, color: '#e85d2a', fontSize: 10, position: 'insideEndTop' },
          data: contract > 0 ? [{ yAxis: contract }] : [],
        },
      },
      {
        name: '上网(出口)', type: 'line', data: exportData, symbol: 'none', smooth: true,
        lineStyle: { color: '#6b8e4e', width: 2 },
        areaStyle: { color: '#6b8e4e', opacity: 0.08 },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { color: 'rgba(107,142,78,0.5)', type: 'dashed' },
          label: { formatter: `防逆流阈值 ${fmt(setpoint)}`, color: '#6b8e4e', fontSize: 10, position: 'insideEndBottom' },
          data: setpoint > 0 ? [{ yAxis: setpoint }] : [],
        },
      },
      { name: '负荷', type: 'line', data: loadData, symbol: 'none', smooth: true, lineStyle: { color: '#9ca3af', width: 1.5, type: 'dashed' } },
      {
        name: '关口净功率', type: 'line', data: totalPData, symbol: 'none', smooth: true,
        lineStyle: { color: '#dc2626', width: 2.5 },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: 'rgba(220,38,38,0.3)', type: 'dashed' }, label: { show: false }, data: [{ yAxis: 0 }] },
        z: 3,
      },
      {
        name: '逆流告警', type: 'scatter', data: reverseData, symbolSize: 5,
        itemStyle: { color: '#ef4444' },
      },
    ],
  };
});

// ── 功率 + SOC option(双轴,时间轴) ──
function powerSocOption(pcsSnaps: PcsSnapshot[], batSnaps: BatterySnapshot[]): EChartsOption {
  if (!pcsSnaps.length && !batSnaps.length) return {};
  const powerData = pcsSnaps.map((s) => [s.timestamp * 1000, s.active_power_kw]);
  const socData = batSnaps.map((s) => [s.timestamp * 1000, Number((s.soc * 100).toFixed(2))]);
  return {
    grid: { left: 52, right: 52, top: 32, bottom: 28 },
    tooltip: {
      trigger: 'axis', confine: true,
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params];
        if (!arr.length) return '';
        const t = new Date(arr[0].value[0]);
        let s = `${String(t.getMonth() + 1).padStart(2, '0')}/${String(t.getDate()).padStart(2, '0')} ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
        for (const it of arr) {
          const unit = it.seriesName === 'SOC' ? '%' : 'kW';
          const explain = SERIES_EXPLAIN[it.seriesName];
          s += `<br/>${it.marker}<b>${it.seriesName}</b>: ${fmt(Number(it.value[1]))} ${unit}`;
          if (explain) s += `<br/><span style="margin-left:18px;color:#9ca3af;font-size:11px">${explain}</span>`;
        }
        return s;
      },
    },
    legend: { data: ['有功功率', 'SOC'], top: 4, right: 8, textStyle: { color: AXIS, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: AXIS } },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
    },
    yAxis: [
      {
        type: 'value', name: 'kW',
        nameTextStyle: { color: AXIS, fontSize: 10 },
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
        splitLine: { lineStyle: { color: SPLIT } },
      },
      {
        type: 'value', name: '%', min: 0, max: 100,
        nameTextStyle: { color: AXIS, fontSize: 10 },
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace', formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '有功功率', type: 'line', data: powerData, yAxisIndex: 0, symbol: 'none', smooth: true,
        lineStyle: { color: '#e85d2a', width: 2 },
        areaStyle: { color: '#e85d2a', opacity: 0.1 },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: 'rgba(107,114,128,0.35)', type: 'dashed' }, label: { show: false }, data: [{ yAxis: 0 }] },
      },
      {
        name: 'SOC', type: 'line', data: socData, yAxisIndex: 1, symbol: 'none',
        lineStyle: { color: '#3a6b8c', width: 1.5, type: 'dashed' },
      },
    ],
  };
}

// ── 日电量与收益 option(柱+线) ──
const dailyEnergyOption = computed<EChartsOption>(() => {
  if (!dailyEnergy.value.length) return {};
  const rows = [...dailyEnergy.value].sort((a, b) => a.date.localeCompare(b.date));
  const dates = rows.map((r) => r.date.slice(5));
  return {
    grid: { left: 52, right: 52, top: 32, bottom: 28 },
    tooltip: {
      trigger: 'axis', confine: true,
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params];
        if (!arr.length) return '';
        let s = arr[0].axisValueLabel;
        for (const it of arr) {
          const unit = it.seriesName === '收益' ? '元' : 'kWh';
          const explain = SERIES_EXPLAIN[it.seriesName];
          s += `<br/>${it.marker}<b>${it.seriesName}</b>: ${fmt(Number(it.value))} ${unit}`;
          if (explain) s += `<br/><span style="margin-left:18px;color:#9ca3af;font-size:11px">${explain}</span>`;
        }
        return s;
      },
    },
    legend: { data: ['充电', '放电', '收益'], top: 4, right: 8, textStyle: { color: AXIS, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    xAxis: {
      type: 'category', data: dates,
      axisLine: { lineStyle: { color: AXIS } },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
    },
    yAxis: [
      {
        type: 'value', name: 'kWh',
        nameTextStyle: { color: AXIS, fontSize: 10 },
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
        splitLine: { lineStyle: { color: SPLIT } },
      },
      {
        type: 'value', name: '元',
        nameTextStyle: { color: AXIS, fontSize: 10 },
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: AXIS, fontSize: 10, fontFamily: 'monospace' },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '充电', type: 'bar', data: rows.map((r) => r.charge_kwh), itemStyle: { color: '#3a6b8c', opacity: 0.85 }, barGap: '10%' },
      { name: '放电', type: 'bar', data: rows.map((r) => r.discharge_kwh), itemStyle: { color: '#e85d2a', opacity: 0.85 } },
      { name: '收益', type: 'line', yAxisIndex: 1, data: rows.map((r) => r.revenue), symbol: 'circle', symbolSize: 6, lineStyle: { color: '#6b8e4e', width: 2 }, itemStyle: { color: '#6b8e4e' } },
    ],
  };
});

// ── 派生 ──
const loadStats = computed(() => stats(forecastDay.value?.load_kw ?? []));
const pvStats = computed(() => stats(forecastDay.value?.pv_kw ?? []));
const powerStats = computed(() => stats(pcsSnaps.value.map((s) => s.active_power_kw)));
const meterStats = computed(() => {
  const arr = meterSnaps.value;
  if (!arr.length) return { peakImport: 0, peakExport: 0, reverseCount: 0 };
  return {
    peakImport: Math.max(...arr.map((s) => s.import_kw)),
    peakExport: Math.max(...arr.map((s) => s.export_kw)),
    reverseCount: arr.filter((s) => s.reverse_flow).length,
  };
});
const dailyEnergyTotal = computed(() => dailyEnergy.value.reduce((a, r) => a + (r.revenue || 0), 0));

const loadOption = computed(() => forecastOption(
  [
    { data: forecastDay.value?.load_kw ?? [], color: '#e85d2a', name: '负荷', area: true },
    { data: forecastDay.value?.net_load_kw ?? [], color: '#6b8e4e', name: '净负荷' },
  ],
  'kW', true,
));
const pvOption = computed(() => forecastOption(
  [
    { data: forecastDay.value?.pv_kw ?? [], color: '#e8b62a', name: '光伏出力', area: true },
    { data: forecastDay.value?.net_load_kw ?? [], color: '#6b8e4e', name: '净负荷' },
  ],
  'kW', true,
));
const powerSocOpt = computed(() => powerSocOption(pcsSnaps.value, batSnaps.value));

const hasLoadData = computed(() => (forecastDay.value?.load_kw?.length ?? 0) > 0);
const hasPvData = computed(() => (forecastDay.value?.pv_kw?.length ?? 0) > 0);
const hasPowerData = computed(() => pcsSnaps.value.length > 0 || batSnaps.value.length > 0);
const hasMeterData = computed(() => meterSnaps.value.length > 0);

// ── PCS-BMS 表辅助 ──
function currentSoc(it: PcsStatusItem): number {
  if (it.latest_battery_snapshot?.soc != null) return it.latest_battery_snapshot.soc;
  return it.battery?.soc ?? 0;
}
function modeLabel(it: PcsStatusItem): string {
  const m = it.latest_pcs_snapshot?.mode ?? it.pcs.override_mode;
  if (!m) return '-';
  return { charge: '充电', discharge: '放电', standby: '待机', auto: '自动' }[m as PcsMode] ?? m;
}
function modeBadge(it: PcsStatusItem): string {
  const m = it.latest_pcs_snapshot?.mode ?? it.pcs.override_mode;
  if (m === 'charge') return 'bg-[#3a6b8c]/15 text-[#3a6b8c]';
  if (m === 'discharge') return 'bg-[#e85d2a]/15 text-[#e85d2a]';
  return 'bg-[var(--background-gray-main)] text-[var(--text-tertiary)]';
}
function segColor(mode: string): string {
  if (mode === 'charge') return '#3a6b8c';
  if (mode === 'discharge') return '#e85d2a';
  return '#9ca3af';
}
function deviceTypeLabel(t: DeviceType): string {
  return { battery: '电池', inverter: '逆变器', meter: '电表', pcs: 'PCS' }[t];
}
function deviceTypeBadge(t: DeviceType): string {
  return {
    battery: 'bg-[#3a6b8c]/15 text-[#3a6b8c]',
    pcs: 'bg-[#e85d2a]/15 text-[#e85d2a]',
    inverter: 'bg-[#6b8e4e]/15 text-[#6b8e4e]',
    meter: 'bg-[var(--background-gray-main)] text-[var(--text-tertiary)]',
  }[t];
}
function statusDot(s: DeviceStatus): string {
  return { online: 'bg-[var(--function-success)]', pending_online: 'bg-[var(--function-warning)]', offline: 'bg-[var(--text-disable)]' }[s];
}
function statusLabel(s: DeviceStatus): string {
  return { online: '在线', pending_online: '待入网', offline: '离线' }[s];
}

function fmt(n: number): string {
  if (!isFinite(n)) return '0.00';
  return n.toFixed(2);
}
function fmtDate(ts: number): string {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
function socColor(soc: number): string {
  if (soc < 0.2) return 'var(--function-error)';
  if (soc < 0.4) return 'var(--function-warning)';
  if (soc > 0.9) return 'var(--function-warning)';
  return 'var(--text-primary)';
}

// ── 24h 窗口 ──
const curveWindow = computed(() => {
  const to = Math.floor(Date.now() / 1000);
  const from = to - 24 * 3600;
  return { from, to };
});

async function fetchSnapshots() {
  const { from, to } = curveWindow.value;
  if (items.value.length === 0) {
    pcsSnaps.value = [];
    batSnaps.value = [];
    return;
  }
  if (selectedPcsId.value === '__all__') {
    const [allPcs, allBat] = await Promise.all([
      Promise.all(items.value.map((it) => getPcsSnapshots(it.pcs.id, from, to).catch(() => [] as PcsSnapshot[]))),
      Promise.all(items.value.map((it) => getBatterySnapshots(it.pcs.id, from, to).catch(() => [] as BatterySnapshot[]))),
    ]);
    const pBucket = new Map<number, number>();
    for (const arr of allPcs) for (const s of arr) {
      const k = Math.round(s.timestamp / 60) * 60;
      pBucket.set(k, (pBucket.get(k) ?? 0) + s.active_power_kw);
    }
    pcsSnaps.value = [...pBucket.entries()].sort((a, b) => a[0] - b[0]).map(([ts, p]) => ({
      id: `agg-${ts}`, pcs_id: '__all__', timestamp: ts,
      active_power_kw: p, reactive_power_kvar: 0, mode: 'auto' as PcsMode,
      ac_voltage_v: 0, dc_voltage_v: 0, efficiency: 0, status: 'aggregated',
    }));
    const totalCap = items.value.reduce((a, it) => a + (it.battery?.rated_capacity_kwh ?? 0), 0) || 1;
    const bBucket = new Map<number, number>();
    items.value.forEach((it, idx) => {
      const cap = it.battery?.rated_capacity_kwh ?? 0;
      for (const s of allBat[idx]) {
        const k = Math.round(s.timestamp / 60) * 60;
        bBucket.set(k, (bBucket.get(k) ?? 0) + s.soc * cap);
      }
    });
    batSnaps.value = [...bBucket.entries()].sort((a, b) => a[0] - b[0]).map(([ts, sw]) => ({
      id: `agg-${ts}`, battery_id: '__all__', timestamp: ts,
      soc: sw / totalCap, voltage: 0, current_a: 0, temperature: 0,
      mode: 'auto' as PcsMode, cycle_count: 0,
    }));
  } else {
    const [p, b] = await Promise.all([
      getPcsSnapshots(selectedPcsId.value, from, to).catch(() => [] as PcsSnapshot[]),
      getBatterySnapshots(selectedPcsId.value, from, to).catch(() => [] as BatterySnapshot[]),
    ]);
    pcsSnaps.value = p;
    batSnaps.value = b;
  }
}

async function refresh() {
  loading.value = true;
  try {
    const { from, to } = curveWindow.value;
    const dates = weekDateList();
    weekDates.value = dates;
    // 并行拉取 7 天调度计划(每天独立容错)
    const schedulePromises = dates.map(d => getChargeSchedule(d).catch(() => null));
    const [pcs, fcDay, ...schedules] = await Promise.all([
      listPcs(),
      getStationForecastDay(todayStr()).catch(() => null),
      ...schedulePromises,
      listDevices(),
      getStationOverview().catch(() => null),
      getStationDemand().catch(() => null),
      getStationTariff().catch(() => [] as TariffRow[]),
      getStationMeterSnapshots(from, to).catch(() => [] as MeterSnapshotPoint[]),
      getStationDailyEnergy(7).catch(() => [] as DailyEnergy[]),
    ]);
    items.value = pcs;
    forecastDay.value = fcDay;
    weekSchedules.value = schedules.slice(0, 7) as (ChargeSchedule | null)[];
    schedule.value = weekSchedules.value[0] ?? null;
    // 后续解构:devs, ov, dem, trf, meter, daily
    const rest = schedules.slice(7);
    devices.value = rest[0] as Device[];
    overview.value = rest[1] as StationOverview | null;
    demand.value = rest[2] as DemandStatus | null;
    tariff.value = (rest[3] as TariffRow[]) ?? [];
    meterSnaps.value = (rest[4] as MeterSnapshotPoint[]) ?? [];
    dailyEnergy.value = (rest[5] as DailyEnergy[]) ?? [];
    if (pcs.length && selectedPcsId.value !== '__all__' && !pcs.some((it) => it.pcs.id === selectedPcsId.value)) {
      selectedPcsId.value = '__all__';
    }
    await fetchSnapshots();
  } catch (e: any) {
    showToast('error', e?.response?.data?.detail ?? e?.message ?? '加载失败');
  } finally {
    loading.value = false;
  }
}

const toastClass = computed(() => {
  const t = toast.value?.type ?? 'info';
  if (t === 'error') return 'bg-[var(--background-card)] text-[var(--function-error)] border-[var(--function-error)]';
  if (t === 'success') return 'bg-[var(--background-card)] text-[var(--function-success)] border-[var(--function-success)]';
  return 'bg-[var(--background-card)] text-[#3a6b8c] border-[#3a6b8c]';
});

function showToast(type: 'success' | 'error' | 'info', text: string) {
  toast.value = { type, text };
  setTimeout(() => (toast.value = null), 3000);
}

watch(selectedPcsId, () => {
  if (items.value.length > 0) fetchSnapshots();
});

onMounted(refresh);

// ── KPI 卡片组件(内联定义,带通俗讲解 MetricInfo) ──
const KpiCard = _dc({
  name: 'KpiCard',
  props: {
    value: { type: String, required: true },
    unit: { type: String, default: '' },
    label: { type: String, required: true },
    sub: { type: String, default: '' },
    tone: { type: String, default: 'idle' },
    color: { type: String, default: '' },
    hint: { type: Object as () => Explainer, default: null },
  },
  setup(props) {
    return () =>
      h('div', {
        class:
          'rounded-lg border bg-[var(--background-card)] p-3 flex flex-col gap-1 relative '
          + (props.tone === 'danger' ? 'border-[var(--function-error)]/40'
            : props.tone === 'warning' ? 'border-[var(--function-warning)]/40'
            : props.tone === 'success' ? 'border-[var(--function-success)]/40'
            : 'border-[var(--border-light)]'),
      }, [
        h('div', { class: 'flex items-center gap-1 text-xs text-[var(--text-tertiary)]' }, [
          h('span', props.label),
          props.hint ? h(MetricInfo, { title: props.hint.title, explain: props.hint.explain, formula: props.hint.formula }) : null,
        ]),
        h('div', { class: 'mt-0.5 flex items-baseline gap-1' }, [
          h('span', {
            class: 'font-mono text-xl tabular-nums',
            style: props.color ? { color: props.color } : { color: 'var(--text-primary)' },
          }, props.value),
          props.unit ? h('span', { class: 'text-xs text-[var(--text-tertiary)]' }, props.unit) : null,
        ]),
        props.sub ? h('div', { class: 'text-[10px] text-[var(--text-tertiary)]' }, props.sub) : null,
      ]);
  },
});
</script>

<style scoped>
.strategy-btn {
  height: 2rem;
  padding: 0 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  transition: all 0.15s;
  cursor: pointer;
}
.strategy-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.strategy-btn:not(:disabled):hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
</style>
