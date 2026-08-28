# 豆包手机助手（Doubao Phone Assistant）

用**网页版豆包 AI** 驱动 **adb**，自动操作你的安卓手机（支持 Android 16）。

你在电脑软件里下指令（比如「打开微信，给张三发消息：晚上一起吃饭，然后回到桌面」），
软件把手机屏幕截图发给豆包，豆包看懂画面后输出操作步骤，软件再用 adb 真实点击 / 滑动 / 输入，
循环直到任务完成。

```
你输入指令 ──► 截图手机屏幕 ──► 发给网页版豆包 ──► 豆包给出动作 ──► adb 执行 ──► 新截图 ──► … ──► 完成
```

## 功能

- **AI 操作手机**：豆包看屏幕，自动点击 / 滑动 / 输入中文 / 按键 / 打开应用，逐轮执行直到任务完成。
- **中文输入**：优先 uiautomator2 后端，自动通过 adb 部署 ADBKeyboard，支持中文（无需手动装 App）。
- **网页版豆包**：Playwright 打开 `doubao.com/chat`，扫码登录一次，登录态长期保存。
- **屏幕预览**：实时显示手机画面，**单击预览画面 = 在手机上点击该位置**（可手动干预纠正 AI）。
- **美化界面**：暗色 + 豆包蓝紫渐变主题。
- **完整日志**：每一步截图 / 点击 / 滑动 / 输入都记录在「操作日志」。

## 环境要求（电脑端）

- Windows 10/11（打包 exe）或任意系统运行源码
- Python 3.12（运行源码时需要）
- **Android platform-tools（adb）**：<https://developer.android.com/tools/releases/platform-tools>，把解压目录加入 PATH，或安装后把 `adb.exe` 放到 exe 同目录
- 手机：开启「开发者选项 → USB 调试」，用数据线连接（或开启「无线调试」用 ip:port 连接）
- 豆包账号（登录用）

## 快速开始（源码运行）

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
python -m playwright install chromium   # 首次需要下载浏览器
python -m app.main
```

## 使用步骤

1. **连接手机**：USB 连接后点「连接手机」。若手机上弹出「是否允许 USB 调试」，勾选并允许。
   - 无线调试：手机「开发者选项 → 无线调试」开启后，在左侧输入 `ip:端口` 点「无线连接」。
2. **连接豆包**：点「连接豆包」，会自动打开豆包网页，用**手机扫码登录**。登录完成后等待状态变为「豆包已登录」。
3. **发送指令**：在底部输入框输入自然语言指令，回车或点「发送指令」。例如：
   - `打开微信，给张三发消息：晚上一起吃饭`
   - `帮我把屏幕亮度调到最低`
   - `打开抖音，随便刷三个视频`
   - `进入设置，查看存储空间`
4. **随时干预**：点击左侧预览画面可手动点击手机；点「停止」结束任务；「操作日志」可查看每一步。

## 常见问题

| 问题 | 处理 |
| --- | --- |
| 连接失败「未发现设备」 | 检查 USB 调试是否开启、驱动是否装好、`adb devices` 能否看到设备 |
| 提示没找到 adb | 安装 platform-tools 并加 PATH，或在「设置」里指定 adb 路径 |
| 豆包登录后仍显示未登录 | 在豆包网页里随便发一条消息，确认输入框可用后点「连接豆包」重试 |
| 中文输入无效 | 确认「设置 → 优先使用 uiautomator2 后端」已勾选（首次会自动部署组件） |
| 任务轮数不够 | 「设置 → 最大操作轮数」调大 |

## 打包成 exe

### 方式一：本地打包（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File build\build_win.ps1
```

产物在 `dist\豆包手机助手\豆包手机助手.exe`（含 Playwright 浏览器，首次打开即用）。

### 方式二：GitHub Actions 自动打包（无需本地环境）

把本项目推到 GitHub，在 **Actions** 页面选择 `Build Windows exe` → **Run workflow**，
运行完下载 `豆包手机助手-win64` 工件，解压即得 exe。

> 说明：Playwright 浏览器会打进 dist 目录（约 300MB），因此 exe 首次打开**无需再下载浏览器**。

## 项目结构

```
app/
├── main.py                  # 入口
├── core/
│   ├── config.py            # 配置（用户目录持久化）
│   ├── parser.py            # 豆包回复 → adb 动作解析
│   ├── prompt.py            # 发给豆包的提示词/指令语法
│   ├── agent.py             # Agent 循环（截图→问→执行→再截图）
│   ├── device/              # 设备控制：uiautomator2 + 纯 adb 双后端
│   └── doubao/              # Playwright 驱动网页版豆包
└── gui/                     # PySide6 界面（主题/主窗口/控件/设置）
```

## 免责声明

请仅在你有权的设备上使用，并遵守相关软件服务条款。本项目仅供学习自动化技术。
