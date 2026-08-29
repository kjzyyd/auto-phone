"""Inspect doubao.com DOM on landing page (guest vs logged-in signatures)."""
import os, sys, time
sys.path.insert(0, "/workspace")
from app.core.config import Config
from app.core.doubao import DoubaoClient
from pathlib import Path

cfg = Config(Path("/tmp/dpa_dom_inspect.json"))
os.environ.setdefault("DISPLAY", ":99")

dc = DoubaoClient(cfg)
dc.ensure_browser()
dc.start()
time.sleep(3)

# 登录检测所用的元素
checks = [
    ("button[class*='login-btn-header']", "header login button"),
    ("a[href*='login']", "login anchor"),
    ("button:has-text('登录')", "login-text button"),
    ("button[data-testid*='login']", "login testid button"),
    ("div[class*='LoginModal'],div[class*='login-modal']", "login modal"),
    ("div[class*='Avatar'],button[class*='avatar'],img[class*='avatar']", "avatar element"),
    ("[class*='user-info'],[class*='UserInfo']", "user info box"),
    ("div[class*='Header'] [class*='username'],[class*='nick-name']", "username"),
    ("button[class*='logout'],button:has-text('退出')", "logout button"),
    ("[data-testid='app-header-right']", "header right area"),
    ("[class*='Header'] [class*='right']", "header right generic"),
]

print("当前 URL:", dc._page.url)
print("Title:", dc._page.title())
for sel, name in checks:
    try:
        els = dc._page.query_selector_all(sel)
        visible = [e for e in els if e.is_visible()]
        if els:
            print(f"  ✔ {name}: {len(els)} elems, visible={len(visible)}")
            # Print class name hint for visible ones
            if visible:
                cls = visible[0].get_attribute("class") or ""
                inner = (visible[0].inner_text() or "").strip()[:60]
                print(f"     class={cls[:80]}")
                print(f"     text={inner!r}")
    except Exception as e:
        print(f"  {name}: error {e}")

# Try sending actual test content to see guest behavior
inp = dc._find_input()
print("\n找到输入框:", inp is not None)
# 尝试实际 fill + click send，观察是否弹出登录窗
try:
    if inp:
        inp.click()
        inp.fill("测试")
        time.sleep(1)
        sbtn = dc._find_send_button()
        print("发送按钮:", sbtn is not None)
        if sbtn:
            print("  send 按钮 class:", sbtn.get_attribute("class"))
            # 不真的点击发送，只是看 send button 状态
            disabled = sbtn.get_attribute("disabled")
            print("  send disabled attr:", disabled)
            print("  send visible:", sbtn.is_visible(), "enabled:", sbtn.is_enabled())
except Exception as e:
    print("fill test error:", e)

dc.close()
