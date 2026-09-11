<template>
  <div class="flex flex-col h-full w-full overflow-hidden">
    <!-- ── Masthead ── -->
    <div class="flex-shrink-0 border-b border-[var(--border-main)] bg-[var(--background-card)]">
      <div class="px-6 py-4 max-w-[1240px] mx-auto flex items-end justify-between gap-4 flex-wrap">
        <div class="flex items-end gap-4">
          <div class="flex flex-col gap-0.5">
            <div class="flex items-center gap-2.5">
              <span class="size-2 rounded-full bg-[var(--function-success)]"></span>
              <h1 class="text-lg font-semibold tracking-tight text-[var(--text-primary)]">项目介绍</h1>
            </div>
            <span class="text-[11px] text-[var(--text-tertiary)] ml-[18px]">emsclaw · 为什么用 DeepAgents 做 EMS 调度策略</span>
          </div>
        </div>
        <nav class="flex items-center gap-1 flex-wrap">
          <button v-for="s in SECTIONS" :key="s.id" @click="goto(s.id)" class="intro-nav-btn">
            {{ s.label }}
          </button>
        </nav>
      </div>
    </div>

    <!-- ── Body ── -->
    <div ref="scrollEl" class="flex-1 overflow-y-auto bg-[var(--background-gray-main)]">
      <!-- 共享 SVG marker 定义（inline SVG 的 id 是文档级作用域，此处定义一次供下方各图引用） -->
      <svg width="0" height="0" style="position:absolute" aria-hidden="true">
        <defs>
          <marker id="route-arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
          </marker>
        </defs>
      </svg>
      <div class="max-w-[1240px] mx-auto p-6 pt-4 space-y-5">

        <!-- ═══ 1. Hero ═══ -->
        <section id="sec-hero" class="intro-card overflow-hidden">
          <div class="hero-grad px-6 py-7">
            <div class="flex items-start gap-4 flex-wrap">
              <div class="size-12 rounded-2xl bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 flex-shrink-0">
                <Sparkles :size="22" class="text-white" />
              </div>
              <div class="flex-1 min-w-[280px]">
                <h2 class="text-xl font-bold text-[var(--text-primary)] tracking-tight">emsclaw</h2>
                <p class="text-[13px] text-[var(--text-secondary)] mt-1.5 leading-relaxed">
                  基于 <b class="text-[var(--text-primary)]">FastAPI + LangGraph + DeepAgents</b> 的 EMS 多智能体平台。
                  把一个由 DeepAgents 驱动的 Agent 运行时嵌进后端，用 SSE 把"模型思考 / 工具调用 / 计划变更 / 最终回复"实时推给前端，
                  配合远程 sandbox 执行代码、Celery 做定时调度。
                </p>
                <p class="text-[13px] mt-2.5 leading-relaxed font-medium text-[var(--text-primary)]">
                  一句话：把能源系统的操作界面，从「专业工程师的控制台」变成「业务人员的对话框」。
                </p>
              </div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-2.5 mt-5">
              <div v-for="s in HERO_STATS" :key="s.label" class="rounded-lg bg-[var(--background-card)]/70 border border-[var(--border-light)] px-3 py-2.5">
                <div class="text-[10px] text-[var(--text-tertiary)]">{{ s.label }}</div>
                <div class="text-[13px] font-semibold text-[var(--text-primary)] mt-0.5">{{ s.value }}</div>
              </div>
            </div>
          </div>
        </section>

        <!-- ═══ 2. 痛点 ═══ -->
        <section id="sec-pain" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">01</span>
            <span class="intro-title">要解决的痛点</span>
            <span class="intro-sub">光储园区的调度决策，已经超出人工调度员的认知带宽</span>
          </div>
          <div class="px-4 pb-4 pt-1">
            <p class="text-[12px] text-[var(--text-tertiary)] leading-relaxed mb-3">
              电源侧（光伏）波动不可控、负荷侧越来越挑剔、储能侧有寿命约束、关口表侧既要压需量又要防逆流。
              把它们捏在一起做最优决策，传统基于规则的 EMS 做不到。
            </p>
            <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
              <div v-for="(p, i) in PAINS" :key="p.title" class="pain-card">
                <div class="flex items-center gap-2">
                  <span class="pain-idx">{{ i + 1 }}</span>
                  <span class="text-[12.5px] font-semibold text-[var(--text-primary)]">{{ p.title }}</span>
                </div>
                <p class="text-[11.5px] text-[var(--text-tertiary)] leading-relaxed mt-1.5">{{ p.desc }}</p>
                <p class="text-[11px] text-[var(--text-secondary)] leading-relaxed mt-1.5 pl-2 border-l-2 border-[var(--border-dark)]">
                  {{ p.conflict }}
                </p>
              </div>
            </div>
            <div class="mt-3 rounded-lg bg-[var(--background-gray-main)] px-3.5 py-2.5 text-[11.5px] leading-relaxed text-[var(--text-tertiary)]">
              <b class="text-[var(--text-secondary)]">共同指向：</b>
              业务人员用自然语言下达意图，系统自主完成「意图识别 → 目标拆解 → 约束校验 → 策略生成 → 审批下发 → 执行监测 → 收益核算」闭环。
              这正是把 Agent 嵌入 EMS 的代际特征。
            </div>
          </div>
        </section>

        <!-- ═══ 3. 三种做策略的方式（核心） ═══ -->
        <section id="sec-compare" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">02</span>
            <span class="intro-title">三种做策略的方式</span>
            <span class="intro-sub">同一个需求，三条技术路线给出完全不同的实现形态</span>
          </div>
          <div class="px-4 pb-4 pt-1">
            <div class="rounded-lg bg-[var(--background-gray-main)] px-3.5 py-3 mb-4">
              <div class="text-[11px] text-[var(--text-tertiary)] mb-1">需求示例</div>
              <div class="text-[12.5px] text-[var(--text-primary)] font-medium">
                「明天产线加急，帮我出一套储能充放电策略，别让关口表需量超线。」
              </div>
            </div>

            <!-- 三张路线卡 -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div v-for="r in ROUTES" :key="r.key" class="route-card" :class="{ 'route-card-active': r.active }">
                <div class="flex items-center gap-2">
                  <span class="route-badge" :class="r.active ? 'route-badge-on' : ''">{{ r.tag }}</span>
                  <span class="text-[13px] font-semibold text-[var(--text-primary)]">{{ r.name }}</span>
                </div>

                <div class="route-fig mt-3">
                  <!-- A: 直线式 -->
                  <svg v-if="r.key === 'A'" viewBox="0 0 300 92" class="w-full h-auto">
                    <g font-size="10" text-anchor="middle" style="fill:var(--text-secondary)">
                      <rect x="4" y="30" width="66" height="32" rx="6" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="37" y="50">前端表单</text>
                      <line x1="72" y1="46" x2="92" y2="46" style="stroke:var(--text-disable)" stroke-width="1.5" marker-end="url(#route-arw)" />
                      <rect x="94" y="24" width="112" height="44" rx="6" style="fill:var(--background-gray-main);stroke:var(--text-disable)" stroke-width="1.2" />
                      <text x="150" y="43">Java 规则表</text>
                      <text x="150" y="57" font-size="9" style="fill:var(--text-tertiary)">if-else 写死</text>
                      <line x1="208" y1="46" x2="228" y2="46" style="stroke:var(--text-disable)" stroke-width="1.5" marker-end="url(#route-arw)" />
                      <rect x="230" y="30" width="66" height="32" rx="6" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="263" y="50">写库下发</text>
                    </g>
                  </svg>
                  <!-- B: 固定流程图 -->
                  <svg v-else-if="r.key === 'B'" viewBox="0 0 300 92" class="w-full h-auto">
                    <g font-size="9.5" text-anchor="middle" style="fill:var(--text-secondary)">
                      <rect x="2" y="34" width="58" height="26" rx="13" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="31" y="51">解析</text>
                      <line x1="61" y1="47" x2="73" y2="47" style="stroke:var(--text-disable)" stroke-width="1.4" marker-end="url(#route-arw)" />
                      <rect x="75" y="34" width="58" height="26" rx="13" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="104" y="51">预测</text>
                      <line x1="134" y1="47" x2="146" y2="47" style="stroke:var(--text-disable)" stroke-width="1.4" marker-end="url(#route-arw)" />
                      <rect x="148" y="34" width="58" height="26" rx="13" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="177" y="51">生成</text>
                      <line x1="207" y1="47" x2="219" y2="47" style="stroke:var(--text-disable)" stroke-width="1.4" marker-end="url(#route-arw)" />
                      <rect x="221" y="34" width="58" height="26" rx="13" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="250" y="51">下发</text>
                      <path d="M177,60 L177,78 L104,78 L104,62" fill="none" style="stroke:var(--function-warning)" stroke-width="1.2" stroke-dasharray="4 3" marker-end="url(#route-arw)" />
                      <text x="140" y="89" font-size="8.5" style="fill:var(--function-warning)">图里没画就卡住</text>
                    </g>
                  </svg>
                  <!-- C: Agent 中心辐射 -->
                  <svg v-else viewBox="0 0 300 92" class="w-full h-auto">
                    <g font-size="9.5" text-anchor="middle" style="fill:var(--text-secondary)">
                      <circle cx="150" cy="46" r="26" fill="#6366f1" fill-opacity="0.16" stroke="#6366f1" stroke-opacity="0.6" stroke-width="1.3" />
                      <text x="150" y="43" font-size="10" font-weight="600" style="fill:var(--text-primary)">Agent</text>
                      <text x="150" y="55" font-size="8.5" style="fill:var(--text-tertiary)">自主决策</text>
                      <rect x="18" y="10" width="76" height="24" rx="12" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="56" y="26">LP 求解器</text>
                      <rect x="206" y="10" width="76" height="24" rx="12" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="244" y="26">业务工具</text>
                      <rect x="18" y="58" width="76" height="24" rx="12" style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1" />
                      <text x="56" y="74">Skills</text>
                      <rect x="206" y="58" width="76" height="24" rx="12" fill="#f59e0b" fill-opacity="0.14" stroke="#f59e0b" stroke-opacity="0.6" stroke-width="1" />
                      <text x="244" y="74">HITL 审批</text>
                      <line x1="124" y1="40" x2="96" y2="26" style="stroke:var(--text-disable)" stroke-width="1.2" marker-end="url(#route-arw)" />
                      <line x1="176" y1="40" x2="204" y2="26" style="stroke:var(--text-disable)" stroke-width="1.2" marker-end="url(#route-arw)" />
                      <line x1="124" y1="52" x2="96" y2="66" style="stroke:var(--text-disable)" stroke-width="1.2" marker-end="url(#route-arw)" />
                      <line x1="176" y1="52" x2="204" y2="66" style="stroke:#f59e0b" stroke-width="1.2" marker-end="url(#route-arw)" />
                    </g>
                  </svg>
                </div>

                <div class="mt-3 rounded-md bg-[var(--background-gray-main)] px-2.5 py-2">
                  <div class="text-[10px] text-[var(--text-tertiary)]">本质</div>
                  <div class="text-[12px] font-medium text-[var(--text-primary)] mt-0.5">{{ r.essence }}</div>
                </div>

                <div class="mt-2.5">
                  <div class="text-[10.5px] font-medium text-[var(--function-success)] mb-1">强项</div>
                  <ul class="space-y-0.5">
                    <li v-for="x in r.pros" :key="x" class="text-[11px] text-[var(--text-secondary)] leading-relaxed flex gap-1.5">
                      <span class="text-[var(--function-success)]">+</span><span>{{ x }}</span>
                    </li>
                  </ul>
                </div>
                <div class="mt-2.5">
                  <div class="text-[10.5px] font-medium text-[var(--function-error)] mb-1">代价</div>
                  <ul class="space-y-0.5">
                    <li v-for="x in r.cons" :key="x" class="text-[11px] text-[var(--text-secondary)] leading-relaxed flex gap-1.5">
                      <span class="text-[var(--function-error)]">−</span><span>{{ x }}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            <!-- 三句话结论 -->
            <div class="mt-4 rounded-lg border border-[var(--border-main)] overflow-hidden">
              <div class="px-3.5 py-2.5 bg-[var(--background-gray-main)] text-[11.5px] font-medium text-[var(--text-primary)]">
                一句话说清差别
              </div>
              <div class="divide-y divide-[var(--border-light)]">
                <div v-for="(l, i) in ONE_LINERS" :key="i" class="px-3.5 py-2.5 flex items-start gap-3">
                  <span class="route-badge flex-shrink-0" :class="i === 2 ? 'route-badge-on' : ''">{{ ['A', 'B', 'C'][i] }}</span>
                  <span class="text-[12px] leading-relaxed" :class="i === 2 ? 'text-[var(--text-primary)] font-medium' : 'text-[var(--text-secondary)]'">{{ l }}</span>
                </div>
              </div>
            </div>

            <!-- 横向对比表 -->
            <div class="mt-4 rounded-lg border border-[var(--border-main)] overflow-hidden">
              <div class="px-3.5 py-2.5 border-b border-[var(--border-light)] bg-[var(--background-gray-main)]">
                <span class="text-[11.5px] font-medium text-[var(--text-primary)]">横向对比</span>
              </div>
              <div class="overflow-x-auto">
                <table class="w-full text-[11px] border-collapse min-w-[720px]">
                  <thead>
                    <tr class="text-[var(--text-tertiary)]">
                      <th class="text-left font-medium py-2 px-3 whitespace-nowrap">维度</th>
                      <th class="text-left font-medium py-2 px-3">A · 传统企业应用</th>
                      <th class="text-left font-medium py-2 px-3">B · LangGraph 工作流</th>
                      <th class="text-left font-medium py-2 px-3 cmp-col-c">C · DeepAgents（本平台）</th>
                    </tr>
                  </thead>
                  <tbody class="align-top">
                    <tr v-for="row in CMP_TABLE" :key="row.dim" class="border-t border-[var(--border-light)]">
                      <td class="py-2 px-3 whitespace-nowrap font-medium text-[var(--text-primary)]">{{ row.dim }}</td>
                      <td class="py-2 px-3 text-[var(--text-secondary)]">{{ row.a }}</td>
                      <td class="py-2 px-3 text-[var(--text-secondary)]">{{ row.b }}</td>
                      <td class="py-2 px-3 cmp-col-c text-[var(--text-primary)]">{{ row.c }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>

        <!-- ═══ 4. 为什么选 DeepAgents ═══ -->
        <section id="sec-why" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">03</span>
            <span class="intro-title">为什么选 DeepAgents</span>
            <span class="intro-sub">继承 LangGraph 的工程能力，但不把流程写死</span>
          </div>
          <div class="px-4 pb-4 pt-1 space-y-3">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              <div v-for="w in WHYS" :key="w.title" class="why-card">
                <div class="flex items-center gap-2">
                  <component :is="w.icon" :size="14" class="text-[#6366f1] flex-shrink-0" />
                  <span class="text-[12.5px] font-semibold text-[var(--text-primary)]">{{ w.title }}</span>
                </div>
                <p class="text-[11.5px] text-[var(--text-tertiary)] leading-relaxed mt-1.5">{{ w.desc }}</p>
              </div>
            </div>
            <div class="rounded-lg border border-[var(--border-main)] px-3.5 py-3">
              <div class="text-[11.5px] font-medium text-[var(--text-primary)] mb-2">关键：不画死控制流，但把安全边界焊死</div>
              <div class="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                <div v-for="g in GUARDRAILS" :key="g.t" class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-2">
                  <div class="text-[11px] font-medium text-[var(--text-primary)]">{{ g.t }}</div>
                  <div class="text-[10.5px] text-[var(--text-tertiary)] leading-relaxed mt-1">{{ g.d }}</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ═══ 5. 应用场景（重点） ═══ -->
        <section id="sec-scene" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">04</span>
            <span class="intro-title">应用场景</span>
            <span class="intro-sub">选它不是因为"新技术更酷"，而是问题形态正好落在 A / B 的能力死角上</span>
          </div>
          <div class="px-4 pb-4 pt-1 space-y-4">
            <!-- 该用 -->
            <div>
              <div class="flex items-center gap-2 mb-2">
                <CircleCheck :size="15" class="text-[var(--function-success)]" />
                <span class="text-[12.5px] font-semibold text-[var(--text-primary)]">✅ 该用的场景（价值集中区）</span>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
                <div v-for="s in SCENES_YES" :key="s.title" class="scene-card scene-yes">
                  <div class="text-[12px] font-semibold text-[var(--text-primary)]">{{ s.title }}</div>
                  <p class="text-[11px] text-[var(--text-tertiary)] leading-relaxed mt-1">{{ s.why }}</p>
                  <div class="mt-1.5 flex flex-wrap gap-1">
                    <span v-for="t in s.tools" :key="t" class="chip chip-on">{{ t }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 不该用 -->
            <div>
              <div class="flex items-center gap-2 mb-2">
                <CircleSlash :size="15" class="text-[var(--function-error)]" />
                <span class="text-[12.5px] font-semibold text-[var(--text-primary)]">⛔ 不该用的场景（边界与代价，如实标注）</span>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                <div v-for="s in SCENES_NO" :key="s.title" class="scene-card scene-no">
                  <div class="text-[12px] font-semibold text-[var(--text-primary)]">{{ s.title }}</div>
                  <p class="text-[11px] text-[var(--text-tertiary)] leading-relaxed mt-1">
                    更合适：<b class="text-[var(--text-secondary)]">{{ s.better }}</b>
                  </p>
                </div>
              </div>
            </div>

            <!-- 三条硬边界 -->
            <div class="rounded-lg border-l-[3px] border-l-[var(--function-warning)] bg-[var(--background-gray-main)] px-3.5 py-3">
              <div class="text-[11.5px] font-medium text-[var(--text-primary)] mb-2">三条硬边界</div>
              <ol class="space-y-1.5">
                <li v-for="(b, i) in BOUNDARIES" :key="i" class="text-[11.5px] leading-relaxed text-[var(--text-tertiary)] flex gap-2">
                  <span class="text-[var(--text-secondary)] font-medium flex-shrink-0">{{ i + 1 }}.</span>
                  <span v-html="b"></span>
                </li>
              </ol>
            </div>
          </div>
        </section>

        <!-- ═══ 6. 架构图 ═══ -->
        <section id="sec-arch" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">05</span>
            <span class="intro-title">整体架构</span>
            <span class="intro-sub">浏览器 · FastAPI 后端（含 Agent 运行时）· sandbox · Postgres · Redis · 调度服务</span>
          </div>
          <div class="px-4 pb-4 pt-1">
            <div class="overflow-x-auto rounded-lg border border-[var(--border-light)] bg-[var(--background-gray-main)] p-3">
              <ArchitectureDiagram />
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-2.5 mt-3">
              <div v-for="s in SERVICES" :key="s.name" class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-2">
                <div class="flex items-center gap-1.5">
                  <span class="font-mono text-[11px] font-medium text-[var(--text-primary)]">{{ s.name }}</span>
                  <span class="chip">{{ s.port }}</span>
                </div>
                <div class="text-[10.5px] text-[var(--text-tertiary)] mt-1">{{ s.role }}</div>
              </div>
            </div>
          </div>
        </section>

        <!-- ═══ 7. Agent 运行时 ═══ -->
        <section id="sec-runtime" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">06</span>
            <span class="intro-title">Agent 运行时结构</span>
            <span class="intro-sub">Lead 只做路由与收口，子 Agent 在自己领域内自主决策，硬约束与审批兜底</span>
          </div>
          <div class="px-4 pb-4 pt-1">
            <div class="overflow-x-auto rounded-lg border border-[var(--border-light)] bg-[var(--background-gray-main)] p-3">
              <AgentRuntimeDiagram />
            </div>
            <div class="mt-3 rounded-lg bg-[var(--background-gray-main)] px-3.5 py-2.5 text-[11.5px] leading-relaxed text-[var(--text-tertiary)]">
              <b class="text-[var(--text-secondary)]">分层要点：</b>
              ① Lead 负责意图理解 + 路由 + 收口，不亲自调领域工具；
              ② 子 Agent 只声明"我处理什么 / 不处理什么"，不做路由（没有全局视图）；
              ③ 关键数字来自 LP 求解器，LLM 不编造；
              ④ 影响硬件的动作一律走 HITL 审批 + 落库留痕。
            </div>
          </div>
        </section>

        <!-- ═══ 8. 核心流程图 ═══ -->
        <section id="sec-flow" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">07</span>
            <span class="intro-title">核心流程：一次请求的 SSE 管道</span>
            <span class="intro-sub">单线程事件循环 · 生产者/消费者解耦 · await 订阅挂起（等待不烧 CPU）· 哨兵关闭</span>
          </div>
          <div class="px-4 pb-4 pt-1">
            <div class="overflow-x-auto rounded-lg border border-[var(--border-light)] bg-[var(--background-gray-main)] p-3">
              <SseFlowDiagram />
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5 mt-3">
              <div class="rounded-md bg-[var(--background-gray-main)] px-3 py-2.5">
                <div class="text-[11.5px] font-medium text-[var(--text-primary)]">为什么这么设计</div>
                <ul class="mt-1.5 space-y-1">
                  <li v-for="x in FLOW_NOTES" :key="x" class="text-[11px] text-[var(--text-tertiary)] leading-relaxed flex gap-1.5">
                    <span class="text-[var(--text-disable)]">·</span><span>{{ x }}</span>
                  </li>
                </ul>
              </div>
              <div class="rounded-md bg-[var(--background-gray-main)] px-3 py-2.5">
                <div class="text-[11.5px] font-medium text-[var(--text-primary)]">HITL 审批闭环</div>
                <div class="mt-1.5 space-y-1 text-[11px] text-[var(--text-tertiary)] leading-relaxed">
                  <div>① 子 Agent 声明 <code class="intro-code">interrupt_on</code>，工具命中触发 LangGraph interrupt</div>
                  <div>② Runner 检测并 yield <code class="intro-code">approval_required</code>（带 action_requests / review_configs）</div>
                  <div>③ Worker 落库 pending + 标 AWAITING_APPROVAL，前端渲染审批卡</div>
                  <div>④ 决策 → 合成 <code class="intro-code">Command(resume)</code> 续流执行，工具结果回填 ApprovalRecord</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ═══ 9. 真实界面截图 ═══ -->
        <section id="sec-shots" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">08</span>
            <span class="intro-title">真实界面</span>
            <span class="intro-sub">以下均为前端实际运行截图（Docker 最新代码）</span>
          </div>
          <div class="px-4 pb-4 pt-1 space-y-4">
            <div v-for="sh in SHOTS" :key="sh.src" class="shot-card">
              <div class="flex items-center justify-between gap-3 px-3.5 py-2.5 border-b border-[var(--border-light)]">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="chip">{{ sh.tag }}</span>
                  <span class="text-[12px] font-semibold text-[var(--text-primary)] truncate">{{ sh.title }}</span>
                </div>
                <span class="text-[10.5px] text-[var(--text-tertiary)] truncate flex-shrink-0">{{ sh.note }}</span>
              </div>
              <div class="p-2.5 bg-[var(--background-gray-main)]">
                <img :src="sh.src" :alt="sh.title" class="w-full rounded-md border border-[var(--border-light)] block" loading="lazy" />
              </div>
              <div class="px-3.5 py-2.5 text-[11px] text-[var(--text-tertiary)] leading-relaxed">{{ sh.desc }}</div>
            </div>
            <div v-if="shotsMissing.length" class="rounded-md bg-[var(--background-gray-main)] px-3 py-2 text-[11px] text-[var(--text-tertiary)]">
              说明：未捕获到的截图（{{ shotsMissing.join('、') }}）说明该场景当前无数据，页面已跳过展示。
            </div>
          </div>
        </section>

        <!-- ═══ 10. 技术栈 + 评测 ═══ -->
        <section id="sec-stack" class="intro-card">
          <div class="intro-head">
            <span class="intro-num">09</span>
            <span class="intro-title">技术栈与质量兜底</span>
            <span class="intro-sub">模型输出有不确定性，所以把评测当一等公民</span>
          </div>
          <div class="px-4 pb-4 pt-1">
            <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
              <div v-for="s in STACK" :key="s.layer" class="rounded-md bg-[var(--background-gray-main)] px-2.5 py-2">
                <div class="text-[10.5px] text-[var(--text-tertiary)]">{{ s.layer }}</div>
                <div class="text-[11.5px] text-[var(--text-primary)] mt-0.5 leading-relaxed">{{ s.tech }}</div>
              </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5 mt-3">
              <div v-for="e in EVALS" :key="e.t" class="rounded-lg border border-[var(--border-main)] px-3 py-2.5">
                <div class="flex items-center gap-2">
                  <component :is="e.icon" :size="13" class="text-[var(--text-secondary)]" />
                  <span class="text-[12px] font-semibold text-[var(--text-primary)]">{{ e.t }}</span>
                  <span class="chip">{{ e.when }}</span>
                </div>
                <p class="text-[11px] text-[var(--text-tertiary)] leading-relaxed mt-1.5">{{ e.d }}</p>
                <div class="mt-1.5 flex flex-wrap gap-1">
                  <span v-for="d in e.dims" :key="d" class="chip chip-on">{{ d }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div class="h-2"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import {
  Sparkles, Layers, Route, ShieldCheck, Gauge, CircleCheck, CircleSlash,
  LineChart, FlaskConical, GitBranch, Database,
} from 'lucide-vue-next';
import ArchitectureDiagram from '@/components/intro/ArchitectureDiagram.vue';
import SseFlowDiagram from '@/components/intro/SseFlowDiagram.vue';
import AgentRuntimeDiagram from '@/components/intro/AgentRuntimeDiagram.vue';

const SECTIONS = [
  { id: 'sec-pain', label: '痛点' },
  { id: 'sec-compare', label: '三种方式' },
  { id: 'sec-why', label: '为什么选它' },
  { id: 'sec-scene', label: '应用场景' },
  { id: 'sec-arch', label: '架构' },
  { id: 'sec-runtime', label: '运行时' },
  { id: 'sec-flow', label: '核心流程' },
  { id: 'sec-shots', label: '真实界面' },
  { id: 'sec-stack', label: '技术栈' },
];

const scrollEl = ref<HTMLElement | null>(null);
function goto(id: string) {
  const el = scrollEl.value?.querySelector('#' + id);
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

const HERO_STATS = [
  { label: '架构', value: 'FastAPI + Agent 运行时' },
  { label: '内核', value: 'DeepAgents 0.6.x (LangGraph)' },
  { label: '决策内核', value: 'LP 求解 + 约束建模' },
  { label: '推送方式', value: 'SSE 事件流' },
];

const PAINS = [
  {
    title: '多目标冲突天然打架',
    desc: '省钱要多放电 → 加剧电池退化；保电池要少循环 → 错过套利；最大化绿电消纳 → 可能触发逆流；防逆流要限光伏 → 弃光。',
    conflict: '固定权重或单目标算法难以动态平衡；光伏骤降或负荷突变时，硬编码规则容易陷入局部最优。',
  },
  {
    title: '储能优化不是"低充高放"',
    desc: '单日收益最大化往往透支电池寿命：每次激进充放都在加速老化，缩短的资产寿命可能远超当天套利收益。',
    conflict: 'SOC 范围、充放电倍率、保修循环数、最小充放时间构成约束网；核心矛盾是"今天多赚"还是"未来少衰"。',
  },
  {
    title: '光伏防逆流：从"硬切"到"柔性"',
    desc: '自发自用模式下哪怕少量反送都算违规，部分地区要求零逆流，超标触发考核罚款。',
    conflict: '传统方案直接切断光伏逆变器：弃光、断路器频繁分合闸触头烧蚀、分闸瞬间负载可能断电。',
  },
  {
    title: '需量管理：超线即罚',
    desc: '两部制电价下，关口表月度最大需量超过申报档位，按超出部分收需量电费。',
    conflict: '负荷突变（产线启停、空调负荷跳变）会瞬间冲高需量，人工盯曲线 + 手动放电根本跟不上。',
  },
  {
    title: '业务语言 ↔ 控制指令割裂',
    desc: '生产主管说"明天下午订单加急，优先保障产线 A"；能源操作员要把它翻译成"14:00-18:00 储能放电功率不低于 XX kW"。',
    conflict: '中间这道翻译，既慢又容易出错；对操作员经验依赖极强。',
  },
];

const ROUTES = [
  {
    key: 'A',
    tag: 'A',
    name: '传统企业应用做策略',
    essence: '策略 = 代码（规则表 / if-else）',
    active: false,
    pros: ['确定、可控、低延迟、易审计', '规则长期稳定时最省心省钱'],
    cons: ['每条新诉求 = 一次发版', '多目标冲突只能写死权重', '业务语言靠人工翻译成参数'],
  },
  {
    key: 'B',
    tag: 'B',
    name: 'LangGraph 工作流做策略',
    essence: '策略 = 固定流程图（控制流编码期画死）',
    active: false,
    pros: ['流程可视化、节点可插拔', '有状态，checkpoint 可续跑', '可嵌 LLM 节点做意图或文案'],
    cons: ['图里没画的路径走不通', 'LLM 只是节点，无自主决策权', '需求增长 → 条件分支爆炸'],
  },
  {
    key: 'C',
    tag: 'C',
    name: 'DeepAgents 做策略（本平台）',
    essence: '策略 = Agent 推理 + 工具（数学模型）硬约束',
    active: true,
    pros: ['控制流运行期生成，不预先画死', '继承 LangGraph 全部工程能力', '改约束 / 换句话即可，无需发版', '走图外路径天然支持（重规划 / 换工具 / 拆子任务）'],
    cons: ['延迟与成本高于纯 Java 接口', '需配套约束校验与评测体系兜底'],
  },
];

const ONE_LINERS = [
  'A 把策略写成代码：规则进 Java，改一次发一次版。',
  'B 把策略画成流程图：控制流在编码期定死，运行期只按图走。',
  'C 让 Agent 在「工具 + 约束」围出的安全区里自主找路，人只定边界，不画路径。',
];

const CMP_TABLE = [
  { dim: '策略载体', a: 'if-else / 规则表（代码）', b: '预定义的有向图', c: 'Agent 推理 + 工具 / 约束' },
  { dim: '控制流谁定', a: '开发者（编码期）', b: '开发者（编码期画死）', c: '模型（运行期生成）' },
  { dim: 'LLM 的角色', a: '通常没有', b: '图里一个节点，无自主权', c: '决策主体，工具是它的手' },
  { dim: '新增一条诉求', a: '改代码 → 发版', b: '加节点 / 改边 → 发版', c: '改约束 / Skill，或换句话，无需发版' },
  { dim: '多目标冲突', a: '写死权重', b: '写死在节点逻辑里', c: '权重由策略组合推导，算得出权衡解' },
  { dim: '走图外的路径', a: '不支持', b: '要改图', c: '天然支持（重规划 / 换工具 / 拆子任务）' },
  { dim: '业务语言直连', a: '人工翻译填表', b: '需专门做意图节点', c: 'Lead 原生意图理解 + 路由' },
  { dim: '人机协作', a: '权限靠账号', b: '可加 interrupt 节点', c: 'HITL 审批内建 + 落库留痕' },
  { dim: '算不出来时', a: '抛异常 / 静默给默认计划', b: '图里没画就卡住', c: '给诊断（冲突约束 / 物理下限 / 建议动作），上报而非自行改参' },
  { dim: '可观测', a: '翻日志', b: '图执行 trace', c: '全链路 trace + 工具调用质量评分' },
  { dim: '延迟 / 成本', a: '最低', b: '中', c: '较高（约十几秒 + token 成本）' },
  { dim: '适合', a: '规则稳定、要解释、低延迟', b: '流程清晰、步骤固定的编排', c: '多目标权衡、需求多变、要解释的日前决策' },
];

const WHYS = [
  { icon: GitBranch, title: '不画死控制流，路径运行期生成', desc: '先查设备还是先拉预测、这个工具不好用换一个、要不要拆成两个子任务——这些不需要人预先穷举，Agent 按上下文自己定。' },
  { icon: Layers, title: '继承 LangGraph 的工程能力', desc: 'checkpoint 跨重启续跑、HITL interrupt 中断恢复、astream_events v2 事件流、子图与状态管理，一样都不少——只是不把流程写死。' },
  { icon: Route, title: 'Lead 只路由，子 Agent 只干活', desc: '父子职责严格切开：Lead 做意图理解 + 分发 + 收口，不越权调领域工具；子 Agent 只声明自己的边界，不做全局路由。' },
  { icon: Gauge, title: '决策内核是数学模型，不是提示词', desc: 'LP 求解器（scipy HiGHS）负责算出功率 / SOC / 需量 / 收益，LLM 只做意图理解、约束翻译与解释说明——不编造数值。' },
  { icon: Database, title: '两层记忆 + 结果落盘', desc: '全局 AGENTS.md + 会话级 CONTEXT.md；工具结果过大时自动落盘并把历史里的原文替换为摘要 + 文件路径，避免多轮被截断丢信息。' },
  { icon: ShieldCheck, title: '风险动作不直连，必过审批', desc: '影响硬件的动作声明 interrupt_on，触发 LangGraph interrupt，人工审批后才 resume 执行，全程落库留痕。' },
];

const GUARDRAILS = [
  { t: '工具签名 = 能力边界', d: '工具 docstring 与 schema 由框架自动注入，Agent 只能在注册给自己的工具范围内活动。' },
  { t: '约束校验 = 物理边界', d: 'SOC / 倍率 / 循环 / 需量 / 防逆流硬约束在 LP 层强制，不可行时返回物理下限与冲突约束。' },
  { t: '双层评测 = 质量边界', d: '在线 LLM-as-Judge（4 维度）+ 离线 Code Evaluator（8 维度），把"跑偏"挡在发版前。' },
];

const SCENES_YES = [
  { title: '多目标权衡的日前调度', why: '省钱 / 保电池 / 绿电 / 防逆流同时打架，需要算出权衡解、并能向业务解释依据。', tools: ['策略组合', 'LP 求解', '诊断'] },
  { title: '需求频繁变化的策略', why: '按订单排产调整口径，改约束 / 换句话即可，不必为每条诉求发版。', tools: ['约束建模', 'Skill'] },
  { title: '自然语言下达的业务意图', why: '"保产线""少折腾电池"这类业务语言直连，省掉人工翻译成参数的环节。', tools: ['Lead 意图路由'] },
  { title: '高风险动作需人工确认', why: '下发充放电、配置设备等影响硬件的动作，必须人工审批后才执行。', tools: ['interrupt', 'ApprovalRecord'] },
  { title: '多方案并列对比', why: '一次出 2~3 个方案并排比指标 + 标最优，让业务点选采用。', tools: ['多方案', '最优标记'] },
  { title: '需要可观测与持续评测', why: '全链路 trace + 双层评测，决策链路可回溯、可回归验证。', tools: ['Langfuse judge', 'code evaluator'] },
];

const SCENES_NO = [
  { title: '毫秒级实时闭环控制（一次调频、快速功率跟随）', better: '底层控制器 / 边缘设备' },
  { title: '规则长期稳定、无需解释、要求极低延迟', better: 'Java 规则引擎（路线 A）' },
  { title: '步骤完全固定、不需要动态分支的流程编排', better: 'LangGraph 工作流（路线 B）' },
  { title: '要求绝对确定性、无 token 成本预算', better: '传统实现' },
];

const BOUNDARIES = [
  '<b class="text-[var(--text-secondary)]">关键数字不来自模型</b>——功率 / SOC / 需量 / 收益全部由 LP 求解器（scipy HiGHS）算出，LLM 只负责意图理解、约束翻译与解释，不编造数值。',
  '<b class="text-[var(--text-secondary)]">模型输出有不确定性</b>——靠约束校验、<code class="intro-code">sanity_check</code>、在线 judge + 离线 evaluator 双层评测兜底；这也是把评测体系当作一等公民的原因。',
  '<b class="text-[var(--text-secondary)]">延迟与成本高于纯 Java 接口</b>——一次调度决策约十几秒、有 token 成本，只适合需要权衡与解释的日前决策，不适合毫秒级实时闭环控制。',
];

const SERVICES = [
  { name: 'frontend', port: ':5173', role: 'Vue 3 SPA（Vite dev）' },
  { name: 'backend', port: ':12001 → 8000', role: 'FastAPI：auth / sessions / Agent SSE / devices / forecasts' },
  { name: 'sandbox', port: ':18080 → 8080', role: '远程代码执行 + 文件系统沙箱（DeepAgents backend）' },
  { name: 'scheduler_api', port: ':12002 → 8001', role: 'FastAPI 任务调度 API' },
  { name: 'postgres', port: ':5433 → 5432', role: '共享 DB `ai_agent`（backend + task-service）' },
  { name: 'redis', port: '—', role: 'task-service 的 Celery broker' },
];

const FLOW_NOTES = [
  '端点建会话级 Queue 并按 session_id 挂到全局注册表，让 worker 能凭 sid 找到。',
  '端点起后台生产者协程后不等待，立即返回 EventSourceResponse。',
  '消费者 await queue.get() 是订阅挂起，不是轮询——队列空时协程睡眠 0 CPU，worker put 时由 asyncio 唤醒。',
  'worker 的 async for 自然耗尽后进 finally：先 emit(done)，再 put 哨兵 None，最后清理任务表。',
  '消费者拿到哨兵 → break 收摊，用 is 校验后移除队列（防止误删后续新连接换上的新 queue）。',
];

const STACK = [
  { layer: '后端', tech: 'Python 3.13 · FastAPI · SQLAlchemy(async) · LangGraph · DeepAgents 0.6.x' },
  { layer: '前端', tech: 'Vue 3 · Vite · TypeScript · Tailwind · reka-ui · xterm · monaco' },
  { layer: '任务调度', tech: 'FastAPI · Celery · croniter · Redis' },
  { layer: '沙箱', tech: 'Python 3.12 · 远程代码执行 + 文件系统沙箱' },
  { layer: '数据', tech: 'PostgreSQL 16 · Redis 7' },
  { layer: '工具链', tech: 'uv · Docker Compose · pytest' },
];

const EVALS = [
  {
    t: '在线 · LLM-as-Judge',
    when: '生产自动评分',
    icon: LineChart,
    d: '每条 Agent 对话自动触发，评测工具调用质量（1-5 分），前端「质量评分」页实时查看。',
    dims: ['工具选择', '顺序合理性', '参数质量', '结果利用'],
  },
  {
    t: '离线 · Code Evaluator',
    when: '发版前验证',
    icon: FlaskConical,
    d: '对 golden dataset 跑 run_experiment，用于变更发版前的回归验证。',
    dims: ['工具集合', '工具顺序', '子 Agent 路由', '工具用量', '重复率', '结果质量', '参数有效性', '工具效率'],
  },
];

const ALL_SHOTS = [
  { tag: '总览', title: '场站总览 · 策略入口', src: '/intro-shots/01-station-overview.png', file: '01-station-overview.png',
    note: '一次决策的起点', desc: '顶部一排就是"生成策略"的入口：场站分析、赶产保供、峰谷省钱、光伏消纳、保电池延寿、收益报告。点任意一个即以自然语言创建会话，Agent 接管后续全部流程。下方是 KPI、预测曲线、关口表能量流与储能运行状态。' },
  { tag: '策略', title: '生成策略 · 调度方案卡片', src: '/intro-shots/06-strategy-card.png', file: '06-strategy-card.png',
    note: 'Lead 委派 → 领域子 Agent', desc: '用户点"峰谷省钱"后，Lead Agent 解析意图并委派给 DispatchPlanningExpert 子智能体；右侧实时显示推理过程与任务进度，左侧以卡片展示子 Agent 的 PLAN、工具调用与思考。' },
  { tag: '审批', title: '子智能体 HITL 审批卡片', src: '/intro-shots/07-hitl-approval.png', file: '07-hitl-approval.png',
    note: '影响硬件的动作必过审批', desc: '子 Agent 命中需审批的工具（create_device / configure_network / apply_schedule）时触发 LangGraph interrupt，Runner yield approval_required，前端渲染黄色审批卡片：按工具展示 name + description + args JSON 预览，按 allowed_decisions 渲染 Approve / Reject 按钮，右下角还有"Auto-approve all"开关。' },
  { tag: '台账', title: '审批台账 · 跨会话追溯', src: '/intro-shots/02-approvals.png', file: '02-approvals.png',
    note: '分页 + 状态筛选', desc: '跨会话的审批台账：按 status（pending / decided / auto_approved）、发起人、会话筛选，每行展示工具名、子 Agent、状态徽章、决策与审批人，实现"谁批的、批了什么"全程留痕。' },
  { tag: '智能体', title: '智能体注册表', src: '/intro-shots/03-agents.png', file: '03-agents.png',
    note: 'Lead + 3 个领域子 Agent', desc: '可插拔的 Agent profile 与领域子 Agent 注册表：首席协调 Agent（Lead）负责路由与收口；StationDataExpert、DeviceOperationExpert、DispatchPlanningExpert 各领域子 Agent 在 import 时自注册，并把提示词版本化到 Langfuse。' },
  { tag: '技能', title: 'Skills 能力', src: '/intro-shots/04-skills.png', file: '04-skills.png',
    note: '一整套打包能力', desc: '内置 skills（docx / pdf / pptx / xlsx / feishu）加上用户自行安装的外置 skills；粒度大于单个工具，用于整套流程。' },
];

const shotsMissing = ref<string[]>([]);
const SHOTS = ref(ALL_SHOTS);

onMounted(async () => {
  // 只展示实际存在的截图，避免出现裂图
  const checks = await Promise.all(
    ALL_SHOTS.map(async (s) => {
      try {
        const res = await fetch(s.src, { method: 'HEAD' });
        return res.ok ? s : null;
      } catch {
        return null;
      }
    })
  );
  SHOTS.value = checks.filter(Boolean) as typeof ALL_SHOTS;
  shotsMissing.value = ALL_SHOTS.filter((s) => !checks.includes(s)).map((s) => s.title);
});
</script>

<style scoped>
.intro-card {
  background: var(--background-card);
  border: 1px solid var(--border-main);
  border-radius: 10px;
  overflow: hidden;
}
.intro-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--border-light);
  flex-wrap: wrap;
}
.intro-num {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-brand);
  background: var(--fill-blue);
  border-radius: 5px;
  padding: 2px 7px;
}
.intro-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.intro-sub {
  font-size: 11px;
  color: var(--text-tertiary);
}
.intro-nav-btn {
  font-size: 11.5px;
  padding: 5px 10px;
  border-radius: 6px;
  color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
}
.intro-nav-btn:hover {
  background: var(--background-gray-main);
  color: var(--text-primary);
}
.hero-grad {
  background: linear-gradient(135deg, var(--fill-blue) 0%, transparent 55%),
              linear-gradient(315deg, rgba(99, 102, 241, 0.07) 0%, transparent 50%);
}
.pain-card {
  background: var(--background-gray-main);
  border-radius: 8px;
  padding: 11px 12px;
}
.pain-idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: var(--fill-blue);
  color: var(--text-brand);
  font-size: 10.5px;
  font-weight: 700;
  flex-shrink: 0;
}
.route-card {
  border: 1px solid var(--border-main);
  border-radius: 9px;
  padding: 12px;
  display: flex;
  flex-direction: column;
}
.route-card-active {
  border-color: rgba(99, 102, 241, 0.55);
  background: rgba(99, 102, 241, 0.05);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.15);
}
.route-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: var(--background-gray-main);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.route-badge-on {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
}
.route-fig {
  background: var(--background-gray-main);
  border-radius: 7px;
  padding: 8px 6px;
}
.cmp-col-c {
  background: rgba(99, 102, 241, 0.05);
  font-weight: 500;
}
.why-card {
  border: 1px solid var(--border-main);
  border-radius: 8px;
  padding: 11px 12px;
}
.scene-card {
  border-radius: 8px;
  padding: 11px 12px;
  border-left: 3px solid transparent;
}
.scene-yes {
  background: rgba(37, 186, 59, 0.06);
  border-left-color: var(--function-success);
}
.scene-no {
  background: rgba(242, 90, 90, 0.06);
  border-left-color: var(--function-error);
}
.chip {
  display: inline-block;
  font-size: 10px;
  padding: 1.5px 6px;
  border-radius: 4px;
  background: var(--background-gray-main);
  color: var(--text-tertiary);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.chip-on {
  background: rgba(99, 102, 241, 0.10);
  color: #6366f1;
}
.dark .chip-on {
  color: #a5b4fc;
}
.shot-card {
  border: 1px solid var(--border-main);
  border-radius: 9px;
  overflow: hidden;
}
.intro-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10.5px;
  background: var(--background-gray-main);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--text-secondary);
}
</style>
