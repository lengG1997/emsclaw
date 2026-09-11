// 场站总览页各指标/图表的通俗讲解文案(单一真相源)。
// 每条用最通俗易懂的话讲,让不懂 EMS 的人也能看懂。

export interface Explainer {
  title: string;
  explain: string;
  formula?: string; // 口径/计算说明(可选)
}

export const EXPLAINERS = {
  // ── EMS 导览 / 策略方向 ──
  whatIsEms: {
    title: 'EMS 是什么',
    explain:
      'EMS(能源管理系统)就是场站的"大脑":它盯着光伏发了多少电、负荷用了多少、电池还剩多少,'
      + '然后决定什么时候充电、什么时候放电,目标是让电费最低、设备最安全、光伏不浪费。',
  },
  // ── KPI 指标 ──
  totalPower: {
    title: '储能功率',
    explain: '所有 PCS 当前充放电功率之和(储能侧)。正数=正在充电(往电池里存电),负数=正在放电(电池往外供电),0=待机。注意与关口表的"关口净功率"区分:储能功率看电池在充/放,关口净功率看和电网的进出。',
  },
  totalCapacity: {
    title: '总储能容量',
    explain: '场站所有电池的额定容量之和(kWh)。就像电池桶的总大小,决定最多能存多少电。',
  },
  weightedSoc: {
    title: '加权 SOC',
    explain:
      '电池还剩多少电。把每台电池按容量大小加权平均出来的全站总电量百分比。'
      + '低于 20% 要重点看(快没电了),高于 90% 注意别过充。',
  },
  onlinePcs: {
    title: '在线 PCS',
    explain: '当前有最新运行数据的 PCS(变流器)台数。PCS 是把电池直流电转成交流电的"开关",在线才能充放电。',
  },
  importPower: {
    title: '当前下网功率',
    explain: '此刻从电网买的功率(kW)。数字越大,电费越高;储能放电或光伏发电时这个数会降下来。',
  },
  demand: {
    title: '当前需量',
    explain:
      '近 15 分钟从电网买电的平均功率。跟"申报需量"比,超过就要罚款。'
      + '占比越接近 100% 越危险,储能要在快超时放电顶上。',
  },
  revenue: {
    title: '今日收益',
    explain: '今天靠峰谷套利赚的钱(元)= 高峰放电卖的钱 − 低谷充电花的钱。负数说明今天还没到放电高峰或电价倒挂。',
  },
  tariffCurrent: {
    title: '当前电价时段',
    explain:
      '现在处于尖/峰/平/谷哪个电价档。谷段(便宜)适合充电,峰/尖段(贵)适合放电。'
      + 'EMS 就是卡着这个时段来调度的。',
  },

  // ── 图表 / 概念 ──
  loadForecast: {
    title: '负荷预测',
    explain: '未来 24 小时场站预计要用多少电(kW)。呈双峰:午峰和晚峰。决定储能什么时候要放电帮忙。',
  },
  pvForecast: {
    title: '光伏预测',
    explain: '未来 24 小时光伏预计发多少电(kW)。中午最高、夜间为 0。光伏多过负荷时多的电要存进电池(防逆流)。',
  },
  netLoad: {
    title: '净负荷',
    explain:
      '负荷减去光伏。正数=还差电、要从电网买;负数=光伏多出来了、可能往电网倒灌(逆流)。'
      + '负值越大,防逆流压力越大。',
  },
  meterFlow: {
    title: '关口表能量流',
    explain:
      '关口表是场站和电网之间的"电表"。下网=从电网买电,上网=往电网送电。'
      + '两条参考线:申报需量(下网超了罚款)和防逆流阈值(上网超了违规)。',
  },
  powerSocCurve: {
    title: '功率 / SOC 曲线',
    explain:
      '近 24 小时储能实际充放电功率(橙,正充负放)和电池电量 SOC(蓝)。'
      + '看实际运行和计划的吻合度,SOC 有没有越红线。',
  },
  chargeSchedule: {
    title: '充放电调度计划',
    explain: '今天 24 小时按电价时段安排的充放电时间表:低谷充电、高峰/尖峰放电、平段待机,实现削峰填谷与套利。',
  },
  dailyEnergy: {
    title: '日电量与收益',
    explain: '近几天每天的充电量、放电量和赚的钱。看储能是不是在稳定赚钱、有没有异常天。',
  },
  soc: {
    title: 'SOC(荷电状态)',
    explain: '电池当前的电量百分比,就像手机电量。保护带一般设在 10%-90%,超出会自动停。',
  },
  soh: {
    title: 'SOH(健康状态)',
    explain: '电池健康度。新电池 100%,越用越低。低于 80% 建议降额使用或更换。',
  },
  efficiency: {
    title: '效率',
    explain: 'PCS 转换效率:直流电变交流电的过程中,有多少能量被保留下来。越高越省。',
  },
  contractDemand: {
    title: '申报需量',
    explain: '跟电网公司报的"最大功率档位"(kW)。实际功率超过它要按超出部分交罚款,这是需量控制要守的线。',
  },
  antiReverseSetpoint: {
    title: '防逆流阈值',
    explain: '允许往电网送电(上网)的上限(kW)。光伏过剩时,上网功率不能超这个数,超了就是逆流违规。',
  },
  tariffPeriod: {
    title: '电价时段(尖峰平谷)',
    explain:
      '一天按电价分四档:尖(最贵)>峰>平>谷(最便宜)。EMS 的核心逻辑就是谷段充电、尖/峰段放电,赚中间差价。',
  },

  // ── 模型总览 / Langfuse 可观测性 ──
  modelOverviewIntro: {
    title: '模型总览是什么',
    explain:
      '把所有大模型调用汇总成一张图:调了多少次、用了多少字(token)、花了多少钱、快不快、出错过几次。'
      + '数据来自 Langfuse 可观测性平台,每次 Agent 跟大模型交互都会自动记录。',
  },
  modelFilter: {
    title: '模型筛选',
    explain:
      '选「全部模型」看整体,选某个具体模型则下方所有数字和趋势都只看它(模型之间的对比图会暂时隐藏)。'
      + '想对比哪个模型贵、哪个慢,先看「全部模型」下的对比图。',
  },
  totalCalls: {
    title: '总调用次数',
    explain:
      '大模型被叫起来干活的次数。每次回答、每轮思考都算一次。'
      + '次数突然暴涨,要看看是不是有任务在空转、或者提示词把一轮对话拆成了太多轮。',
  },
  sessionCount: {
    title: '会话数',
    explain:
      '发生了大模型调用的独立对话数。一个会话里可能有很多次调用。'
      + '会话多=用得多,但不一定=花钱多;花钱多少看「总成本」。',
  },
  totalTokens: {
    title: '总 Token',
    explain:
      '所有调用加起来读了+写了多少字(token)。1 个 token 约等于半个汉字。'
      + '这是衡量消耗的根本指标,token 越多越花钱。输入(读)通常远多于输出(写)。',
  },
  totalCost: {
    title: '总成本',
    explain:
      '按 Langfuse 后台配置的模型单价算出来的花费,单位美元。'
      + '显示 0 不是没花钱,而是还没在 Langfuse 的「模型管理」里配单价——配完就有了。',
  },
  p50Latency: {
    title: 'P50 延迟',
    explain:
      '把所有调用按快慢排好,正好在中间那一次的耗时。一半的调用比它快、一半比它慢。'
      + '代表「日常体验」——用户大多数时候等这么久。',
  },
  p95Latency: {
    title: 'P95 延迟',
    explain:
      '95% 的调用都比它快,只有 5% 更慢。代表「最差体验的下限」——'
      + '这个数高,说明偶尔会卡一下;P95 比 P50 高很多,说明偶尔有慢请求拖后腿。',
  },
  avgTtft: {
    title: '平均首字时间',
    explain:
      '从发出请求到大模型吐出第一个字要等多久(TTFT)。'
      + '等得久,用户会觉得「卡住了」;等得短,感觉「反应很快」。带思考过程的模型这个值通常更大。',
  },
  errorRate: {
    title: '错误率',
    explain:
      '调用失败(报错)的比例。健康应该接近 0。'
      + '飙高通常是模型服务挂了、超时、或请求超长被拒;点趋势图看是哪天开始出问题的。',
  },
  modelCallShare: {
    title: '模型调用量占比',
    explain:
      '每个模型被叫了多少次,看谁是主力。'
      + '如果某个不该常用的模型占比很高,可能是配置默认模型时选错了。',
  },
  modelTokenCost: {
    title: '模型 Token 与成本',
    explain:
      '每个模型花了多少字(token)、多少钱。找出最烧钱的模型。'
      + '同样调用次数下 token 高的模型,要么单价贵、要么单次读写得太多,值得优化提示词。',
  },
  modelLatency: {
    title: '模型延迟对比',
    explain:
      '每个模型快慢对比(P50 和 P95)。带思考过程的模型(如带 reasoning 的)通常更慢,这里看得最清楚。'
      + '选模型时在「贵但快」和「便宜但慢」之间权衡。',
  },
  modelTable: {
    title: '模型明细',
    explain:
      '每个模型一行:调用次数、token、成本、快慢、吞吐(每秒出多少字)、错误率。'
      + '点列头可以按需对比;吞吐高=单位时间产出多,适合大批量任务。',
  },
  trendCalls: {
    title: '调用量趋势',
    explain: '每天调用多少次,看用量是涨是跌。突然的尖峰常对应某次重任务或异常循环。',
  },
  trendTokens: {
    title: 'Token 与成本趋势',
    explain: '每天消耗的字数和花费。两条线对齐看,定位哪天突然烧钱、烧的是字数还是单价。',
  },
  trendLatency: {
    title: '延迟趋势',
    explain: '每天 P50 延迟。整体上扬说明模型响应在变慢,可能是服务负载升高或上下文越来越长。',
  },
  trendError: {
    title: '错误率趋势',
    explain: '每天出错比例。某天突然冒尖,去 Langfuse 那天的 trace 里看具体报错。',
  },

  // ── 质量评分 / LLM-as-judge ──
  scoreOverviewIntro: {
    title: '质量评分是什么',
    explain:
      '让一个大模型当"裁判",评估 Agent 在每一步对话中的工具调用质量——'
      + '工具选得对不对(tool_selection)、调用顺序是否合理(tool_order_reasoning)、'
      + '参数是否准确(argument_quality)、工具返回结果是否被正确用到最终回复(result_utilization)。'
      + '这叫 LLM-as-judge。分数由 Langfuse 的 evaluator 自动产生,每次对话打一次,汇总在这里看整体质量。',
  },
  judgeHow: {
    title: 'LLM 当裁判怎么打分',
    explain:
      '评判流程:把 Agent 的工具调用序列 + 用户的问题 + 一段评判标准,喂给"裁判模型",让它输出分数。'
      + '比规则灵活,能判断"工具选得对不对""顺序合不合理"这种难量化的点。但裁判本身也是模型,不是百分百准——'
      + '所以看趋势比看单条分数更有意义。',
  },
  scoreNameFilter: {
    title: '评分维度筛选',
    explain:
      '选「全部维度」看整体,选某个维度(如 tool_selection)则下方数字只看它(维度对比图会暂时隐藏)。'
      + '维度由你在 Langfuse 配 evaluator 时定义。',
  },
  scoreCount: {
    title: '评分次数',
    explain: '一共打了几次分。次数少说明 evaluator 刚配或对话还少;突然变多说明评分在稳定运行。',
  },
  avgScore: {
    title: '平均分',
    explain:
      '所有评分的平均值。分数高低看 evaluator 怎么设(有的 0~1,有的 0~5,有的 0~100)。'
      + '总体越高=回答质量越好。重点是看相对变化(涨了还是跌了),不是纠结绝对数字。',
  },
  scoreNameCount: {
    title: '评分维度数',
    explain: '从几个角度在打分(如"工具选型"+"调用顺序"=2 个维度)。维度多=评估更全面,但也更花裁判调用的钱。',
  },
  scoreModelCount: {
    title: '评分模型数',
    explain: '被评分的模型有几个。如果为 0,可能是评分挂在会话级没绑到具体模型——不影响看分,只是没法按模型拆。',
  },
  scoreByDimension: {
    title: '各维度平均分',
    explain: '每个评分维度的平均分对比。哪个维度低,就是 Agent 的短板,优先改进那个方向。',
  },
  scoreDistribution: {
    title: '评分分布',
    explain:
      '分数落在哪些区间。集中在高分=整体稳;出现一堆低分=有批质量差的问题回答,要去 Langfuse 查具体哪几条。',
  },
  scoreTrend: {
    title: '评分趋势',
    explain: '每天的平均分和评分次数。平均分下滑=质量在退步,可能提示词改坏了或数据分布变了,去对齐那天的改动。',
  },
  scoreByModel: {
    title: '按模型平均分',
    explain: '不同模型的评分对比。同样任务下分数高的模型回答更好——但注意模型可能跑的任务难度不同,别只看绝对值。',
  },
  scoreTable: {
    title: '评分维度明细',
    explain: '每个维度一行:打分次数、平均分。按需对比,找短板维度。',
  },
  // ── 评分会话视图 ──
  scoreTracesIntro: {
    title: '会话评分是什么',
    explain:
      '按会话(对话)列出 Agent 的每一条评分及理由。点开一条会话,能看到用户问了什么、Agent 答了什么、'
      + '裁判给了几分、为什么给这个分。比看汇总数字更细,方便定位"哪条对话答得不好、为什么不好"。',
  },
  scoreVersionFilter: {
    title: '版本筛选',
    explain:
      '改了提示词 / skill 后 bump AGENT_VERSION(环境变量),Langfuse trace 里就会带版本号 tag (v0.1)。'
      + '选不同版本对比同一阶段的分数,就能知道这次改动是变好还是变坏。',
  },
  scoreSessionList: {
    title: '会话列表',
    explain:
      '每行一次会话。按时间倒序。'
      + '点开能看到这次会话的所有评分维度(工具选型/调用顺序/参数质量/结果利用等)及裁判给出的中文理由。',
  },
  scoreReasoning: {
    title: '评分理由',
    explain:
      '裁判模型给出这个分数的中文解释。'
      + '理由由 LLM 自己写,可能含有对 Agent 行为的批评或建议,是定位"为什么扣分"的主要线索。',
  },

  // ── 技能评估(ExperimentComparePage 8 维度 + overall)──
  evalOverall: {
    title: '总通过率',
    explain:
      '这一版 skill 在所有测试样本上,8 个维度(tool_set/tool_order/subagent/tool_count/repeat_rate/'
      + 'tool_result_quality/tool_args_validity/tool_efficiency)通过率的简单平均。'
      + '数字越高=越成熟。0.8 以上算可用,0.5 以下说明大面积出问题。粗略概括,不替代看各维度细节——比如总分 0.7 但 subagent 只有 0.1,说明路由全是错的。',
    formula: 'mean(tool_set, tool_order, subagent, tool_count, repeat_rate, tool_result_quality, tool_args_validity, tool_efficiency) 各维度 pass_rate',
  },
  evalToolSet: {
    title: '工具集(tool_set)',
    explain:
      'Lead 在这条样本里用的工具集合是否正确——既没漏掉该用的(比如该调 get_station_snapshot 却没调),也没碰禁用的(比如用 write_file→execute 自己写代码试错,这是 Lead 不该干的事)。'
      + '每个样本的 expectedOutput 里写了 expected_tools(必用)和 forbidden_tools(禁用),通过=集合符合预期。',
    formula: 'expected_tools ⊆ actual 且 forbidden ∩ actual = ∅',
  },
  evalToolOrder: {
    title: '调用顺序(tool_order)',
    explain:
      '工具调用顺序是否合理。比如该先 get_station_snapshot 拿全量数据,再分析策略,不能反过来。'
      + '判定方式:expected_order 是 actual 调用序列的子序列(中间允许插别的工具)。'
      + '比如 expected=[read_file, execute],actual=[read_file, write_todos, execute] → 通过。',
    formula: 'expected_order 是 actual 的子序列(允许中间插入)',
  },
  evalSubagent: {
    title: '子 agent 路由(subagent)',
    explain:
      'Lead 是否把任务委派给了正确的领域专家(EmsStationExpert / PowerMarketExpert / DeviceManagementExpert 等)。'
      + 'Lead 的本职是路由 + 收口,不该自己干专业活。'
      + '失败=Lead 自己干了没委派,或委派给了错的专家(比如该给 PowerMarketExpert 的却给了 EmsStationExpert)。'
      + '每个样本标了 expected_subagent,null=不需要委派(直接答)。',
    formula: 'expected_subagent ∈ delegates.subagent_type',
  },
  evalToolCount: {
    title: '调用次数(tool_count)',
    explain:
      '工具调用总次数是否在预算内。每条样本标了 max_tool_calls(经验值,比如 14 次)。'
      + '超出=Lead 在反复试错,典型场景:write_file→execute 失败→改一下再试,这种循环说明 Lead 没想清楚就动手。'
      + '正常应该一次委派专家,专家内部用少量工具完成,Lead 自己几乎不调工具。',
    formula: 'len(actual_tool_calls) <= max_tool_calls',
  },
  evalRepeatRate: {
    title: '相邻重复率(repeat_rate)',
    explain:
      '相邻两次调用同一工具且参数结构相同(比如连续两次 get_station_snapshot 传一样参数)算重复。'
      + '分子=相邻重复对数,分母=工具调用总数减一。pass_rate 越高越好(高=没有无谓重复)。'
      + '低分=Lead 卡在某步反复试同一调用,典型症状是"模型在原地打转"。'
      + '注意:这里评的是"通过率"(ratio 是否 ≤ max_repeat_ratio),不是重复率本身——分数高=没怎么重复,不是重复多。',
    formula: '相邻重复对数 / max(len-1, 1) ≤ max_repeat_ratio(默认 0.2)',
  },
  evalToolResult: {
    title: '结果质量(tool_result_quality)',
    explain:
      '工具返回的结果是否正常——非空、不含错误标记(Error/Exception/Traceback/Failed)、未被截断。'
      + '空结果或报错说明工具执行出了问题,截断说明 offload 没生效或返回过长。'
      + '每个样本可以指定检查哪些工具(支持通配符如 get_*),并可分别开启 non_empty/no_error/not_truncated 检查。',
    formula: '通过检查的调用数 / 匹配的工具调用总数',
  },
  evalToolArgs: {
    title: '参数有效性(tool_args_validity)',
    explain:
      '工具调用传的参数是否正确——必需字段是否存在、字段类型对不对(如 station_id 该是 str 却传了 int)、'
      + '值域是否合理(如功率不超过额定值、station_id 长度在合理范围)。'
      + '每个样本可以为不同工具配置不同的检查规则,支持 required_fields/field_types/reasonable 三类约束。',
    formula: '通过检查的调用数 / 匹配的工具调用总数',
  },
  evalToolEfficiency: {
    title: '调用效率(tool_efficiency)',
    explain:
      '检测浪费模式——① read_file(path) 后立刻 write_file(path) 同一路径(读是多余的,应该直接写);'
      + '② 连续 ≥3 次 search/grep 类调用无中间 execute/write(在搜索上打转,应该先找再动)。'
      + '效率分 = 1 - 浪费权重/总调用,满分 1.0 = 没有浪费。低分说明 Agent 在做无用功。',
    formula: '1.0 - min(waste_weight / total_calls, 1.0)',
  },
} as const;

export type ExplainerKey = keyof typeof EXPLAINERS;
