<template>
  <svg class="w-full h-auto min-w-[920px]" viewBox="0 0 1200 660" xmlns="http://www.w3.org/2000/svg"
       role="img" aria-label="Agent 运行时结构图">
    <defs>
      <marker id="rt-arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
      </marker>
      <marker id="rt-arw-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#3b82f6" />
      </marker>
    </defs>

    <!-- ── 横切关注点（记忆 / 中间件） ── -->
    <rect x="190" y="46" width="250" height="152" rx="10" stroke-dasharray="6 5"
          style="fill:var(--background-gray-main);stroke:var(--border-dark)" stroke-width="1.2" />
    <text x="315" y="72" text-anchor="middle" font-size="11.5" font-weight="600" style="fill:var(--text-primary)">横切关注点</text>
    <text x="315" y="96" text-anchor="middle" font-size="10.5" style="fill:var(--text-secondary)">两层记忆</text>
    <text x="315" y="114" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">AGENTS.md（全局）</text>
    <text x="315" y="132" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">CONTEXT.md（会话级）</text>
    <text x="315" y="158" text-anchor="middle" font-size="10.5" style="fill:var(--text-secondary)">SSE 监控中间件</text>
    <text x="315" y="176" text-anchor="middle" font-size="10.5" style="fill:var(--text-secondary)">offload 中间件（大结果落盘）</text>

    <!-- ── 用户 ── -->
    <rect x="20" y="280" width="150" height="100" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="95" y="318" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">用户 / 业务人员</text>
    <text x="95" y="340" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">自然语言意图</text>
    <text x="95" y="358" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">"明天保产线"</text>

    <line x1="170" y1="330" x2="186" y2="330" stroke="#94a3b8" stroke-width="1.8" marker-end="url(#rt-arw)" />

    <!-- ── Lead Agent ── -->
    <rect x="190" y="250" width="250" height="160" rx="10"
          fill="#6366f1" fill-opacity="0.12" stroke="#6366f1" stroke-opacity="0.55" stroke-width="1.3" />
    <text x="315" y="278" text-anchor="middle" font-size="13" font-weight="600" style="fill:var(--text-primary)">Lead Agent</text>
    <text x="315" y="302" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">意图理解 · 目标拆解</text>
    <text x="315" y="322" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">路由到领域子 Agent</text>
    <text x="315" y="342" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">收口整合 · 对用户答复</text>
    <text x="315" y="372" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">不亲自调领域工具</text>
    <text x="315" y="390" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">不替子 Agent 做决策</text>

    <!-- 记忆 → Lead 虚线 -->
    <line x1="315" y1="198" x2="315" y2="246" stroke="#94a3b8" stroke-width="1.3" stroke-dasharray="5 5" marker-end="url(#rt-arw)" />

    <line x1="440" y1="330" x2="476" y2="330" stroke="#3b82f6" stroke-width="1.8" marker-end="url(#rt-arw-b)" />
    <text x="458" y="320" text-anchor="middle" font-size="10" style="fill:var(--text-tertiary)">task</text>

    <!-- ── 领域子 Agent ── -->
    <rect x="480" y="250" width="260" height="160" rx="10"
          fill="#3b82f6" fill-opacity="0.12" stroke="#3b82f6" stroke-opacity="0.55" stroke-width="1.3" />
    <text x="610" y="278" text-anchor="middle" font-size="13" font-weight="600" style="fill:var(--text-primary)">领域子 Agent（business）</text>
    <text x="610" y="302" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">在自己领域内自主决策</text>
    <text x="610" y="322" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">挑选工具 · 决定调用顺序</text>
    <text x="610" y="342" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">产出专业结论并回传</text>
    <text x="610" y="372" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">边界清晰：只干本领域的活</text>
    <text x="610" y="390" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">超出范围 → 交回主 Agent</text>

    <!-- 子 Agent → 右侧四个能力 -->
    <path d="M740,278 C 765,278 765,112 786,112" fill="none" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#rt-arw)" />
    <path d="M740,300 C 765,300 765,240 786,240" fill="none" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#rt-arw)" />
    <path d="M740,325 C 765,325 765,366 786,366" fill="none" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#rt-arw)" />
    <path d="M740,360 C 765,360 765,494 786,494" fill="none" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#rt-arw)" />

    <!-- ── 右侧：工具 / LP / Skills / Sandbox ── -->
    <rect x="790" y="60" width="375" height="104" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="810" y="86" font-size="12" font-weight="600" style="fill:var(--text-primary)">领域工具（StructuredTool / @tool）</text>
    <text x="810" y="108" font-size="10.5" style="fill:var(--text-secondary)">optimize_dispatch · account_revenue</text>
    <text x="810" y="127" font-size="10.5" style="fill:var(--text-secondary)">device_management · 场站 / 预测查询 …</text>
    <text x="810" y="148" font-size="10.5" style="fill:var(--text-tertiary)">原子操作；schema + docstring 由框架自动注入</text>

    <rect x="790" y="190" width="375" height="100" rx="10"
          fill="#14b8a6" fill-opacity="0.13" stroke="#14b8a6" stroke-opacity="0.6" stroke-width="1.3" />
    <text x="810" y="216" font-size="12" font-weight="600" style="fill:var(--text-primary)">LP 求解器 · scipy HiGHS</text>
    <text x="810" y="238" font-size="10.5" style="fill:var(--text-secondary)">硬约束：SOC / 倍率 / 循环 / 需量 / 防逆流</text>
    <text x="810" y="257" font-size="10.5" style="fill:var(--text-secondary)">目标：省钱 / 保电池 / 绿电 / 防逆流 权重可叠加</text>
    <text x="810" y="278" font-size="10.5" style="fill:var(--text-tertiary)">★ 关键数字来自这里，LLM 只翻译与解释</text>

    <line x1="977" y1="164" x2="977" y2="186" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#rt-arw)" />

    <rect x="790" y="316" width="375" height="100" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="810" y="342" font-size="12" font-weight="600" style="fill:var(--text-primary)">Skills（内置 + 外置）</text>
    <text x="810" y="364" font-size="10.5" style="fill:var(--text-secondary)">docx / pdf / pptx / xlsx · feishu</text>
    <text x="810" y="383" font-size="10.5" style="fill:var(--text-secondary)">一整套打包能力，粒度大于单个工具</text>
    <text x="810" y="404" font-size="10.5" style="fill:var(--text-tertiary)">用户可自行安装 / 屏蔽 / 删除</text>

    <line x1="977" y1="416" x2="977" y2="438" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#rt-arw)" />

    <rect x="790" y="442" width="375" height="118" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="810" y="468" font-size="12" font-weight="600" style="fill:var(--text-primary)">CompositeBackend → sandbox</text>
    <text x="810" y="490" font-size="10.5" style="fill:var(--text-secondary)">FilesystemBackend（内置 skills，只读）</text>
    <text x="810" y="509" font-size="10.5" style="fill:var(--text-secondary)">FilteredFilesystemBackend（用户 skills）</text>
    <text x="810" y="528" font-size="10.5" style="fill:var(--text-secondary)">FullSandboxBackend（文件 / 命令 → REST 代理）</text>
    <text x="810" y="549" font-size="10.5" style="fill:var(--text-tertiary)">按会话隔离执行目录 · 熔断器 · 连接池</text>

    <!-- ── 子 Agent → HITL ── -->
    <line x1="610" y1="414" x2="610" y2="456" stroke="#f59e0b" stroke-width="1.8" marker-end="url(#rt-arw)" />
    <text x="622" y="440" font-size="10" style="fill:var(--text-tertiary)">命中需审批的工具</text>

    <rect x="190" y="460" width="550" height="150" rx="10"
          fill="#f59e0b" fill-opacity="0.13" stroke="#f59e0b" stroke-opacity="0.6" stroke-width="1.3" />
    <text x="465" y="487" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">HITL 人工审批（影响硬件的动作）</text>
    <text x="465" y="511" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">子 Agent 声明 interrupt_on → LangGraph 触发 interrupt</text>
    <text x="465" y="531" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">yield approval_required → 落库 pending → 前端决策</text>
    <text x="465" y="551" text-anchor="middle" font-size="10.8" style="fill:var(--text-secondary)">approve / reject / edit / respond → resume 续流执行</text>
    <text x="465" y="578" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">checkpointer 持久化中断状态，后端重启后仍可恢复</text>
    <text x="465" y="597" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">★ 影响硬件的动作不直连，必须过人工审批 + 落库留痕</text>
  </svg>
</template>
