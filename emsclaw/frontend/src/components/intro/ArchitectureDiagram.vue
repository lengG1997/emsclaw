<template>
  <svg class="w-full h-auto min-w-[880px]" viewBox="0 0 1200 600" xmlns="http://www.w3.org/2000/svg"
       role="img" aria-label="emsclaw 整体架构图">
    <defs>
      <marker id="arch-arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
      </marker>
      <marker id="arch-arw-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#3b82f6" />
      </marker>
    </defs>

    <!-- ── 浏览器 ── -->
    <rect x="430" y="26" width="340" height="96" rx="12"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.5" />
    <text x="600" y="58" text-anchor="middle" font-size="15" font-weight="600" style="fill:var(--text-primary)">浏览器 · Vue 3 SPA</text>
    <text x="600" y="80" text-anchor="middle" font-size="11.5" style="fill:var(--text-tertiary)">Vite dev · :5173 · SSE + REST 客户端</text>
    <text x="600" y="101" text-anchor="middle" font-size="11.5" style="fill:var(--text-tertiary)">对话 · 总览 · 审批 · 技能 · 工具 · 质量评分</text>

    <line x1="600" y1="122" x2="600" y2="166" stroke="#3b82f6" stroke-width="2" marker-end="url(#arch-arw-b)" />
    <text x="612" y="149" font-size="11" style="fill:var(--text-secondary)">POST /sessions/{id}/chat → SSE 事件流</text>

    <!-- ── backend 容器 ── -->
    <rect x="120" y="166" width="960" height="188" rx="14"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.5" />
    <text x="144" y="192" font-size="13.5" font-weight="600" style="fill:var(--text-primary)">backend · FastAPI :12001</text>
    <text x="144" y="209" font-size="11" style="fill:var(--text-tertiary)">auth · sessions · Agent SSE · devices · forecasts · approvals</text>

    <!-- REST 路由 -->
    <rect x="144" y="220" width="300" height="116" rx="10"
          style="fill:var(--background-gray-main);stroke:var(--border-light)" stroke-width="1" />
    <text x="294" y="246" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">route / controller / service</text>
    <text x="294" y="268" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">薄 HTTP 层 + 业务逻辑</text>
    <text x="294" y="290" text-anchor="middle" font-size="11" style="fill:var(--text-tertiary)">db/ 异步 ORM · mapper/ 同步</text>
    <text x="294" y="312" text-anchor="middle" font-size="11" style="fill:var(--text-tertiary)">entity/ 跨层 DTO（前后端共享枚举）</text>

    <!-- Agent 运行时 -->
    <rect x="464" y="220" width="592" height="116" rx="10"
          fill="#6366f1" fill-opacity="0.10" stroke="#6366f1" stroke-opacity="0.55" stroke-width="1.2" />
    <text x="760" y="245" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">Agent 运行时 · DeepAgents 0.6.x（LangGraph 内核）</text>
    <text x="760" y="267" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">Lead Agent（意图理解 / 路由 / 收口） → 领域子 Agent（自主决策）</text>
    <text x="760" y="289" text-anchor="middle" font-size="11" style="fill:var(--text-tertiary)">工具 + Skills + 两层记忆 + SSE 监控 / offload 中间件</text>
    <text x="760" y="311" text-anchor="middle" font-size="11" style="fill:var(--text-tertiary)">thread_id → Postgres checkpointer（重启可恢复） · HITL 审批</text>

    <!-- backend 下行箭头 -->
    <line x1="235" y1="354" x2="235" y2="424" stroke="#94a3b8" stroke-width="2" marker-end="url(#arch-arw)" />
    <text x="245" y="382" font-size="11" style="fill:var(--text-secondary)">REST 代理</text>
    <text x="245" y="398" font-size="11" style="fill:var(--text-tertiary)">文件 / 命令 / 工具执行</text>

    <line x1="475" y1="354" x2="475" y2="424" stroke="#94a3b8" stroke-width="2" marker-end="url(#arch-arw)" />
    <text x="485" y="390" font-size="11" style="fill:var(--text-secondary)">SQLAlchemy async</text>

    <line x1="955" y1="424" x2="955" y2="354" stroke="#94a3b8" stroke-width="2" marker-end="url(#arch-arw)" />
    <text x="945" y="390" text-anchor="end" font-size="11" style="fill:var(--text-secondary)">任务触发 · 调 /api/v1/chat</text>

    <line x1="820" y1="493" x2="850" y2="493" stroke="#94a3b8" stroke-width="2" marker-end="url(#arch-arw)" />
    <text x="835" y="480" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">Celery broker</text>

    <!-- ── 执行 / 调度层 ── -->
    <rect x="130" y="428" width="210" height="120" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="235" y="456" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">sandbox · :18080</text>
    <text x="235" y="478" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">远程代码执行</text>
    <text x="235" y="497" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">+ 文件系统沙箱</text>
    <text x="235" y="521" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">DeepAgents backend</text>

    <rect x="370" y="428" width="210" height="120" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="475" y="456" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">PostgreSQL 16 · :5433</text>
    <text x="475" y="478" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">共享库 ai_agent</text>
    <text x="475" y="497" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">backend + task-service</text>
    <text x="475" y="521" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">会话 / 设备 / 预测</text>
    <text x="475" y="537" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">审批记录 / checkpoint</text>

    <rect x="610" y="428" width="210" height="120" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="715" y="456" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">Redis 7</text>
    <text x="715" y="478" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">Celery broker</text>
    <text x="715" y="497" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">任务队列 / 定时信号</text>
    <text x="715" y="521" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">仅 task-service 使用</text>

    <rect x="850" y="428" width="210" height="120" rx="10"
          style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.2" />
    <text x="955" y="456" text-anchor="middle" font-size="12.5" font-weight="600" style="fill:var(--text-primary)">scheduler_api · :12002</text>
    <text x="955" y="478" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">FastAPI + Celery</text>
    <text x="955" y="497" text-anchor="middle" font-size="11" style="fill:var(--text-secondary)">+ croniter 调度</text>
    <text x="955" y="521" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">自然语言 → crontab</text>
    <text x="955" y="537" text-anchor="middle" font-size="10.5" style="fill:var(--text-tertiary)">定时执行流水线</text>
  </svg>
</template>
