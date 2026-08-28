"""DoubaoClient：通过 Playwright 驱动网页版豆包（doubao.com/chat）。

- 登录态持久化：浏览器 profile 存在用户目录，登录一次长期有效（扫码即可）。
- 发送：找到输入框 -> 填入文字 ->（可选）附带截图 -> 回车/点发送。
- 读取：基于「发送前/后整段对话文本 diff」+ 文本稳定判定，兼容豆包前端改版。
- 登录检测：优先看「登录」按钮是否存在（未登录时输入框也可见，不能只看输入框）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from ..config import app_dir

logger_type = Callable[[str, str], None]


def _setup_browsers_path() -> None:
    """打包成 exe 时，Playwright 浏览器放在 exe 同目录的 ms-playwright 下。"""
    if getattr(sys, "frozen", False) and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        base = Path(sys.executable).resolve().parent / "ms-playwright"
        if base.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(base)


class DoubaoError(RuntimeError):
    """豆包网页操作异常。"""


class DoubaoClient:
    def __init__(self, config, logger: logger_type | None = None):
        self.config = config
        self._log = logger or (lambda msg, level="info": None)
        self._pw = None
        self._context = None
        self._page = None
        self._started = False

    def log(self, msg: str, level: str = "info") -> None:
        self._log(msg, level)

    @property
    def started(self) -> bool:
        return self._started

    def profile_dir(self) -> Path:
        ud = str(self.config.get("user_data_dir") or "")
        if ud:
            return Path(ud)
        return app_dir() / "doubao_profile"

    # ---------- 生命周期 ----------
    def ensure_browser(self) -> None:
        """确保 Playwright Chromium 可用（首次运行需要联网下载一次）。"""
        _setup_browsers_path()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if Path(path).exists():
                return
        if getattr(sys, "frozen", False):
            raise DoubaoError(
                "未找到 Chromium 浏览器。请重新运行打包脚本（含 playwright install chromium），"
                "或将 ms-playwright 目录放到 exe 同目录。"
            )
        self.log("首次运行：正在下载 Chromium 浏览器（约 150MB），请稍候…", "info")
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"], check=True
        )
        self.log("Chromium 下载完成。", "success")

    def start(self) -> None:
        if self._started:
            return
        from playwright.sync_api import sync_playwright

        _setup_browsers_path()
        self._pw = sync_playwright().start()
        profile = self.profile_dir()
        profile.mkdir(parents=True, exist_ok=True)
        headless = bool(self.config.get("headless"))
        try:
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=headless,
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            self._pw.stop()
            self._pw = None
            raise DoubaoError(f"启动浏览器失败：{e}。请先运行 playwright install chromium。")

        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.set_default_timeout(15000)
        self._page.goto(str(self.config.get("doubao_url")), wait_until="domcontentloaded")
        self._started = True
        self.log("豆包浏览器已打开。若未登录，请在窗口中扫码/登录，然后点「连接豆包」确认。", "info")

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._started = False
        self.log("豆包浏览器已关闭。", "info")

    # ---------- 登录检测 ----------
    def is_logged_in(self) -> bool:
        if not self._started or not self._page:
            return False
        try:
            login_btn = self._page.query_selector("button[class*='login-btn-header']")
            if login_btn and self._safe_visible(login_btn):
                return False
            # 兜底：出现登录弹窗也算未登录
            for sel in ["div[class*='login-modal']", "div[class*='LoginModal']"]:
                m = self._page.query_selector(sel)
                if m and self._safe_visible(m):
                    return False
        except Exception:
            pass
        return self._find_input() is not None

    @staticmethod
    def _safe_visible(el) -> bool:
        try:
            return bool(el.is_visible())
        except Exception:
            return False

    def wait_login(self, timeout: int = 300) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.is_logged_in():
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    # ---------- 元素定位 ----------
    _INPUT_CANDIDATES = [
        "[contenteditable='true']",
        "div[role='textbox']",
        "textarea[placeholder]",
        "textarea",
    ]

    def _find_input(self) -> Optional[object]:
        page = self._page
        if page is None:
            return None
        for sel in self._INPUT_CANDIDATES:
            try:
                el = page.query_selector(sel)
                if el and self._safe_visible(el):
                    return el
            except Exception:
                continue
        return None

    def _find_send_button(self) -> Optional[object]:
        for sel in [
            "button[aria-label*='发送']",
            "button[class*='send']",
            "button[class*='Send']",
            "button[aria-label*='Send']",
        ]:
            try:
                el = self._page.query_selector(sel)
                if el and self._safe_visible(el):
                    return el
            except Exception:
                continue
        return None

    # ---------- 发送 ----------
    def ask(self, instruction: str, image: bytes | None = None, timeout: int = 180) -> str:
        if not self._started or not self._page:
            raise DoubaoError("豆包浏览器未启动，请先点击「连接豆包」。")
        if not self.is_logged_in():
            raise DoubaoError("豆包未登录或输入框不可见，请在打开的浏览器中完成登录。")

        page = self._page
        base_text = self._conversation_text()
        self._send(instruction, image)
        return self._wait_response(instruction, base_text, timeout)

    def _send(self, text: str, image: bytes | None) -> None:
        page = self._page
        el = self._find_input()
        if el is None:
            raise DoubaoError("找不到输入框，请确认豆包页面已加载并登录。")
        try:
            el.click()
        except Exception:
            pass

        if image is not None:
            self._attach_image(image)

        try:
            page.keyboard.insert_text(text)
        except Exception:
            try:
                page.keyboard.type(text, delay=8)
            except Exception as e:
                raise DoubaoError(f"输入文字失败：{e}")

        send_btn = self._find_send_button()
        if send_btn is not None:
            try:
                send_btn.click()
                self.log("已发送给豆包。", "info")
                return
            except Exception:
                pass
        try:
            page.keyboard.press("Enter")
            self.log("已发送给豆包。", "info")
        except Exception as e:
            raise DoubaoError(f"发送失败：{e}")

    def _attach_image(self, image: bytes) -> None:
        page = self._page
        # 方式1：直接存在 file input
        try:
            fi = page.query_selector("input[type='file']")
            if fi:
                fi.set_input_files(
                    {"name": "screen.png", "mimeType": "image/png", "buffer": image}
                )
                self.log("已附带手机截图。", "info")
                time.sleep(1.2)
                return
        except Exception:
            pass
        # 方式2：点击输入区附件按钮，等待 file chooser
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                btn = self._find_attach_button()
                if btn is None:
                    raise DoubaoError("no attach button")
                btn.click()
            fc = fc_info.value
            fc.set_files({"name": "screen.png", "mimeType": "image/png", "buffer": image})
            self.log("已附带手机截图。", "info")
            time.sleep(1.2)
            return
        except Exception as e:
            self.log(f"上传截图失败（{e}），将仅发送文字，AI 可能看不到屏幕。", "warn")

    def _find_attach_button(self) -> Optional[object]:
        """输入区里第一个带图标的按钮（图片/加号上传入口）。"""
        try:
            input_el = self._find_input()
            if input_el:
                container = input_el.evaluate_handle("e => e.parentElement.parentElement")
                for b in container.query_selector_all("button"):
                    if self._safe_visible(b):
                        return b
        except Exception:
            pass
        # 兜底：main 里所有带 svg 的可见按钮
        try:
            for b in self._page.query_selector_all("main button"):
                if self._safe_visible(b):
                    return b
        except Exception:
            pass
        return None

    # ---------- 读取回复 ----------
    def _conversation_text(self) -> str:
        """取对话区整段文本（发送前/后 diff 用）。"""
        page = self._page
        for sel in [
            "main > div > div:nth-child(2)",           # 消息区容器
            "main div[class*='flex-grow flex-col']",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    t = (el.inner_text() or "").strip()
                    if t:
                        return t
            except Exception:
                continue
        return ""

    def _wait_response(self, sent_text: str, base_text: str, timeout: int) -> str:
        page = self._page
        deadline = time.time() + timeout
        last_text = ""
        stable_since = 0.0

        while time.time() < deadline:
            try:
                current = self._conversation_text()
            except Exception:
                current = last_text
            if current and current != last_text:
                last_text = current
                stable_since = time.time()
            # 文本变化且稳定 1.5s，且输入框已清空（消息已发出）
            if last_text and (time.time() - stable_since) > 1.5:
                if self._input_empty():
                    return self._extract_reply(sent_text, base_text, last_text)
            time.sleep(0.6)

        if last_text:
            return self._extract_reply(sent_text, base_text, last_text)
        raise DoubaoError(f"等待豆包回复超时（{timeout}s）。")

    def _input_empty(self) -> bool:
        try:
            el = self._find_input()
            if el is None:
                return False
            return not (el.inner_text() or "").strip()
        except Exception:
            return False

    def _extract_reply(self, sent_text: str, base_text: str, current: str) -> str:
        """从对话文本中取出『新增部分』（助手回复）。"""
        # 优先尝试 markdown 块
        try:
            md = self._page.query_selector("div[class*='markdown-body']")
            if md:
                t = (md.inner_text() or "").strip()
                if t:
                    return t
        except Exception:
            pass

        base = base_text.strip()
        cur = current.strip()
        if base and cur.startswith(base):
            diff = cur[len(base):]
        elif base and base in cur:
            diff = cur.split(base, 1)[1]
        else:
            diff = cur
        # 去掉回显的用户消息
        if sent_text and diff.startswith(sent_text):
            diff = diff[len(sent_text):]
        diff = diff.strip()
        return diff or current.strip()
