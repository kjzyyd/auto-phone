"""GUI 真实按钮驱动：
1. 显示 MainWindow
2. 点「连接手机」→ 等设备连接完成回调
3. 点「连接豆包」→ DoubaoWorker 真实启浏览器（启动后 monkeypatch 注入 fake client）
4. 在输入框写指令、点「发送指令」→ AgentWorker 完成 DONE
5. 断言：状态栏、操作日志、聊天记录、adb(mock) 实际动作序列
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/workspace")
os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":99")
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # 离屏渲染，避免 Playwright Chromium + Xvfb 资源冲突

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QPlainTextEdit

from app.core.config import Config
from app.gui.main_window import MainWindow

adb_log = "/tmp/dpa_adb_gui.log"
os.environ["DPA_MOCK_ADB_LOG"] = adb_log
if os.path.exists(adb_log):
    os.remove(adb_log)

# 保证 adb 指向 mock
cfg_path = Path("/tmp/dpa_gui_chain.json")
if cfg_path.exists():
    cfg_path.unlink()
cfg = Config(cfg_path)
cfg.set("adb_path", "/workspace/.test-tmp/adb")
cfg.set("prefer_u2", False)
cfg.set("max_steps", 10)
cfg.set("action_interval", 0.05)
cfg.set("post_screenshot_delay", 0.05)
cfg.set("headless", True)       # 沙箱里 Playwright 必须 headless，否则会连 DISPLAY 跟 Qt 抢资源

app = QApplication(sys.argv)
app.setStyle("Fusion")
win = MainWindow(cfg)
win.resize(1280, 800)
win.show()
app.processEvents()
time.sleep(0.3)

OUT = Path("/workspace/.test-tmp")


def btn_by_text(name):
    for b in win.findChildren(QPushButton):
        if b.text() == name and b.isVisible():
            return b
    raise RuntimeError(f"找不到可见按钮: {name}")


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.05)


def grab(tag):
    app.processEvents()
    pix = win.grab()
    p = OUT / f"gui_chain_{tag}.png"
    pix.save(str(p))
    print(f"  [截图] {p.name} 已保存")


# ================================================================
# 1. 连接手机
# ================================================================
print("== 1. 点「连接手机」 ==")
old_model = win.lbl_model.text()
btn_by_text("连接手机").click()
deadline = time.time() + 15
while time.time() < deadline:
    pump(0.2)
    if win.lbl_model.text() and win.lbl_model.text() != old_model:
        break
print(f"  设备名: {win.lbl_model.text()} | 状态: {win.device_pill.label.text()}")
assert win.device_pill.label.text().startswith("已连接")
assert "FakePhone16" in win.lbl_model.text()
assert win.preview._pixmap is not None
print("  手机已连接，预览画面尺寸:", win.preview._pixmap.size().width(), "x", win.preview._pixmap.size().height())
grab("1_connected")

# ================================================================
# 2. 连接豆包（真实启动 Chromium 浏览器）
# ================================================================
print("== 2. 点「连接豆包」 ==")
btn_by_text("连接豆包").click()
deadline = time.time() + 60
while time.time() < deadline:
    pump(0.3)
    if win.doubao.client is not None and win.doubao.client.started:
        break
dstate = win.doubao_pill.label.text()
print(f"  豆包状态: {dstate}")
print(f"  浏览器 URL: {win.doubao.client._page.url[:100] if (win.doubao.client and win.doubao.client._page) else 'NONE'}")
assert win.doubao.client is not None and win.doubao.client.started, "DoubaoWorker 未启动"
grab("2_doubao")

# 现在 monkeypatch 一个假 client，让 ask 走我们的注入 reply 而不是真实豆包
class InjectClient:
    started = True
    def is_logged_in(self): return True
    def close(self): pass
    def ask(self, instr, image=None, timeout=180):
        assert image and len(image) > 1000, "截图未透传"
        # 返回一组动作：点击图标 + 点击输入框 + 输入文本 + 发送 + DONE
        return (
            "ACTION: TAP 200 1600\n"
            "ACTION: TAP 540 1800\n"
            "ACTION: TEXT test123\n"
            "ACTION: TAP 1000 1800\n"
            "ACTION: DONE GUI 发送完成"
        )

win.doubao.client = InjectClient()

# ================================================================
# 3. 发送指令 —— 等 Agent 完整跑完
# ================================================================
print("== 3. 输入指令并点「发送指令」 ==")
win.input_edit.setPlainText("打开微信测试")
pump(0.3)
send_btn = btn_by_text("发送指令")
print(f"  发送按钮可用: {send_btn.isEnabled()}")
assert send_btn.isEnabled()
send_btn.click()
pump(0.3)
assert not send_btn.isEnabled(), "点发送后按钮应禁用表示任务中"
print("  按钮已禁用，任务进行中…")

deadline = time.time() + 30
while time.time() < deadline:
    pump(0.3)
    if send_btn.isEnabled():
        break

print(f"  任务结束，发送按钮重新启用: {send_btn.isEnabled()}")
assert send_btn.isEnabled()
grab("3_sent")

# ================================================================
# 4. 检查输出
# ================================================================
print("== 4. 检查结果 ==")
log_text = win.log_view.toPlainText()
chat_text = win.chat_view.toPlainText()
print(f"  日志行数: {log_text.count(chr(10))}")
print(f"  聊天行数: {chat_text.count(chr(10))}")
assert "开始执行指令" in log_text or "AI" in log_text or "动作" in log_text, "日志未写入"
assert "完成" in chat_text or "DONE" in chat_text or "发送完成" in chat_text, "聊天里没有完成消息"
# 检查 adb 动作日志
actual = []
try:
    with open(adb_log) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            if r["type"] in ("tap", "swipe", "text", "key", "launch"):
                actual.append((r["type"], r["data"]))
except Exception:
    pass

print(f"  adb(mock) 实际执行 {len(actual)} 个动作:")
for t, d in actual:
    print(f"    - {t}: {d}")
verbs = [v for v, _ in actual]
assert verbs.count("tap") >= 3, f"tap 动作不足 {verbs}"
assert "text" in verbs, f"text 动作缺失 {verbs}"

grab("4_final")
print("\nGUI 按钮驱动端到端全部通过 ✔")

# ------------- 安全清理（避免 QThread 析构时仍在跑 → SIGABRT） -------------
print("== 5. 清理线程 ==")
# AgentWorker 已完成（send_btn 已重新启用），如果还在跑就等一下
if win.agent_worker and win.agent_worker.isRunning():
    win.stop_event.set()
    ok = win.agent_worker.wait(5000)
    print(f"  AgentWorker wait: {ok}")
# 关闭窗口 → 触发 closeEvent → request_close → doubao.wait(3000)
win.close()
pump(1.0)
# 显式等 DoubaoWorker 退出（closeEvent 已经 request_close + wait(3000)，再兜底一次）
if win.doubao.isRunning():
    ok = win.doubao.wait(6000)
    print(f"  DoubaoWorker wait: {ok}")
# DeviceWorker 是短时任务，完成后 isRunning=False
if win.device_worker and win.device_worker.isRunning():
    win.device_worker.wait(3000)
print("  全部线程已停止")
app.quit()
pump(0.5)
del win
del app
