/**
 * Judge 评分理由结构化解析工具。
 *
 * Judge（qwen3.7-plus）返回的 comment 格式：
 *   **优点**
 *   - 做得好的方面
 *   **问题工具**
 *   - 步骤 #N: 问题描述
 *   **综合建议**
 *   - 改进方向
 *   **评分：X**
 *
 * 本模块按 \n** 边界切分 comment，按关键词给每段打 type，
 * 并从「问题工具」段提取步骤编号引用，供工具时间轴高亮使用。
 */

export interface CommentSection {
  type: 'strengths' | 'problems' | 'suggestions' | 'score' | 'other';
  title: string;          // e.g. "优点", "问题工具"
  items: string[];        // bullet 行（已去前缀 "- "）
  stepRefs?: number[];    // 问题工具段里的 `#N` 引用
}

export interface ParsedComment {
  sections: CommentSection[];
  raw: string;            // 原始 comment（兜底用）
}

interface ProblemMark {
  dim: string;
  desc: string;
}

// ── 关键词 → type 映射 ──
const TYPE_MAP: [string, CommentSection['type']][] = [
  ['优点', 'strengths'],
  ['问题工具', 'problems'],
  ['问题', 'problems'],
  ['综合建议', 'suggestions'],
  ['建议', 'suggestions'],
  ['评分', 'score'],
];

function classifyTitle(rawTitle: string): CommentSection['type'] {
  const t = rawTitle.trim();
  for (const [keyword, type] of TYPE_MAP) {
    if (t.includes(keyword)) return type;
  }
  return 'other';
}

/**
 * 解析 judge comment 为结构化段。
 *
 * 按 `\n**` 边界切分；首段（第一个 `**` 之前）丢弃（通常是空或废话）。
 * 每段格式：`**标题**\n- item1\n- item2`。
 *
 * 如果未检测到结构化标记（无 `**优点**` 或 `**问题工具**`），
 * 返回单个 `other` 段以保留兼容性。
 */
export function parseJudgeComment(comment: string | undefined | null): ParsedComment {
  const result: ParsedComment = { sections: [], raw: comment || '' };
  if (!comment) return result;

  // 检测是否为结构化 markdown
  const isStructured = comment.includes('**优点**') || comment.includes('**问题工具**');
  if (!isStructured) {
    result.sections.push({
      type: 'other',
      title: '',
      items: [comment],
    });
    return result;
  }

  // 按 \n** 切分（保留 ** 在每段开头）
  const blocks = comment.split(/\n(?=\*\*)/);
  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    // 提取标题：`**标题**` 或 `**标题：X**`
    const titleMatch = trimmed.match(/^\*\*(.+?)\*\*/);
    if (!titleMatch) continue;

    const rawTitle = titleMatch[1].trim();
    const type = classifyTitle(rawTitle);

    // 标题之后的内容
    const afterTitle = trimmed.slice(titleMatch[0].length).trim();

    // 提取 bullet 行（"- xxx" 开头）
    const items: string[] = [];
    const stepRefs: number[] = [];

    // 先按换行 split，过滤空行和纯标题行
    const lines = afterTitle.split('\n');
    for (const line of lines) {
      let item = line.trim();
      // 去掉行首 "- "
      if (item.startsWith('- ')) {
        item = item.slice(2).trim();
      } else if (item.startsWith('-')) {
        item = item.slice(1).trim();
      }
      if (!item) continue;

      // 跳过可能是下一个 ** 段的行
      if (item.startsWith('**')) continue;

      items.push(item);

      // 提取步骤编号 #N
      const nums = item.match(/#(\d+)/g);
      if (nums) {
        for (const n of nums) {
          const stepNum = Number(n.slice(1));
          if (!stepRefs.includes(stepNum)) {
            stepRefs.push(stepNum);
          }
        }
      }
    }

    if (items.length > 0 || type === 'score') {
      // score 段可能没有 bullets，用 rawTitle 本身作为 item
      if (type === 'score' && items.length === 0) {
        // rawTitle 格式："评分：4" 或 "评分: 4"
        const scoreVal = rawTitle.replace(/^评分\s*[:：]\s*/, '').trim();
        items.push(scoreVal || rawTitle);
      }
    }

    if (items.length > 0) {
      result.sections.push({
        type,
        title: rawTitle,
        items,
        stepRefs: type === 'problems' && stepRefs.length > 0 ? stepRefs : undefined,
      });
    }
  }

  return result;
}

/**
 * 提取 judge comment 中「问题工具」段的步骤编号 → 问题描述。
 *
 * 返回 Map<stepNumber, description>。
 */
export function extractProblemSteps(comment: string | undefined | null): Map<number, string> {
  const result = new Map<number, string>();
  if (!comment) return result;

  const parsed = parseJudgeComment(comment);
  for (const section of parsed.sections) {
    if (section.type !== 'problems') continue;
    for (const item of section.items) {
      const nums = item.match(/#(\d+)/g);
      if (!nums) continue;
      // 描述：去掉 "步骤 #N、#M:" 前缀
      const desc = item.replace(/^步骤\s*#\d+(?:、#\d+)*\s*[:：]\s*/, '').trim();
      for (const n of nums) {
        const stepNum = Number(n.slice(1));
        if (!result.has(stepNum)) {
          result.set(stepNum, desc);
        }
      }
    }
  }
  return result;
}

/**
 * 聚合 trace 内所有评分的问题步骤：stepIndex(1-based) → [{dim, desc}]。
 *
 * 用于工具时间轴高亮问题步骤。
 */
export function traceProblemSteps(scores: { name: string; comment?: string | null }[]): Map<number, ProblemMark[]> {
  const merged = new Map<number, ProblemMark[]>();
  for (const sc of scores) {
    if (!sc.comment) continue;
    for (const [step, desc] of extractProblemSteps(sc.comment)) {
      if (!merged.has(step)) merged.set(step, []);
      merged.get(step)!.push({ dim: sc.name, desc });
    }
  }
  return merged;
}
