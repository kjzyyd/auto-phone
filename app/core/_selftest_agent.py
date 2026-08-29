"""Agent 集成自测（模拟设备 + 模拟豆包，无需真机）。
运行：python app/core/_selftest_agent.py
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.agent import AgentCallbacks, PhoneAgent  # noqa: E402
from app.core.config import Config  # noqa: E402
from app.core.device.controller import DeviceController  # noqa: E402
from app.core.device import DeviceInfo  # noqa: E402


class MockDevice:
    connected = True
    info = DeviceInfo(serial="test", model="TestPhone", resolution=(1080, 2400))

    def __init__(self):
        self.ops: list[str] = []

    def screenshot(self):
        return b"\x89PNG-fake"

    def tap(self, x, y):
        self.ops.append(f"tap {x} {y}")

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.ops.append(f"swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def text(self, s):
        self.ops.append(f"text {s}")

    def key(self, k):
        self.ops.append(f"key {k}")

    def launch(self, pkg):
        self.ops.append(f"launch {pkg}")


class MockDoubao:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def ask(self, instruction, image=None, timeout=180):
        self.calls += 1
        assert image == b"\x89PNG-fake", "image 未透传"
        return self.replies.pop(0)


class Recorder(AgentCallbacks):
    def __init__(self):
        self.logs = []
        self.ais = []
        self.shots = 0
        self.statuses = []
        self.result = None

    def log(self, msg, level="info"):
        self.logs.append((msg, level))

    def ai_message(self, msg):
        self.ais.append(msg)

    def screenshot(self, png, width, height):
        self.shots += 1

    def status(self, text):
        self.statuses.append(text)

    def finished(self, ok, reason):
        self.result = (ok, reason)


def make_cfg(tag: str) -> Config:
    cfg = Config(Path(f"/tmp/dpa_agent_test_{tag}.json"))
    cfg.set("max_steps", 20)  # 每个场景独立配置，避免状态泄漏
    return cfg


def main() -> None:
    cfg = make_cfg("s1")
    dev = MockDevice()
    rec = Recorder()

    # 场景1：一轮完成
    doubao = MockDoubao([
        "ACTION: TAP 100 200\nACTION: TEXT 早上好\nACTION: DONE 已发送",
    ])
    agent = PhoneAgent(cfg, dev, doubao, rec, threading.Event())
    agent.run("测试指令")
    assert rec.result == (True, "已发送"), rec.result
    assert dev.ops == ["tap 100 200", "text 早上好"], dev.ops
    assert rec.shots >= 1
    print("OK 场景1：一轮完成 ->", dev.ops, rec.result)

    # 场景2：豆包纯文字回答（无动作）
    cfg2 = make_cfg("s2")
    dev2 = MockDevice()
    rec2 = Recorder()
    doubao2 = MockDoubao(["今天天气不错，注意防晒。"])
    agent2 = PhoneAgent(cfg2, dev2, doubao2, rec2, threading.Event())
    agent2.run("今天天气怎么样")
    assert rec2.result[0] is True, rec2.result
    assert dev2.ops == [], dev2.ops
    print("OK 场景2：纯文字回答 ->", rec2.result)

    # 场景3：多轮 + 停止事件
    cfg3 = make_cfg("s3")
    dev3 = MockDevice()
    rec3 = Recorder()
    stop = threading.Event()
    doubao3 = MockDoubao([
        "ACTION: TAP 1 1",
        "ACTION: SWIPE 0 0 100 100 200",
        "ACTION: DONE 结束",
    ])
    agent3 = PhoneAgent(cfg3, dev3, doubao3, rec3, stop)
    agent3.run("多轮测试")
    assert rec3.result == (True, "结束"), rec3.result
    assert dev3.ops == ["tap 1 1", "swipe 0 0 100 100 200"], dev3.ops
    print("OK 场景3：多轮 ->", dev3.ops)

    # 场景4：达到最大轮数
    cfg4 = make_cfg("s4")
    cfg4.set("max_steps", 2)
    dev4 = MockDevice()
    rec4 = Recorder()
    doubao4 = MockDoubao(["ACTION: TAP 1 1"] * 10)
    agent4 = PhoneAgent(cfg4, dev4, doubao4, rec4, threading.Event())
    agent4.run("轮数测试")
    assert rec4.result[0] is False, rec4.result
    assert "最大操作轮数" in rec4.result[1], rec4.result
    print("OK 场景4：轮数限制 ->", rec4.result[1])

    print("\n全部通过")


if __name__ == "__main__":
    main()
