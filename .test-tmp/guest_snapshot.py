"""探测豆包「游客态/已登录态」DOM 特征：
目标：用 Playwright 打开 doubao.com/chat/ 后，把页面里所有可见的
  a. 按钮/链接/菜单项的文案（尤其是含"登录/升级/游客/退出/个人中心"）
  b. 含"用户+数字"或头像用户名区的按钮
  c. 登录相关 cookie 名
统一打印出来。不发送任何请求到后端，仅读 DOM。
"""
import os, sys, time
sys.path.insert(0, "/workspace")
os.environ.setdefault("DISPLAY", ":99")
from pathlib import Path
from app.core.config import Config
from app.core.doubao import DoubaoClient

logs=[]
def log(m,l="info"):
    logs.append((l,m)); print(f"[{l}] {m}")

cfg = Config(Path("/tmp/dpa_guest_check.json"))
# 每次用新 profile（确保纯游客态）
profile = Path("/tmp/dpa_guest_check_profile")
if profile.exists():
    import shutil; shutil.rmtree(profile, ignore_errors=True)
profile.mkdir(parents=True, exist_ok=True)
cfg._data["user_data_dir"] = str(profile)
cfg._data["headless"] = True
cfg._data["browser_backend"] = "bundled"
cfg.save()

dc = DoubaoClient(cfg, log)
dc.ensure_browser()
dc.start()
time.sleep(5)  # 等首屏骨架屏加载完
print("URL:", dc._page.url)
print("TITLE:", dc._page.title())

page = dc._page
# cookie 诊断
ctx = dc._context
cookies = ctx.cookies() or []
names = sorted({c.get("name","") for c in cookies if c.get("value")})
print("\n== 现有 cookie（非空）= {} 个 ==".format(len(names)))
for n in names:
    print("  -", n)

# 列出页面上所有可见 button/a，按文本里含关键字符分组
keywords = ["登录","登陆","升级","退出","个人中心","账号","扫码","用户","guest","游客","我的"]
buckets = {k: [] for k in keywords}
other = []
def add(t, tag, cls, box):
    t = t.strip()
    if not t: return
    for kw in keywords:
        if kw in t:
            buckets[kw].append((t, tag, cls, box))
            return
    if len(t) <= 20:
        other.append((t, tag, cls, box))
for sel in ("button", "a", "div[role='button']", "span[role='button']"):
    for el in page.query_selector_all(sel):
        try:
            if not el.is_visible():
                continue
        except Exception:
            continue
        try:
            txt = (el.inner_text() or "").strip()
            cls = (el.get_attribute("class") or "")[:160]
            try:
                box = el.bounding_box()
            except Exception:
                box = None
            add(txt, sel, cls, box)
            # 如果元素子元素有 img（头像），也收集
            imgs = el.query_selector_all("img")
            for img in imgs:
                try:
                    if not img.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    print(f"  [头像img] parent={txt!r} src={str(img.get_attribute('src') or '')[:120]} box={img.bounding_box()}")
                except Exception:
                    pass
        except Exception:
            continue
print("\n== 关键按钮/链接 ==")
for k, arr in buckets.items():
    if arr:
        print(f"  含 '{k}' 的元素 {len(arr)} 个:")
        for txt, tag, cls, box in arr[:12]:
            print(f"    - {tag}: {txt!r} box={box} class[:120]={cls[:120]}")

print("\n== 其他可见 button/a（短文案<=20字）共", len(other), "个，前 40 ==")
for txt, tag, cls, box in other[:40]:
    print(f"    - {tag}: {txt!r:30s} box={box} class[:80]={cls[:80]}")

# 搜索整个 body 文本里出现的关键行
try:
    body_lines = [ln.strip() for ln in (page.text_content("body") or "").splitlines() if ln.strip()]
except Exception:
    body_lines = []
interesting = [ln for ln in body_lines if any(k in ln for k in ["登录","升级","游客","退出登录","个人中心","用户", "扫码登录","登录/注册"])]
print("\n== body 文本里含登录/升级/游客等关键词的行共", len(interesting), "条，前 30 ==")
for ln in interesting[:30]:
    print("   ", ln[:200])

# 检查 is_logged_in 当前状态（应该是 False）与 _find_input / _find_send_button 填字后是否都能命中
def insp(flag):
    el = dc._find_input()
    print(f"\n== 查找输入框（{flag}）==")
    if el is None: print("  None"); return
    try:
        print(f"  box={el.bounding_box()} tag={el.evaluate('e=>e.tagName')} class[:200]={(el.get_attribute('class') or '')[:200]}")
        print(f"  placeholder={el.get_attribute('placeholder')!r} data-placeholder={el.get_attribute('data-placeholder')!r} contenteditable={el.get_attribute('contenteditable')!r} role={el.get_attribute('role')!r}")
    except Exception as e:
        print(f"  err {e}")
insp("空状态")
sb = dc._find_send_button()
print(f"\n== 空输入框时发送按钮 = {sb is not None}")
# 试着点输入框 focus + 写字（不真点发送，因为会创建会话请求）
el = dc._find_input()
if el:
    try:
        el.scroll_into_view_if_needed()
        el.click()
        time.sleep(0.1)
        page.keyboard.insert_text("这是一段测试文字，请忽略")
        time.sleep(0.8)
        insp("填字后")
        sb2 = dc._find_send_button()
        print(f"\n== 填字后发送按钮 = {sb2 is not None}")
        if sb2:
            print(f"   box={sb2.bounding_box()} enabled={sb2.is_enabled()} aria-label={sb2.get_attribute('aria-label')!r} class[:160]={(sb2.get_attribute('class') or '')[:160]}")
    except Exception as e:
        print(f"  err typing: {e}")

print("\n== is_logged_in 当前 =", dc.is_logged_in())
dc.close()
print("\nDONE")
