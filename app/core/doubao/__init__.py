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

    def login_state_file(self) -> Path:
        """登录态额外备份文件：Playwright persistent_context 有时对程序化 cookie 刷盘不及时，
        我们主动把 cookies/localStorage 存一份 JSON，启动时若有就优先 restore。"""
        return self.profile_dir() / "_login_state.json"

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
        # 反反自动化 + 反"缓存不持久化"的启动参数
        extra_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process,OptimizationHints",
            "--enable-features=NetworkService,NetworkServiceInProcess",
        ]
        if sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() == 0:
            extra_args.append("--no-sandbox")
        try:
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=headless,
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
                args=extra_args,
            )
        except Exception as e:
            self._pw.stop()
            self._pw = None
            raise DoubaoError(f"启动浏览器失败：{e}。请先运行 playwright install chromium。")

        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.set_default_timeout(15000)

        # 先 restore 自己备份的登录 cookie（若存在），解决 persistent_context 偶尔丢登录 cookie 的问题
        self._restore_login_state()

        self._page.goto(str(self.config.get("doubao_url")), wait_until="domcontentloaded")
        # 等首屏脚本跑完（至少 header/输入区就绪），避免立即 is_logged_in 误判
        try:
            self._page.wait_for_selector("[contenteditable='true']", timeout=15000, state="attached")
        except Exception:
            pass
        try:
            self._page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        self.log("豆包浏览器已打开。若未登录，请在窗口中扫码/登录，然后点「连接豆包」确认。", "info")

    # ---------- 本机 Edge（CDP） ----------
    def _start_edge(self) -> None:
        """启动/连接本机 Edge：带调试端口打开真实窗口，通过 CDP 操作，保留登录态。"""
        from playwright.sync_api import sync_playwright

        cdp_url = str(self.config.get("edge_cdp_url") or "http://127.0.0.1:9222")
        self._pw = sync_playwright().start()
        self._edge_mode = True

        if not _wait_cdp(cdp_url, timeout=3.0):
            # 端口未就绪：启动 Edge（默认独立 profile，不影响日常使用的 Edge 窗口）
            exe = str(self.config.get("edge_exe") or "") or _find_edge_executable()
            if not exe:
                self._pw.stop()
                self._pw = None
                raise DoubaoError(
                    "未找到本机 Microsoft Edge。请安装 Edge，或在「设置 → 浏览器来源 → Edge」"
                    "中填写 Edge 可执行文件路径。"
                )
            use_system = bool(self.config.get("edge_use_system_profile"))
            if use_system:
                # 直接用你日常的 Edge 配置（里面已有你登录的账号）。
                # 注意：如果 Edge 已经在运行，新进程会并入旧实例且不会开调试端口，
                # 需要先彻底关闭 Edge（包括托盘）再点「连接豆包」。
                profile = None
                self.log(
                    "使用你日常的 Edge 配置打开。若提示端口未就绪，请先彻底退出 Edge"
                    "（含右下角托盘图标），再点「连接豆包」。",
                    "info",
                )
            else:
                profile = str(self.config.get("edge_profile") or "") or str(app_dir() / "edge_profile")
                Path(profile).mkdir(parents=True, exist_ok=True)
            cmd = [
                exe,
                f"--remote-debugging-port={_cdp_port(cdp_url)}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            if profile:
                cmd.append(f"--user-data-dir={profile}")
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
        self._restore_login_state()  # CDP 模式下也尝试 restore 自己的备份
        self._page.goto(str(self.config.get("doubao_url")), wait_until="domcontentloaded")
        try:
            self._page.wait_for_selector("[contenteditable='true']", timeout=15000, state="attached")
        except Exception:
            pass
        try:
            self._page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        self.log("已连接本机 Edge 窗口。若未登录，请在 Edge 窗口中扫码/登录，然后点「连接豆包」确认。", "info")

    # ---------- 登录态备份/恢复（persistent profile 之外的兜底 JSON） ----------
    def _save_login_state(self) -> None:
        if self._context is None:
            return
        try:
            state = self._context.storage_state()
            # 精简：只保留有 value 的 cookie 与 origins，避免 JSON 过大
            if "cookies" in state:
                state["cookies"] = [c for c in state["cookies"] if c.get("value")]
            path = self.login_state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            import json as _json
            path.write_text(_json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _restore_login_state(self) -> None:
        if self._context is None:
            return
        path = self.login_state_file()
        if not path.exists() or path.stat().st_size <= 4:
            return
        try:
            import json as _json
            state = _json.loads(path.read_text(encoding="utf-8"))
            cookies = state.get("cookies") or []
            if cookies:
                # add_cookies 对域敏感：过期的会被拒绝，这里 try 单个，失败就跳过
                try:
                    self._context.add_cookies(cookies)
                except Exception:
                    for c in cookies:
                        try:
                            self._context.add_cookies([c])
                        except Exception:
                            continue
            origins = state.get("origins") or []
            if origins and self._page is not None:
                for origin_block in origins:
                    origin_url = origin_block.get("origin")
                    if not origin_url:
                        continue
                    for ls in origin_block.get("localStorage", []):
                        try:
                            self._page.evaluate(
                                """({o, k, v}) => {
                                    try { localStorage.setItem(k, v); } catch(e) {}
                                }""",
                                {"o": origin_url, "k": ls.get("name"), "v": ls.get("value")},
                            )
                        except Exception:
                            continue
        except Exception:
            pass

    def close(self) -> None:
        # 在 context 还活着时先把登录态做一份 JSON 备份（兜底 persistent_context 刷盘失败）
        try:
            self._save_login_state()
        except Exception:
            pass
        try:
            if self._edge_mode:
                # 只关闭本软件开的标签页，保留用户 Edge 与登录态
                if self._page is not None and not self._page.is_closed():
                    self._page.close()
            elif self._context:
                # 再触发一次 cookies 读取，督促浏览器把 cookie 写到磁盘
                try:
                    _ = self._context.cookies()
                except Exception:
                    pass
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

    def is_logged_in(self, *, with_reason: bool = False) -> bool | tuple[bool, str]:
        """
        返回值：
          - 默认只返回 bool（True/False）。
          - with_reason=True 时返回 (bool, reason_text)：reason_text 会写入 GUI 操作日志，
            帮助用户一眼看懂「为什么判我未登录 / 为什么判我已登录」。
        """
        reason_lines: list[str] = []
        def _ok(r: str) -> bool:
            reason_lines.append("✔ " + r)
            return True
        def _bad(r: str) -> bool:
            reason_lines.append("✘ " + r)
            return False

        if not self._started or not self._page:
            reason_lines.append("✘ 浏览器/页面尚未启动")
            return (False, "\n".join(reason_lines)) if with_reason else False
        page = self._page
        ctx = self._context

        # 0) Cookie 凭证优先
        try:
            if ctx is not None:
                cookies = ctx.cookies() or []
                names = {str(c.get("name", "")).lower() for c in cookies if c.get("value")}
                hits = [n for n in self._AUTH_COOKIE_NAMES if n.lower() in names]
                if hits:
                    ok = _ok(f"Cookie 命中登录凭证：{', '.join(hits)}")
                    return (ok, "\n".join(reason_lines)) if with_reason else ok
                else:
                    reason_lines.append(
                        f"— Cookie 未命中登录凭证（当前 cookie {len(names)} 个："
                        f"{', '.join(sorted(names)[:12])}{'…' if len(names) > 12 else ''}）"
                    )
        except Exception as e:
            reason_lines.append(f"— 读取 cookie 失败：{e}")

        # 1) 登录弹窗 = 未登录
        found_modal_login = False
        for sel in self._LOGIN_MODAL_SELECTORS:
            try:
                for m in page.query_selector_all(sel):
                    if not self._safe_visible(m):
                        continue
                    try:
                        text = m.inner_text() or ""
                    except Exception:
                        text = ""
                    if any(k in text for k in ("登录", "扫码登录", "手机号登录", "短信登录", "密码登录", "登 录")):
                        found_modal_login = True
                        break
            except Exception:
                pass
            if found_modal_login:
                break
        if found_modal_login:
            bad = _bad("页面弹出登录/扫码对话框，豆包需要你在弹窗里登录")
            return (bad, "\n".join(reason_lines)) if with_reason else False
        else:
            reason_lines.append("— 未发现登录弹窗")

        # 2) header/nav 范围下扫描"登录/立即登录/登陆"按钮 = 未登录
        visible_login_btns: list[tuple[str, str]] = []  # (text, class_snippet)
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
                            cls = (el.get_attribute("class") or "")[:80]
                            visible_login_btns.append((txt, cls))
                    except Exception:
                        continue
        except Exception:
            pass
        if visible_login_btns:
            texts = sorted({t for t, _ in visible_login_btns})
            bad = _bad(
                "在页面顶栏发现 '" + "、".join(texts) + "' 按钮，说明你目前是【游客会话】："
                "豆包允许游客看界面、看推荐题，但发送消息、保存聊天、跨端同步账号都需要真实登录。"
                "👉 请点击浏览器右上角这个'登录'按钮，用豆包 App 扫码登录，完成后再回软件点「连接豆包」。"
            )
            return (bad, "\n".join(reason_lines)) if with_reason else False
        else:
            reason_lines.append("— 页面顶栏没有'登录'按钮（好现象）")

        # 2.5) 无登录按钮 + 聊天输入框可用 = 已登录
        #      （游客页必然带右上角『登录』按钮——已用真实页面验证；登录后换成头像/菜单，
        #        所以"无登录按钮 + 有输入框"就是最可靠的已登录信号）
        try:
            if not self._page_has_visible_login_btn() and self._find_input() is not None:
                ok = _ok("页面没有任何『登录/立即登录』按钮，且聊天输入框可用 = 已登录")
                return (ok, "\n".join(reason_lines)) if with_reason else ok
        except Exception:
            pass

        # 3) 正向登录态元素 = 已登录
        try:
            for sel in self._LOGGED_IN_ONLY_SELECTORS:
                try:
                    els = page.query_selector_all(sel)
                except Exception:
                    continue
                for el in els:
                    if not self._safe_visible(el):
                        continue
                    try:
                        inner = (el.inner_text() or "").strip()
                    except Exception:
                        inner = ""
                    if inner in ("退出登录", "个人中心", "账号与安全", "我的"):
                        ok = _ok(f"菜单中出现『{inner}』= 已登录")
                        return (ok, "\n".join(reason_lines)) if with_reason else ok
                    try:
                        bb = el.bounding_box()
                    except Exception:
                        bb = None
                    if bb is not None and bb["width"] > 16 and bb["height"] > 16:
                        if abs(bb["width"] - bb["height"]) / max(bb["width"], bb["height"]) < 0.3:
                            if not self._has_login_text_near(el, radius=400):
                                try:
                                    cls = (el.get_attribute("class") or "")[:60]
                                except Exception:
                                    cls = ""
                                ok = _ok(
                                    f"顶栏发现圆形头像元素 ({int(bb['x'])},{int(bb['y'])}, "
                                    f"{int(bb['width'])}x{int(bb['height'])}, class[:60]={cls!r})"
                                )
                                return (ok, "\n".join(reason_lines)) if with_reason else ok
        except Exception:
            pass
        reason_lines.append("— 暂未发现正例（头像/退出登录等）")

        # 4) 兜底：整页文本里有"退出登录/个人中心"但没出现"登录/立即登录"按钮
        try:
            body_text = (page.text_content("body") or "")
            if "退出登录" in body_text:
                ok = _ok("整页文本里包含'退出登录'= 已登录")
                return (ok, "\n".join(reason_lines)) if with_reason else ok
            if "个人中心" in body_text and not self._page_has_visible_login_btn():
                ok = _ok("整页文本里包含'个人中心'且无'登录'按钮 = 已登录")
                return (ok, "\n".join(reason_lines)) if with_reason else ok
        except Exception:
            pass

        bad = _bad(
            "综合判定未登录："
            "既没有登录系 cookie、页面存在『登录』按钮、也没有出现头像或菜单。"
            "如果你确实已登录但仍显示未登录，请点一下顶部『豆包』状态胶囊手动重检；"
            "或改用「设置 → 浏览器来源 → 本机 Edge」+『用我日常的 Edge 配置』直接复用你已登录的账号。"
        )
        return (bad, "\n".join(reason_lines)) if with_reason else False

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
    # 注意：新版豆包的输入框是 Tiptap ProseMirror，有两个强特征可以精确定位、
    #       避免把 header 搜索框 / 侧边筛选框等其他 contenteditable 命中。
    _INPUT_CANDIDATES = [
        # 最强：ProseMirror 的空段落里有这个占位
        "[data-placeholder='发消息...']",
        # 次强：类名里直接包含 Tiptap/ProseMirror（React 渲染聊天输入）
        "div[class*='ProseMirror'][contenteditable='true']",
        "div[class*='tiptap'][contenteditable='true']",
        # 通用兜底：role=textbox 且可见 + 尺寸足够大（聊天输入框比搜索框宽得多）
        "div[role='textbox'][contenteditable='true']",
        "div[role='textbox']",
        "[contenteditable='true']",
        "textarea[placeholder]",
        "textarea",
    ]

    def _find_input(self) -> Optional[object]:
        page = self._page
        if page is None:
            return None
        for sel in self._INPUT_CANDIDATES:
            try:
                for el in page.query_selector_all(sel):
                    if not (el and self._safe_visible(el)):
                        continue
                    # 宽高太小的（比如 1px 搜索框）直接丢弃
                    try:
                        bb = el.bounding_box()
                        if bb and (bb["width"] < 200 or bb["height"] < 16):
                            continue
                    except Exception:
                        pass
                    return el
            except Exception:
                continue
        return None

    _SEND_BTN_SELECTORS = [
        # 文案 aria-label（最理想，无需依赖 class）
        "button[aria-label*='发送']",
        "button[aria-label*='Send']",
        # 新版豆包：背景直接用了 send-msg-btn-bg / 尺寸 size-36 的圆形按钮
        "button[class*='g-send-msg-btn']",
        "button[class*='g-send-msg-btn-bg']",
        "button[class*='send-msg-btn']",
        "button[class*='size-36']",
        "button[class*='shrink-0'][class*='rounded-full']",
        # 兜底：含 send/Send 的 class
        "button[class*='send']",
        "button[class*='Send']",
    ]

    def _find_send_button(self) -> Optional[object]:
        """找『发送』按钮：必须位于输入框右半侧（避免命中左下角的工具栏按钮）。

        新版豆包：输入区右侧的圆形按钮在空输入时是『上传/加号』，填字后才变成发送。
        所以本方法优先返回「位于输入框右半侧」的候选；没有命中时退回任何可见候选
        （最后还会走 Ctrl+Enter 兜底，见 _send）。
        """
        page = self._page
        input_el = self._find_input()
        input_box = None
        try:
            if input_el is not None:
                input_box = input_el.bounding_box()
        except Exception:
            input_box = None

        def _in_right_half(el) -> bool:
            if input_box is None:
                return True
            try:
                bb = el.bounding_box()
            except Exception:
                return False
            if bb is None:
                return False
            # 右半侧：按钮中心 x >= 输入框中心 x，且垂直方向在输入框附近 ±120px
            input_cx = input_box["x"] + input_box["width"] / 2
            input_bottom = input_box["y"] + input_box["height"]
            cx = bb["x"] + bb["width"] / 2
            return cx >= input_cx - 12 and abs(bb["y"] - input_bottom) <= 120

        candidates: list[object] = []
        for sel in self._SEND_BTN_SELECTORS:
            try:
                for el in page.query_selector_all(sel):
                    try:
                        if not (el and self._safe_visible(el) and el.is_enabled()):
                            continue
                    except Exception:
                        continue
                    candidates.append(el)
            except Exception:
                continue
        # 优先：位于输入框右半侧
        for el in candidates:
            if _in_right_half(el):
                return el
        # 兜底：任意可见候选（交给 _send 的 Ctrl+Enter 决策）
        if candidates:
            return candidates[0]
        return None

    # ---------- 发送 ----------
    def ask(self, instruction: str, image: bytes | None = None, timeout: int = 180) -> str:
        if not self._started or not self._page:
            raise DoubaoError("豆包浏览器未启动，请先点击「连接豆包」。")
        # 登录检测不阻塞发送：能打字、能发出去、能收到回复 = 可用。
        # 检测到未登录时仅告警并照常尝试；若豆包真挡住发送，_wait_response 会
        # 在弹出登录框时立刻给出登录指引，而不是干等超时。
        try:
            if not self.is_logged_in():
                self.log(
                    "当前未检测到登录状态，但仍将尝试直接发送。"
                    "如果发送失败或弹出登录框，请按提示在浏览器里登录。",
                    "warn",
                )
        except Exception:
            pass

        page = self._page
        base_text = self._conversation_text()
        self._send(instruction, image)
        return self._wait_response(instruction, base_text, timeout)

    def _send(self, text: str, image: bytes | None) -> None:
        page = self._page
        el = self._find_input()
        if el is None:
            raise DoubaoError("找不到输入框，请确认豆包页面已加载并登录。")

        # 1) 先聚焦聊天输入框，并确保光标落在 contenteditable 内部
        try:
            el.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            el.click(timeout=3000)
            time.sleep(0.08)
        except Exception:
            pass
        # 用 evaluate 再强制 focus，避免 click 被 Popover/overlay 拦截
        try:
            el.evaluate("e => { e.focus && e.focus(); const sel = window.getSelection(); if(sel && e.firstChild){ const r = document.createRange(); r.selectNodeContents(e); r.collapse(false); sel.removeAllRanges(); sel.addRange(r); } }")
        except Exception:
            pass

        # 2) 上传图片（上传完成后焦点可能被偷走，之后要再 focus 一次）
        if image is not None:
            self._attach_image(image)
            try:
                el.evaluate("e => { e.focus && e.focus(); }")
            except Exception:
                pass
            time.sleep(0.25)

        # 3) 把文字写进去 —— 三条路径，按优先级切换：
        #    - 优先 page.keyboard.insert_text（原生输入法，能真的触发 React onChange）
        #    - 失败或空文本：page.keyboard.type（逐键）
        #    - 再失败：直接写 contenteditable.innerHTML + 派发 input/change 事件（强制让受控组件感知）
        text = str(text or "")
        wrote_ok = False
        if text:
            try:
                page.keyboard.insert_text(text)
                wrote_ok = True
            except Exception:
                try:
                    page.keyboard.type(text, delay=6)
                    wrote_ok = True
                except Exception:
                    wrote_ok = False
            if not wrote_ok:
                try:
                    # evaluate 直接塞 DOM + 派发 input，让 ProseMirror 的 onChange 感知到
                    esc = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
                    el.evaluate(
                        f"(e) => {{"
                        f"  const p = document.createElement('p');"
                        f"  p.textContent = `{esc}`;"
                        f"  // 清空 ProseMirror 之前的空占位 p"
                        f"  const empty = e.querySelector('p.is-empty, p[data-placeholder]');"
                        f"  if (empty && (!empty.textContent || !empty.textContent.trim())) empty.remove();"
                        f"  e.appendChild(p);"
                        f"  e.dispatchEvent(new Event('input', {{bubbles:true, cancelable:true}}));"
                        f"  e.dispatchEvent(new Event('change', {{bubbles:true}}));"
                        f"  e.dispatchEvent(new KeyboardEvent('keyup', {{bubbles:true}}));"
                        f"}}"
                    )
                    wrote_ok = True
                except Exception as e:
                    raise DoubaoError(f"输入文字失败：{e}")
            # 等 React 重渲染让「发送」按钮出现并变可用（新版豆包输入空时按钮 hidden）
            for _ in range(15):
                try:
                    if (el.inner_text() or "").strip():
                        break
                except Exception:
                    pass
                time.sleep(0.08)

        # 4) 填字/图片后 **再** 找发送按钮（空输入时按钮可能 display:none）
        send_btn = self._find_send_button()
        if send_btn is None and (text or image):
            # 等 0.5 秒按钮淡入
            for _ in range(10):
                send_btn = self._find_send_button()
                if send_btn is not None:
                    break
                time.sleep(0.06)

        sent = False
        if send_btn is not None:
            try:
                send_btn.click(timeout=3000)
                sent = True
                self.log("已点击发送按钮，消息已提交给豆包。", "info")
            except Exception:
                sent = False
        if not sent:
            # 兜底发送：豆包默认支持 Ctrl+Enter 发送（Enter 是换行）
            try:
                # 确保焦点回到输入框
                try:
                    el.click(timeout=1500)
                except Exception:
                    pass
                page.keyboard.press("Control+Enter")
                sent = True
                self.log("未找到发送按钮，已用 Ctrl+Enter 发送。", "info")
            except Exception as e:
                # 再尝试一下普通 Enter（极少数设置把 Enter 改成发送）
                try:
                    page.keyboard.press("Enter")
                    sent = True
                    self.log("未找到发送按钮，已用 Enter 发送。", "info")
                except Exception as e2:
                    raise DoubaoError(f"发送失败：按钮点击与回车都失败：{e2} / {e}")

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
            # 快速失败：发送后豆包弹出登录框（游客被拦）→ 立刻给指引，别干等
            try:
                if not self.is_logged_in():
                    modal = self._login_modal_visible()
                    if modal:
                        raise DoubaoError(
                            "豆包弹出登录框，消息没有发出去。\n"
                            "👉 请在打开的浏览器窗口里点击『登录』，用豆包 App 扫码登录，\n"
                            "   回到软件点顶部『豆包』状态胶囊重检后再发送。\n"
                            "（如果你确实已在浏览器里登录了账号，请改用「设置 → 浏览器来源 → 本机 Edge」"
                            "并勾选『用我日常的 Edge 配置』，就能直接读到你的登录态。）"
                        )
            except DoubaoError:
                raise
            except Exception:
                pass

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

    def _login_modal_visible(self) -> bool:
        """当前页面是否弹出可见的登录/扫码对话框。"""
        page = self._page
        if page is None:
            return False
        for sel in self._LOGIN_MODAL_SELECTORS:
            try:
                for m in page.query_selector_all(sel):
                    if not self._safe_visible(m):
                        continue
                    try:
                        text = m.inner_text() or ""
                    except Exception:
                        text = ""
                    if any(k in text for k in ("登录", "扫码登录", "手机号登录", "短信登录", "密码登录", "登 录")):
                        return True
            except Exception:
                continue
        return False

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
