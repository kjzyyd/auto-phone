"""把豆包回复解析成可执行的手机操作指令。

支持的指令格式（每行一条，英文或中文均可）：
  ACTION: TAP 500 800            / 动作：点击 500 800
  ACTION: SWIPE 100 200 300 400 500   / 动作：滑动 x1 y1 x2 y2 时长ms
  ACTION: TEXT 你好世界          / 动作：输入 文本
  ACTION: KEY HOME               / 动作：按键 home|back|menu|...
  ACTION: LAUNCH com.tencent.mm  / 动作：启动 包名
  ACTION: WAIT 1000              / 动作：等待 毫秒
  ACTION: SHOT                   / 动作：截图
  ACTION: DONE 原因              / 动作：完成 说明
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# 动作行主格式：ACTION: VERB args / [动作] 动词 args / 动作：动词 args
_ACTION_RE = re.compile(
    r"^\s*\[?\s*(?:ACTION|动作)\s*\]?\s*[:：]?\s*([A-Za-z\u4e00-\u9fa5]+)\s*(.*)$",
    re.IGNORECASE,
)

# 备用格式（容忍度更高的函数式写法）
_FUNC_RE = re.compile(r"^(?:tap|click|swipe|text|key|launch|wait|shot|done)\s*\(", re.IGNORECASE)

_VERB_MAP = {
    "tap": "tap", "click": "tap", "点击": "tap", "点": "tap",
    "swipe": "swipe", "滑动": "swipe", "滑": "swipe",
    "text": "text", "输入": "text", "键入": "text", "type": "text",
    "key": "key", "按键": "key", "键": "key",
    "launch": "launch", "启动": "launch", "打开应用": "launch", "open": "launch",
    "wait": "wait", "等待": "wait", "sleep": "wait", "延时": "wait",
    "shot": "shot", "截图": "shot", "screenshot": "shot",
    "done": "done", "完成": "done", "结束": "done",
}


@dataclass
class Action:
    verb: str                     # tap / swipe / text / key / launch / wait / shot / done
    args: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.verb == "done"

    def describe(self) -> str:
        if self.verb == "tap":
            return f"点击 {self.args[0]},{self.args[1]}" if len(self.args) >= 2 else self.raw
        if self.verb == "swipe":
            return f"滑动 {' '.join(self.args)}" if self.args else self.raw
        if self.verb == "text":
            return f"输入 {self.args[0]}" if self.args else self.raw
        if self.verb == "key":
            return f"按键 {self.args[0].upper()}" if self.args else self.raw
        if self.verb == "launch":
            return f"启动 {self.args[0]}" if self.args else self.raw
        if self.verb == "wait":
            return f"等待 {self.args[0]}ms" if self.args else self.raw
        if self.verb == "shot":
            return "截图"
        if self.verb == "done":
            return f"完成：{' '.join(self.args)}"
        return self.raw or self.verb


def _norm_verb(token: str) -> Optional[str]:
    t = token.strip().lower()
    return _VERB_MAP.get(t)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'“”":
        return s[1:-1]
    return s


def parse_actions(reply: str) -> list[Action]:
    """从豆包回复中提取动作列表（忽略解释性文字）。"""
    if not reply:
        return []
    actions: list[Action] = []
    for raw_line in reply.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _ACTION_RE.match(line)
        if m:
            verb = _norm_verb(m.group(1))
            if not verb:
                continue
            rest = m.group(2).strip()
            act = _build_action(verb, rest, raw_line)
            if act:
                actions.append(act)
            continue
        # 函数式备用：tap(500,800) 等
        if _FUNC_RE.match(line):
            act = _build_func_action(line, raw_line)
            if act:
                actions.append(act)
    return actions


def _build_action(verb: str, rest: str, raw: str) -> Optional[Action]:
    if verb in ("tap",):
        nums = _extract_ints(rest, 2)
        if len(nums) >= 2:
            return Action("tap", [str(nums[0]), str(nums[1])], raw)
        return Action("tap", [rest], raw)
    if verb == "swipe":
        nums = _extract_ints(rest, 5)
        if len(nums) >= 4:
            args = [str(n) for n in nums[:4]]
            if len(nums) >= 5:
                args.append(str(nums[4]))
            else:
                args.append("300")
            return Action("swipe", args, raw)
        return Action("swipe", [rest], raw)
    if verb == "text":
        return Action("text", [_strip_quotes(rest)], raw)
    if verb == "key":
        tok = _strip_quotes(rest).split()[0] if rest else ""
        return Action("key", [tok.upper()], raw) if tok else None
    if verb == "launch":
        return Action("launch", [_strip_quotes(rest)], raw) if rest else None
    if verb == "wait":
        nums = _extract_ints(rest, 1)
        return Action("wait", [str(nums[0])] if nums else ["500"], raw)
    if verb == "shot":
        return Action("shot", [], raw)
    if verb == "done":
        return Action("done", [rest] if rest else ["任务完成"], raw)
    return None


def _build_func_action(line: str, raw: str) -> Optional[Action]:
    s = line.strip()
    m = re.match(r"([A-Za-z]+)\s*\((.*)\)", s)
    if not m:
        return None
    verb = _norm_verb(m.group(1))
    if not verb:
        return None
    inner = m.group(2)
    if verb == "tap":
        nums = _extract_ints(inner, 2)
        if len(nums) >= 2:
            return Action("tap", [str(nums[0]), str(nums[1])], raw)
    if verb == "swipe":
        nums = _extract_ints(inner, 5)
        if len(nums) >= 4:
            args = [str(n) for n in nums[:4]]
            args.append(str(nums[4]) if len(nums) >= 5 else "300")
            return Action("swipe", args, raw)
    if verb == "text":
        t = re.sub(r"^[\"'\u201c\u201d]|[\"'\u201c\u201d]$", "", inner.strip())
        if t:
            return Action("text", [t], raw)
    if verb == "key":
        t = inner.strip().strip("\"'\u201c\u201d").upper()
        if t:
            return Action("key", [t], raw)
    if verb == "launch":
        t = inner.strip().strip("\"'\u201c\u201d")
        if t:
            return Action("launch", [t], raw)
    if verb == "wait":
        nums = _extract_ints(inner, 1)
        if nums:
            return Action("wait", [str(nums[0])], raw)
    if verb in ("shot", "done"):
        return Action(verb, [inner] if inner else [], raw)
    return None


def _extract_ints(s: str, n: int) -> list[int]:
    nums = [int(x) for x in re.findall(r"-?\d+", s)]
    return nums[:n]
