"""端到端链路验证：
A. 浏览器层：真实 Chromium → doubao.com/chat → 找到输入框/发送按钮 → 发送 / 登录检测
B. Agent 链路：模拟 AI 回复（因为沙箱未登录）→ 解析 → 真实 adb(mock) 执行
C. 全链路串联：截图 → 喂给 DoubaoWorker 队列 → 让 worker 返回注入的回复 → Agent 执行动作
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/workspace")

from app.core.config import Config, app_dir
from app.core.agent import AgentCallbacks, PhoneAgent
from app.core.device.controller import DeviceController
from app.gui.workers import DoubaoWorker

cfg_path = Path("/tmp/dpa_chain_test.json")
if cfg_path.exists():
    cfg_path.unlink()

cfg = Config(cfg_path)
cfg.set("adb_path", "/workspace/.test-tmp/adb")
cfg.set("prefer_u2", False)
cfg.set("max_steps", 8)
cfg.set("action_interval", 0.05)
cfg.set("post_screenshot_delay", 0.05)

os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":99")
adb_log = "/tmp/dpa_adb_chain.log"
if os.path.exists(adb_log):
    os.remove(adb_log)


def read_adb_log():
    out = []
    try:
        with open(adb_log) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:
        pass
    return out


# ======================================================
# A 段：浏览器层真实访问 doubao.com
# ======================================================
print("=" * 60)
print("A. 浏览器层：真实 Chromium + doubao.com/chat")
print("=" * 60)
from app.core.doubao import DoubaoClient, DoubaoError

logs_a = []
dc = DoubaoClient(cfg, lambda m, l="info": logs_a.append((l, m)))
dc.ensure_browser()
print("  ensure_browser OK, profile_dir:", dc.profile_dir())
t0 = time.time()
dc.start()
print(f"  start OK 耗时 {time.time()-t0:.1f}s")
print("  当前 URL:", dc._page.url[:100])
# 找输入框
inp = dc._find_input()
print("  输入框找到:", inp is not None)
sbtn = dc._find_send_button()
print("  发送按钮找到:", sbtn is not None)
logged = dc.is_logged_in()
print("  is_logged_in (沙箱未登录应为 False):", logged)
assert not logged, "沙箱里豆包不可能已登录"
# 未登录 ask 应友好报错
try:
    dc.ask("test question")
    raise SystemExit("应抛错")
except DoubaoError as e:
    print("  未登录 ask 正确报错 ✔:", str(e)[:40])
dc.close()
print("  DoubaoClient.close OK; 总共收到日志:", len(logs_a))
assert inp is not None, "doubao.com/chat 输入框没找到（选择器失效了）"
print("A 段全过 ✔\n")


# ======================================================
# B 段：Agent + 真实 ADB(mock) 链路
# ======================================================
print("=" * 60)
print("B. Agent + 设备控制链路（用真实 adb mock）")
print("=" * 60)
dev = DeviceController(cfg)
info = dev.connect()
print("  设备:", info.model, info.android_version, "分辨率:", info.resolution)
assert info.model == "FakePhone16"
assert info.android_version == "16"
assert info.resolution == (1080, 2400)

# 直接调用设备层
png = dev.screenshot()
from PIL import Image
import io
im = Image.open(io.BytesIO(png))
print(f"  截图尺寸: {im.size}")
assert im.size == (1080, 2400)

dev.tap(500, 600)
dev.swipe(100, 200, 300, 400, 250)
dev.key("HOME")
dev.launch("com.tencent.mm")

# 用注入的 AI 回复驱动 Agent（在单元测试层面验证 agent 会把动作发给设备）
class InjectDoubao:
    def __init__(self, replies):
        self._replies = list(replies)
    def ask(self, instr, image=None, timeout=180):
        assert image and len(image) > 100, "截图没给到豆包"
        return self._replies.pop(0)


class Recorder(AgentCallbacks):
    def __init__(self):
        self.logs = []; self.ais = []; self.result = None; self._done = threading.Event()
    def log(self, m, l="info"): self.logs.append((l, m))
    def ai_message(self, m): self.ais.append(m)
    def screenshot(self, png, w, h): pass
    def status(self, t): pass
    def finished(self, ok, r): self.result = (ok, r); self._done.set()

# 场景：打开微信 -> 点击图标 -> 输入消息 -> 发送 -> 完成
rec = Recorder()
doubao_inj = InjectDoubao([
    "ACTION: LAUNCH com.tencent.mm\n"
    "ACTION: TAP 540 1800\n"
    "ACTION: TEXT Hey, let's have dinner tonight\n"
    "ACTION: TAP 1000 1200\n"
    "ACTION: DONE 已给张三发送消息",
])
agent = PhoneAgent(cfg, dev, doubao_inj, rec, threading.Event())
agent.run("Open WeChat and send Zhang San a message")
assert rec._done.wait(5)
print(f"  Agent 结果: {rec.result}")
print(f"  AI 消息数: {len(rec.ais)}")

adb_records = [r for r in read_adb_log() if r["type"] in ("tap", "swipe", "text", "key", "launch")]
print(f"  adb 实际发出的动作数 (mock 层面): {len(adb_records)}")
for r in adb_records:
    print(f"    - {r['type']}: {r['data']}")

# 检查动作序列是否符合预期（包含 launch + 2次tap + 1次text）
seen_verbs = [r["type"] for r in adb_records[-5:]]  # 最后 5 条
print(f"  最后 5 个动作: {seen_verbs}")
assert "launch" in seen_verbs and "text" in seen_verbs and seen_verbs.count("tap") >= 2
assert rec.result == (True, "已给张三发送消息"), rec.result
print("B 段全过 ✔\n")


# ======================================================
# C 段：全链路：GUI 线程(DoubaoWorker) + Agent 协同，验证 ask 经过 queue
# ======================================================
print("=" * 60)
print("C. 全链路：DoubaoWorker(QThread) + PhoneAgent 协同")
print("=" * 60)

# 启动 DoubaoWorker（会真实启浏览器），然后 monkeypatch 它的 client 成注入式
class InjectClient:
    started = True
    def __init__(self, replies):
        self._replies = list(replies)
    def is_logged_in(self): return True
    def ask(self, instr, image=None, timeout=180):
        assert image and len(image) > 100, "截图没透传到 DoubaoWorker.ask 内部"
        return self._replies.pop(0)

# 清空 adb 日志
os.remove(adb_log); open(adb_log, "w").close()

dw = DoubaoWorker(cfg)
dw_logs: list = []
def _on_log(msg, level="info"): dw_logs.append((level, msg))
dw.log.connect(_on_log)
dw.start()
dw.request_start()
# 跨线程 signal 需要 app.exec_ 事件循环才能投递，用 started 属性做更可靠的轮询
deadline = time.time() + 60
while time.time() < deadline:
    if dw.client is not None and dw.client.started:
        break
    # 顺便消费 Qt 事件队列（signal 投递需要）
    try:
        from PySide6.QtCore import QCoreApplication
        app_inst = QCoreApplication.instance()
        if app_inst is not None:
            app_inst.processEvents()
    except Exception:
        pass
    time.sleep(0.2)
if not (dw.client is not None and dw.client.started and dw.client._page is not None):
    print("  FAIL: DoubaoWorker 启动超时，最近日志:")
    for l, m in dw_logs[-10:]:
        print(f"   [{l}] {m[:160]}")
    raise SystemExit("C段启动 DoubaoWorker 失败")
print("  DoubaoWorker 已启动浏览器，当前URL:", dw.client._page.url[:100])

# 注入假 client（不真实请求豆包，只测试通路）
inj = InjectClient([
    "ACTION: TAP 200 400\nACTION: SWIPE 100 2000 100 1200 400\nACTION: DONE 屏幕滑动完成",
])
old_client = dw.client
dw.client = inj

dev2 = DeviceController(cfg)
dev2.connect()

rec2 = Recorder()
stop2 = threading.Event()
agent2 = PhoneAgent(cfg, dev2, dw, rec2, stop2)
agent2.run("打开手机滑动屏幕")
assert rec2._done.wait(20)
print(f"  结果: {rec2.result}")
print(f"  日志条数: {len(rec2.logs)}")

adb_c = [r for r in read_adb_log() if r["type"] in ("tap", "swipe", "text", "key", "launch")]
print(f"  adb 动作序列（C段产生）:")
for r in adb_c:
    print(f"    - {r['type']}: {r['data']}")
verbs = [r["type"] for r in adb_c]
assert "tap" in verbs and "swipe" in verbs, f"动作不足: {verbs}"
assert rec2.result == (True, "屏幕滑动完成"), rec2.result

# 关闭 DoubaoWorker（先还原 client，好让 close 走真实关闭路径）
dw.client = old_client
dw.request_close()
ok = dw.wait(8000)
print("  DoubaoWorker 关闭:", ok)
print("C 段全过 ✔\n")

print("=" * 60)
print("端到端 A/B/C 三段全部通过 ✔")
print("=" * 60)
