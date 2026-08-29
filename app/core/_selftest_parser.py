"""parser 自测（可独立运行）：python app/core/_selftest_parser.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import parser  # noqa: E402


def check(reply: str, expect_verbs: list[str]) -> None:
    acts = parser.parse_actions(reply)
    verbs = [a.verb for a in acts]
    ok = verbs == expect_verbs
    print(("OK  " if ok else "FAIL"), "->", verbs, "|", [a.describe() for a in acts])
    if not ok:
        print("     期望:", expect_verbs)
        raise SystemExit(1)


# 英文 ACTION
check("""先看下屏幕。
ACTION: TAP 500 800
ACTION: WAIT 1000
ACTION: TEXT 你好
ACTION: KEY HOME
""", ["tap", "wait", "text", "key"])

# 中文动作
check("""我来操作。
动作：点击 300 400
动作：滑动 100 200 300 400 500
动作：输入 晚上一起吃饭
动作：完成 已发送
""", ["tap", "swipe", "text", "done"])

# 函数式
check("tap(200, 300)\nswipe(0, 1000, 0, 100, 200)", ["tap", "swipe"])

# 纯文字（无动作）
check("好的，今天天气不错，记得带伞。", [])

# 混合解释+动作+完成
check("""看到微信图标了。
[动作] 点击 120 340
[动作] 输入 早上好
ACTION: DONE 消息已发送
""", ["tap", "text", "done"])

# 解析具体参数
acts = parser.parse_actions("动作：点击 500 800\n动作：滑动 10 20 30 40\n动作：按键 back")
assert acts[0].args == ["500", "800"], acts[0]
assert acts[1].args == ["10", "20", "30", "40", "300"], acts[1]
assert acts[2].args == ["BACK"], acts[2]
print("OK   参数解析正确")
print("\n全部通过")
