"""
验证正则能否从 judge 输出提取所有步骤编号（含连续多编号 步骤 #5、#6）。
"""
import re
import sys

JUDGE_OUTPUT = """**优点**
- 核心任务委派合理：第一步正确调用 `task` 工具生成充放电策略
- 具备容错意识：遇到权限错误后主动尝试不同路径

**问题工具**
- 步骤 #4: 写入测试文件 `_writetest.txt` 属于低效调试手段
- 步骤 #7: 读取 `agent.py` 源码寻找可写路径约定属于过度调试
- 步骤 #5、#6: 连续两次 `ls` 探索目录结构效率较低

**综合建议**
- 遇到文件写入失败时,应优先尝试 `/tmp` 等标准可写路径

**评分：3**"""


def extract_problem_section(comment: str) -> str:
    """从 judge 输出中提取 **问题工具** 段（到下一个 ** 段为止）。"""
    start = comment.find("**问题工具**")
    if start < 0:
        return ""
    # 找下一个 **xxx** 段标题
    after = comment.find("\n**", start)
    section = comment[start : after if after > 0 else len(comment)]
    return section


def parse_problem_steps(comment: str) -> dict[int, str]:
    """提取问题步骤编号 -> 描述。

    策略：
    1. 先切出 **问题工具** 段
    2. 按 bullet 行切分（- 开头）
    3. 每行用正则匹配所有 #N，第一个 #N 之后到行尾算描述
    """
    section = extract_problem_section(comment)
    if not section:
        return {}

    result: dict[int, str] = {}
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("-"):
            continue
        # 匹配所有 #N
        step_nums = re.findall(r"#(\d+)", line)
        if not step_nums:
            continue
        # 描述：去掉 "步骤 #N、#M:" 前缀后的内容
        # 找第一个冒号（中英文）后的内容
        m = re.search(r"[:：]\s*(.+)", line)
        desc = m.group(1).strip() if m else ""
        for n in step_nums:
            result[int(n)] = desc
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("验证 3: 正则提取步骤编号（含连续多编号）")
    print("=" * 60)
    print("judge 输出:")
    print(JUDGE_OUTPUT)
    print()
    steps = parse_problem_steps(JUDGE_OUTPUT)
    print(f"提取到 {len(steps)} 个问题步骤:")
    for step, desc in sorted(steps.items()):
        print(f"  步骤 #{step}: {desc[:60]}")
    print()
    expected = {4, 5, 6, 7}
    actual = set(steps.keys())
    print(f"期望: {expected}")
    print(f"实际: {actual}")
    print(f"通过: {expected == actual}")
    print("=" * 60)
