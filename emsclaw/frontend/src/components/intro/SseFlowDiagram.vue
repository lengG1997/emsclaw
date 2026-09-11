<template>
  <svg class="w-full h-auto min-w-[900px]" viewBox="0 0 1140 620" xmlns="http://www.w3.org/2000/svg"
       role="img" aria-label="一次请求的核心流程时序图">
    <defs>
      <marker id="seq-arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#3b82f6" />
      </marker>
      <marker id="seq-arw-ret" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
      </marker>
    </defs>

    <!-- ── 参与者 ── -->
    <g font-size="12.5" font-weight="600" text-anchor="middle" style="fill:var(--text-primary)">
      <rect x="30"  y="22" width="150" height="52" rx="9" style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.3" />
      <text x="105" y="53">浏览器</text>

      <rect x="230" y="22" width="150" height="52" rx="9" style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.3" />
      <text x="305" y="45">SSE 端点</text>
      <text x="305" y="63" font-size="10.5" font-weight="400" style="fill:var(--text-tertiary)">请求协程</text>

      <rect x="440" y="22" width="150" height="52" rx="9" style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.3" />
      <text x="515" y="45">asyncio.Queue</text>
      <text x="515" y="63" font-size="10.5" font-weight="400" style="fill:var(--text-tertiary)">按 session_id 注册</text>

      <rect x="650" y="22" width="150" height="52" rx="9" style="fill:var(--background-card);stroke:var(--border-main)" stroke-width="1.3" />
      <text x="725" y="45">Worker</text>
      <text x="725" y="63" font-size="10.5" font-weight="400" style="fill:var(--text-tertiary)">生产者协程</text>

      <rect x="860" y="22" width="190" height="52" rx="9" fill="#6366f1" fill-opacity="0.10" stroke="#6366f1" stroke-opacity="0.55" stroke-width="1.3" />
      <text x="955" y="45">Agent 运行时</text>
      <text x="955" y="63" font-size="10.5" font-weight="400" style="fill:var(--text-tertiary)">DeepAgents / LangGraph</text>
    </g>

    <!-- ── 生命线 ── -->
    <g stroke-dasharray="5 6" stroke-width="1.2" style="stroke:var(--border-dark)">
      <line x1="105" y1="78" x2="105" y2="580" />
      <line x1="305" y1="78" x2="305" y2="580" />
      <line x1="515" y1="78" x2="515" y2="580" />
      <line x1="725" y1="78" x2="725" y2="580" />
      <line x1="955" y1="78" x2="955" y2="580" />
    </g>

    <!-- ── 消息 ── -->
    <g stroke-width="1.8" font-size="11.5">
      <!-- 1 -->
      <line x1="105" y1="112" x2="300" y2="112" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="202" y="106" text-anchor="middle" class="seq-label">① POST /sessions/{id}/chat</text>

      <!-- 2 -->
      <line x1="305" y1="158" x2="510" y2="158" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="407" y="152" text-anchor="middle" class="seq-label">② 建会话级 Queue，挂到 _agent_queues[sid]</text>

      <!-- 3 (return) -->
      <line x1="300" y1="204" x2="110" y2="204" stroke="#94a3b8" stroke-dasharray="6 5" marker-end="url(#seq-arw-ret)" />
      <text x="205" y="198" text-anchor="middle" class="seq-label">③ 立即返回 EventSourceResponse（不等 worker）</text>

      <!-- 4 -->
      <line x1="725" y1="252" x2="950" y2="252" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="837" y="246" text-anchor="middle" class="seq-label">⑤ async for evt in arun_science_task_stream()</text>

      <!-- 5 (return) -->
      <line x1="950" y1="300" x2="730" y2="300" stroke="#94a3b8" stroke-dasharray="6 5" marker-end="url(#seq-arw-ret)" />
      <text x="840" y="294" text-anchor="middle" class="seq-label">模型思考 / 工具调用 / 计划变更 事件</text>

      <!-- 6 -->
      <line x1="725" y1="348" x2="520" y2="348" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="622" y="342" text-anchor="middle" class="seq-label">put_nowait(evt)</text>

      <!-- 7 -->
      <line x1="515" y1="396" x2="110" y2="396" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="312" y="390" text-anchor="middle" class="seq-label">④ 消费者 await queue.get() 订阅挂起（0 CPU）→ yield SSE</text>

      <!-- 8 -->
      <line x1="950" y1="444" x2="730" y2="444" stroke="#94a3b8" stroke-dasharray="6 5" marker-end="url(#seq-arw-ret)" />
      <text x="840" y="438" text-anchor="middle" class="seq-label">异步生成器耗尽（本轮结束）</text>

      <!-- 9 -->
      <line x1="725" y1="492" x2="520" y2="492" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="622" y="486" text-anchor="middle" class="seq-label">emit(done) + put_nowait(None) 哨兵</text>

      <!-- 10 -->
      <line x1="515" y1="540" x2="110" y2="540" stroke="#3b82f6" marker-end="url(#seq-arw)" />
      <text x="312" y="534" text-anchor="middle" class="seq-label">消费者 break → 校验后清理 _agent_queues[sid]</text>
    </g>

    <!-- ── 右侧旁注 ── -->
    <g font-size="10.5" style="fill:var(--text-tertiary)">
      <text x="1080" y="248">生产者</text>
      <text x="1080" y="264">逐事件拉取</text>
      <text x="1080" y="392">消费者</text>
      <text x="1080" y="408">订阅挂起</text>
    </g>
  </svg>
</template>

<style scoped>
.seq-label {
  fill: var(--text-secondary);
  paint-order: stroke;
  stroke: var(--background-gray-main);
  stroke-width: 4px;
  stroke-linejoin: round;
}
</style>
