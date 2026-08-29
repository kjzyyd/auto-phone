"""检查：
(1) DoubaoClient 第二次启动是否真的复用 profile（cookie 数量对比）
(2) _find_input 找到的元素是不是"豆包聊天输入框"（不是搜索框等其他 contenteditable）
(3) 多种写字方式中，哪种真能把文字写进 contenteditable（新版豆包前端是 React 受控，fill/type 全局可能不生效）
"""
import os, sys, time, json
sys.path.insert(0, "/workspace")
os.environ.setdefault("DISPLAY", ":99")
from pathlib import Path
from app.core.config import Config, app_dir
from app.core.doubao import DoubaoClient

profile_root = Path("/tmp/dpa_profile_test")
if profile_root.exists():
    import shutil
    shutil.rmtree(profile_root, ignore_errors=True)
profile_root.mkdir(parents=True, exist_ok=True)

cfg = Config(Path("/tmp/dpa_send_check.json"))
# 强制把 profile 改到 /tmp/dpa_profile_test/doubao_profile（非用户真实目录，避免污染）
cfg._data["user_data_dir"] = str(profile_root / "doubao_profile")
cfg._data["headless"] = True
cfg._data["doubao_url"] = "https://www.doubao.com/chat/"
cfg._data["browser_backend"] = "bundled"
cfg.save()

logs = []
def log(m, l="info"):
    logs.append((l, m))
    print(f"[{l}] {m}")

def inspect_ctx(label, dc):
    ctx = dc._context
    print(f"\n== {label} cookie 诊断 ==")
    if ctx is None:
        print("  ctx = None")
        return 0
    cookies = ctx.cookies() or []
    nonempty = [c for c in cookies if c.get("value")]
    names = sorted({c.get("name", "") for c in nonempty})
    doubao = [n for n in names if any(k in n.lower() for k in ("sid","session","uid","passport","odin"))]
    print(f"  cookie 总数: {len(cookies)}, 非空: {len(nonempty)}")
    print(f"  登录相关 cookie: {doubao[:30]}")
    return len(nonempty)

def inspect_input(label, el):
    print(f"\n== {label} 输入框诊断 ==")
    if el is None:
        print("  _find_input = None!")
        return
    try:
        print(f"  tag: {el.evaluate('e=>e.tagName')}")
    except Exception as e:
        print(f"  tag error: {e}")
    try:
        print(f"  contenteditable = {el.get_attribute('contenteditable')}")
        print(f"  role = {el.get_attribute('role')}")
        print(f"  placeholder = {el.get_attribute('placeholder')}")
        print(f"  aria-placeholder = {el.get_attribute('aria-placeholder')}")
        cls = (el.get_attribute("class") or "")[:200]
        print(f"  class[:200] = {cls}")
    except Exception as e:
        print(f"  attr error: {e}")
    try:
        bb = el.bounding_box()
        print(f"  box = {bb}")
    except Exception as e:
        print(f"  box error: {e}")
    try:
        text = (el.inner_text() or "")
        html = (el.inner_html() or "")
        print(f"  inner_text[:200] = {text[:200]!r}")
        print(f"  inner_html[:300] = {html[:300]!r}")
    except Exception as e:
        print(f"  content error: {e}")
    # 向上爬 2 层容器，看附近有没有 send / 上传按钮 / 图片按钮（确认为聊天输入）
    try:
        container = el.evaluate_handle("e => e.closest('form') || e.parentElement?.parentElement?.parentElement || null")
        if container:
            btns = container.query_selector_all("button")
            visible_btns = [b for b in btns if b.is_visible()]
            print(f"  附近 form/container 可见按钮数: {len(visible_btns)}")
            for i, b in enumerate(visible_btns[:8]):
                txt = (b.inner_text() or "").strip()[:40]
                cls_b = (b.get_attribute("class") or "")[:100]
                try:
                    aria = b.get_attribute("aria-label") or ""
                except Exception:
                    aria = ""
                print(f"    [{i}] text={txt!r} aria={aria[:40]!r} class={cls_b[:80]}")
    except Exception as e:
        print(f"  container error: {e}")

# ---------- run ----------
# 第一次启动
dc1 = DoubaoClient(cfg, log)
dc1.ensure_browser()
dc1.start()
print("打开后URL:", dc1._page.url)
print("title:", dc1._page.title())
time.sleep(3)
el1 = dc1._find_input()
inspect_input("FIRST_FIND_INPUT", el1)
send1 = dc1._find_send_button()
print(f"\n== FIRST 发送按钮 ==")
if send1 is not None:
    try:
        print(f"  class[:180]={(send1.get_attribute('class') or '')[:180]}")
        print(f"  aria-label={send1.get_attribute('aria-label')!r}")
        print(f"  visible={send1.is_visible()} box={send1.bounding_box()}")
    except Exception as e:
        print(f"  send_btn err: {e}")
else:
    print("  没找到发送按钮！")

# 填字测试（每种方式之前都要清空）
def clear_and_wait(el):
    try:
        # 先聚焦
        el.click()
        time.sleep(0.2)
        page = dc1._page
        page.keyboard.press("Control+A")
        time.sleep(0.05)
        page.keyboard.press("Backspace")
        time.sleep(0.2)
    except Exception as e:
        print("    clear err:", e)

if el1 is not None:
    page = dc1._page
    tests = [
        ("A_keyboard_insert_text", lambda text: page.keyboard.insert_text(text)),
        ("B_keyboard_type", lambda text: page.keyboard.type(text, delay=5)),
        ("C_element_eval_innerHTML",
            lambda text: el1.evaluate("(e, t) => { e.innerHTML = t + '<br/>'; const evt = new Event('input', {bubbles:true}); e.dispatchEvent(evt); const ce = new Event('change', {bubbles:true}); e.dispatchEvent(ce); return true; }", text)),
        ("D_element_type", lambda text: el1.type(text, delay=5)),
    ]
    print("\n== 填写方式对比（每条前清空） ==")
    for name, fn in tests:
        try:
            clear_and_wait(el1)
            payload = f"你好_{name[-6:]}"
            fn(payload)
            time.sleep(0.6)
            seen_text = (el1.inner_text() or "").strip()
            seen_html = (el1.inner_html() or "")
            ok = payload in seen_text or payload.replace("_","__") in seen_text
            print(f"  {name}: 预期={payload!r} 实际文本={seen_text[:80]!r} 成功={ok}")
            if not ok:
                print(f"    html[:200]={seen_html[:200]!r}")
            # 关键：写完字后检查发送按钮是否可见（修复前空输入框不会出现）
            if ok:
                sb = dc1._find_send_button()
                if sb is None:
                    # 等 0.6s 给前端淡入
                    time.sleep(0.6)
                    sb = dc1._find_send_button()
                if sb is not None:
                    try:
                        print(f"    ✔ 发送按钮命中: box={sb.bounding_box()} aria-label={sb.get_attribute('aria-label')!r}")
                    except Exception as e:
                        print(f"    ✔ 发送按钮命中: {e}")
                else:
                    # 诊断：当前有哪些可见 button
                    print("    ✘ 仍找不到发送按钮，列出所有可见 class 包含 send/rounded-full/size 的按钮：")
                    try:
                        for b in page.query_selector_all("button"):
                            try:
                                if not b.is_visible(): continue
                                cls = (b.get_attribute("class") or "")[:200]
                                if any(k in cls for k in ("send","Send","rounded-full","size-36","g-send","shrink-0")):
                                    print(f"      class[:200]={cls} box={b.bounding_box()} aria-label={b.get_attribute('aria-label')!r} inner={(b.inner_text() or '').strip()[:40]!r}")
                            except Exception:
                                continue
                    except Exception as e2:
                        print(f"      enum error {e2}")
                    # 再打印输入框附近的所有可见按钮（5 个内）
                    try:
                        container = el1.evaluate_handle("e => e.closest('form') || e.parentElement?.parentElement?.parentElement?.parentElement || null")
                        if container:
                            print("    输入框上层容器可见按钮:")
                            n = 0
                            for b in container.query_selector_all("button"):
                                try:
                                    if not b.is_visible(): continue
                                except Exception:
                                    continue
                                n += 1
                                if n > 10: break
                                try:
                                    cls = (b.get_attribute("class") or "")[:200]
                                    print(f"      [{n}] box={b.bounding_box()} cls[:200]={cls} aria-label={b.get_attribute('aria-label')!r} inner={(b.inner_text() or '').strip()[:40]!r}")
                                except Exception as e2:
                                    print(f"      [{n}] err {e2}")
                    except Exception as e3:
                        print(f"    container error {e3}")
        except Exception as e:
            print(f"  {name}: 异常 {e}")

# 检查 cookie 数量（第一次启动后，如果扫码登录过，这里会 > 0；沙箱没扫码，登录系 cookie 可能为 0，但其它 doubao 域名 cookie 应该有）
c1 = inspect_ctx("FIRST start", dc1)

# 模拟"写一个假的登录 cookie"到 profile，用于第二次启动是否复用
# （用户场景：第一次扫码登录后，profile 里应当存了 cookie；第二次启动应该直接读出来）
fake_cookie_domain = ".doubao.com"
try:
    dc1._context.add_cookies([
        {"name": "sessionid_ss", "value": "FAKE_SESSION_12345",
         "domain": fake_cookie_domain, "path": "/", "httpOnly": True, "secure": True,
         "sameSite": "Lax"},
        {"name": "sid_guard", "value": "FAKE_SID_GUARD|1234567890",
         "domain": fake_cookie_domain, "path": "/", "secure": True,
         "sameSite": "Lax"},
        {"name": "uid_tt", "value": "abcdef12345",
         "domain": fake_cookie_domain, "path": "/", "secure": True,
         "sameSite": "Lax"},
    ])
    print("\n== 注入假登录 cookie 成功 ==")
except Exception as e:
    print(f"\n== 注入假登录 cookie 失败（不阻塞，继续测）: {e}")

c1_after_fake = inspect_ctx("AFTER fake cookie", dc1)
print("is_logged_in() after inject fake cookie:", dc1.is_logged_in())

# 关闭（这一步应该由 playwright 持久化 profile 写入磁盘）
dc1.close()
time.sleep(2)

# 第二次启动（profile 相同路径）
dc2 = DoubaoClient(cfg, log)
dc2.start()
time.sleep(3)
print("\n第二次 URL:", dc2._page.url)
c2 = inspect_ctx("SECOND start", dc2)
print(f"\n== Profile 复用诊断 ==")
print(f"  第一次 cookie(非空): {c1}")
print(f"  假 cookie 注入后:      {c1_after_fake}")
print(f"  第二次 cookie(非空):   {c2}")
print(f"  ✔ 第二次自动识别登录: {dc2.is_logged_in()}  (预期 True)")

# 再测一次 _find_input 能找到 & 发送按钮仍然有效
el2 = dc2._find_input()
inspect_input("SECOND_FIND_INPUT", el2)

dc2.close()
print("\nDONE")
