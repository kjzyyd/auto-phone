"""DoubaoClient：通过 Playwright 驱动网页版豆包（doubao.com/chat）。

- 登录态持久化：浏览器 profile 存在用户目录，登录一次长期有效（扫码即可）。
- 发送：找到输入框 -> 填入文字 ->（可选）附带截图 -> 回车/点发送。
- 读取：基于「发送前/后整段对话文本 diff」+ 文本稳定判定，兼容豆包前端改版。
- 登录检测：优先看「登录」按钮是否存在（未登录时输入框也可见，不能只看输入框）。
- 浏览器来源：内置 Chromium（默认）或本机 Edge（通过 CDP 连接，保留登录态）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
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


def _find_edge_executable() -> Optional[str]:
    """自动定位本机 Microsoft Edge 可执行文件。"""
    candidates: list[str] = []
    if sys.platform == "win32":
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        la = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
        if la:
            candidates.append(os.path.join(la, "Microsoft", "Edge", "Application", "msedge.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    else:
        candidates += ["microsoft-edge", "microsoft-edge-stable"]
    for c in candidates:
        if c and Path(c).exists():
            return c
    for name in ("microsoft-edge", "microsoft-edge-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _cdp_port(cdp_url: str) -> int:
    try:
        return int(cdp_url.rsplit(":", 1)[1].rstrip("/"))
    except Exception:
        return 9222


def _wait_cdp(cdp_url: str, timeout: float = 15.0) -> bool:
    """等待 Edge/Chromium 的调试端口就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(cdp_url + "/json/version", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


class DoubaoError(RuntimeError):
    """豆包网页操作异常。"""


class DoubaoClient:
    def __init__(self, config, logger: logger_type | None = None):
        self.config = config
        self._log = logger or (lambda msg, level="info": None)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._started = False
        self._edge_mode = False

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
        """确保浏览器可用：内置 Chromium 首次运行需下载；本机 Edge 则校验已安装。"""
        if str(self.config.get("browser_backend")) == "edge":
            exe = str(self.config.get("edge_exe") or "") or _find_edge_executable()
            if not exe:
                raise DoubaoError(
                    "未找到本机 Microsoft Edge。请在「设置 → 浏览器来源」里选择 Edge，"
                    "并填写 Edge 可执行文件路径。"
                )
            return
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
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"], check=True
        )
        self.log("Chromium 下载完成。", "success")

    def start(self) -> None:
        if self._started:
            return
        backend = str(self.config.get("browser_backend") or "bundled")
        if backend == "edge":
            self._start_edge()
        else:
            self._start_bundled()
        self._started = True

    # ---------- 内置 Chromium ----------
    def _start_bundled(self) -> None:
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
        self.log("豆包浏览器已打开。若未登录，请在窗口中扫码/登录，然后点「连接豆包」确认。", "info")

    # ---------- 本机 Edge（CDP） ----------
    def _start_edge(self) -> None:
        """启动/连接本机 Edge：带调试端口打开真实窗口，通过 CDP 操作，保留登录态。"""
        from playwright.sync_api import sync_playwright

        cdp_url = str(self.config.get("edge_cdp_url") or "http://127.0.0.1:9222")
        self._pw = sync_playwright().start()
        self._edge_mode = True

        if not _wait_cdp(cdp_url, timeout=3.0):
            # 端口未就绪：启动 Edge（独立 profile，不影响日常使用的 Edge 窗口）
            exe = str(self.config.get("edge_exe") or "") or _find_edge_executable()
            if not exe:
                self._pw.stop()
                self._pw = None
                raise DoubaoError(
                    "未找到本机 Microsoft Edge。请安装 Edge，或在「设置 → 浏览器来源 → Edge」"
                    "中填写 Edge 可执行文件路径。"
                )
            profile = str(self.config.get("edge_profile") or "") or str(app_dir() / "edge_profile")
            Path(profile).mkdir(parents=True, exist_ok=True)
            cmd = [
                exe,
                f"--remote-debugging-port={_cdp_port(cdp_url)}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            # Linux 下以 root 运行时需禁用沙箱（Windows 不受影响）
            if sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() == 0:
                cmd.append("--no-sandbox")
            self.log(f"正在启动本机 Edge（调试端口 {_cdp_port(cdp_url)}）…", "info")
            try:
                subprocess.Popen(cmd)
            except Exception as e:
                self._pw.stop()
                self._pw = None
                raise DoubaoError(f"启动 Edge 失败：{e}")
            if not _wait_cdp(cdp_url, timeout=25.0):
                self._pw.stop()
                self._pw = None
                raise DoubaoError("Edge 已启动但调试端口未就绪，请手动检查 Edge 是否可正常打开。")

        try:
            self._browser = self._pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            self._pw.stop()
            self._pw = None
            raise DoubaoError(f"连接本机 Edge 失败：{e}")

        ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        self._context = ctx
        # 已有豆包标签页则复用，否则新开
        page = None
        for pg in ctx.pages:
            if "doubao" in (pg.url or ""):
                page = pg
                break
        if page is None:
            page = ctx.new_page()
        self._page = page
        self._page.set_default_timeout(15000)
        self._page.goto(str(self.config.get("doubao_url")), wait_until="domcontentloaded")
        self.log("已连接本机 Edge 窗口。若未登录，请在 Edge 窗口中扫码/登录，然后点「连接豆包」确认。", "info")

    def close(self) -> None:
        try:
            if self._edge_mode:
                # 只关闭本软件开的标签页，保留用户 Edge 与登录态
                if self._page is not None and not self._page.is_closed():
                    self._page.close()
            elif self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None
        self._started = False
        self.log("豆包浏览器已关闭。", "info")

    # ---------- 登录检测 ----------
    # 1) 负特征：任一可见 = 未登录
    _GUEST_LOGIN_BTN_SELECTORS = [
        # 具体类名（老版本）
        "button[class*='login-btn-header']",
        "a[href*='login']",
        # 新版豆包用的是半通用 "header/Header/侧边栏" 容器下的按钮/链接
        "header button",
        "header a",
        "div[class*='Header'] button",
        "div[class*='Header'] a",
        "nav button",
        "nav a",
        "[data-testid*='header'] button",
        "[data-testid*='header'] a",
    ]

    # 2) 正特征：任一可见 = 已登录（尽量不依赖具体 class 名）
    _LOGGED_IN_ONLY_SELECTORS = [
        # 明确的头像类（老版本 / 通用命名）
        "button[class*='Avatar'], [class*='avatar']:has(img)",
        "[class*='UserInfo'], [class*='user-info']",
        "[class*='username'], [class*='userName'], [class*='nick-name']",
        "[class*='Header'] [class*='avatar']",
        # 新版豆包："退出登录 / 个人中心 / 账号与安全 / 我的" 只会出现在已登录的下拉菜单中
        "button:has-text('退出登录')",
        "a:has-text('退出登录')",
        "button:has-text('个人中心')",
        "a:has-text('个人中心')",
        "button:has-text('我的')",
        "button:has-text('账号与安全')",
        # 顶部右侧经常出现一个圆形图片（头像）+ 没有登录文案
        "header img",
        "nav img",
        "[data-testid*='header'] img",
        "[role='banner'] img",
    ]

    # 3) 弹出登录窗（未登录）
    _LOGIN_MODAL_SELECTORS = [
        "div[class*='login-modal']",
        "div[class*='LoginModal']",
        "div[role='dialog']",
        "div[role='alertdialog']",
    ]

    # 4) Cookie 凭证（只要存在这些 cookie 且非空，基本确定已登录）
    #    豆包 / 字节系常见登录 cookie：
    #      sessionid_ss / passport_csrf_token / uid_tt / uid_tt_ss / sid_guard /
    #      odin_tt / passport_web_id / ttb_browserid 等
    _AUTH_COOKIE_NAMES = (
        "sessionid",
        "sessionid_ss",
        "sid_guard",
        "uid_tt",
        "uid_tt_ss",
        "odin_tt",
        "passport_csrf_token",
        "passport_csrf_token_default",
        "sso_uid_tt",
        "sso_uid_tt_ss",
    )

    def is_logged_in(self) -> bool:
        if not self._started or not self._page:
            return False
        page = self._page
        ctx = self._context

        # ============================================================
        # 0) Cookie 凭证优先：只要存在任一有效登录 cookie，直接认为已登录
        #    （改版最不频繁，不会被前端类名调整误伤）
        # ============================================================
        try:
            if ctx is not None:
                cookies = ctx.cookies()  # type: list[dict] | None
                if cookies:
                    names = {str(c.get("name", "")).lower() for c in cookies if c.get("value")}
                    if any(n.lower() in names for n in self._AUTH_COOKIE_NAMES):
                        return True
        except Exception:
            pass

        # ============================================================
        # 1) 登录弹窗 = 未登录
        # ============================================================
        for sel in self._LOGIN_MODAL_SELECTORS:
            try:
                for m in page.query_selector_all(sel):
                    if not self._safe_visible(m):
                        continue
                    try:
                        text = (m.inner_text() or "")
                    except Exception:
                        text = ""
                    if any(k in text for k in ("登录", "扫码登录", "手机号登录", "短信登录", "密码登录", "登 录")):
                        return False
            except Exception:
                pass

        # ============================================================
        # 2) 扫描含 "登录/立即登录/登陆" 文字的可见按钮/链接 = 未登录
        #    （不依赖 class 名，按容器范围 + 文案 + 长度严格约束）
        # ============================================================
        try:
            for sel in self._GUEST_LOGIN_BTN_SELECTORS:
                try:
                    els = page.query_selector_all(sel)
                except Exception:
                    continue
                for el in els:
                    try:
                        if not self._safe_visible(el):
                            continue
                        txt = (el.inner_text() or "").strip()
                        if not txt or len(txt) > 8:
                            continue
                        if txt in ("登录", "立即登录", "登陆", "去登录", "登录 / 注册"):
                            return False
                    except Exception:
                        continue
        except Exception:
            pass

        # ============================================================
        # 3) 正向登录态元素 = 已登录
        #    对 "header/nav 里的 img" 这类正例要小心：可能是 logo，
        #    所以加"附近没有'登录'按钮"的辅助判断
        # ============================================================
        try:
            for sel in self._LOGGED_IN_ONLY_SELECTORS:
                try:
                    els = page.query_selector_all(sel)
                except Exception:
                    continue
                for el in els:
                    if not self._safe_visible(el):
                        continue
                    # 明确的"退出登录 / 个人中心"文案 = 直接判定登录
                    try:
                        inner = (el.inner_text() or "").strip()
                    except Exception:
                        inner = ""
                    if inner in ("退出登录", "个人中心", "账号与安全", "我的"):
                        return True
                    # 带 img 的元素，且是圆形头像尺寸（近似 width==height）
                    try:
                        bb = el.bounding_box()
                    except Exception:
                        bb = None
                    if bb is not None and bb["width"] > 16 and bb["height"] > 16:
                        # 圆形头像：宽高接近
                        if abs(bb["width"] - bb["height"]) / max(bb["width"], bb["height"]) < 0.3:
                            # 附近 300px 内没有登录按钮才判定为头像
                            if not self._has_login_text_near(el, radius=400):
                                return True
        except Exception:
            pass

        # ============================================================
        # 4) 兜底：整页文本里有"退出登录/个人中心"但没出现"登录/立即登录"按钮
        # ============================================================
        try:
            body_text = (page.text_content("body") or "")
            if "退出登录" in body_text or "个人中心" in body_text:
                # 如果明确有"退出登录"四个字，基本可以确认登录
                if "退出登录" in body_text:
                    return True
                # "个人中心"可能误触发，要求找不到"登录"按钮才算
                if not self._page_has_visible_login_btn():
                    return True
        except Exception:
            pass

        # 5) 无任何凭证，保守判未登录
        return False

    def _page_has_visible_login_btn(self) -> bool:
        """快速扫描：整页是否存在可见、文案为"登录/立即登录"的 a/button。"""
        page = self._page
        if page is None:
            return False
        for sel in ("button", "a"):
            try:
                for el in page.query_selector_all(sel):
                    if not self._safe_visible(el):
                        continue
                    try:
                        txt = (el.inner_text() or "").strip()
                    except Exception:
                        continue
                    if 1 <= len(txt) <= 8 and txt in ("登录", "立即登录", "登陆", "去登录"):
                        return True
            except Exception:
                continue
        return False

    def _has_login_text_near(self, el, radius: int = 400) -> bool:
        """给定元素周边 radius 像素内是否存在可见的'登录'按钮/链接。"""
        page = self._page
        if page is None:
            return False
        try:
            bb = el.bounding_box()
            if bb is None:
                return False
        except Exception:
            return False
        cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
        for sel in ("button", "a"):
            try:
                for other in page.query_selector_all(sel):
                    if not self._safe_visible(other):
                        continue
                    try:
                        txt = (other.inner_text() or "").strip()
                    except Exception:
                        continue
                    if txt not in ("登录", "立即登录", "登陆", "去登录"):
                        continue
                    try:
                        ob = other.bounding_box()
                        if ob is None:
                            continue
                    except Exception:
                        continue
                    ox, oy = ob["x"] + ob["width"] / 2, ob["y"] + ob["height"] / 2
                    if ((ox - cx) ** 2 + (oy - cy) ** 2) ** 0.5 <= radius:
                        return True
            except Exception:
                continue
        return False

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
            "button[aria-label*='Send']",
            # 新版豆包：类名里带 g-send-msg-btn
            "button[class*='g-send-msg-btn']",
            "button[class*='send-msg']",
            # 含 class*=send/Send 兜底
            "button[class*='send']",
            "button[class*='Send']",
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
