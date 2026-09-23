# AI 智阅小助手

面向教师的 Windows 桌面辅助阅卷工具，支持答题区域识别、AI 辅助评分、批量阅卷流程与结果导出。

## 功能

- 配置识别框、打分框和提交框，辅助网页阅卷操作
- 通过 OpenAI 兼容接口调用 AI 服务进行识别和评分
- 支持单评、双评与分歧仲裁工作流
- 保存配置方案与阅卷历史，并导出 JSON、CSV、HTML、Word、Excel 或 PDF
- 支持 Ollama 本地模型

## 环境要求

- 源码运行和构建：Windows 10 或更新版本、64 位 Python 3.10+、Git，以及可联网安装依赖的网络环境。
- AI 在线评分：用户自己的有效 API Key、对应服务商可用的模型和网络连接；API 使用费用由用户承担。
- 使用 Ollama：还需在本机另行安装并启动 Ollama，并准备好本地模型。
- 仅运行已构建的独立 exe：目标电脑为 Windows 10/11 x64 即可，不需要安装 Python；在线 AI 功能仍需要 API Key 和网络。

## 安装与启动

### 方式一：从源码运行

先安装 64 位 Python 3.10 或更高版本，并确保 `py` 命令可用。克隆仓库后，在项目目录打开 PowerShell，首次运行执行：

```powershell
git clone https://github.com/Buyi90/yuejuan.git
cd yuejuan
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

依赖安装完成后，双击项目根目录中的 `启动软件.bat` 即可运行源码；也可以用下面命令直接启动：

```powershell
.\.venv\Scripts\python.exe main.py
```

首次运行会自动创建本机配置目录和默认配置文件。API Key 需要在应用内自行填写。`.venv` 是本机生成的 Python 环境，不包含在 Git 仓库中；新电脑克隆源码后必须先按以上步骤安装 Python 依赖，不能跳过初始化直接双击启动。

### 方式二：构建后分发独立 exe

先按“从源码运行”一节创建 `.venv` 并安装运行依赖，再安装打包依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

然后双击 `构建软件.bat`。构建成功后，将 `dist\AI智阅小助手.exe` 单独发给对方；目标电脑无需安装 Python，也无需安装项目依赖，双击 exe 即可启动。exe 不提交到源码仓库，需通过其他方式发送（例如 GitHub Releases 或网盘）。

在线评分仍要求使用者填入自己的有效 API Key 并保持网络可用；使用 Ollama 的用户需要在目标电脑单独安装并启动 Ollama。Windows 可能会对未签名的程序显示安全提示。

## 开发与测试

运行测试前，在已创建的 `.venv` 中安装测试工具：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest
```

运行代码检查测试：

```powershell
.\.venv\Scripts\python.exe test_code_health.py
```

打包配置保存在 `AI智阅小助手.spec`，路径会根据项目目录及当前 Python 环境自动解析，不绑定某台电脑的用户名或 Python 安装位置。`requirements-build.txt` 单独列出打包依赖。`build/` 和 `dist/` 是本地生成目录，不需要提交到源码仓库。

## 项目结构

```text
.
├── assets/                 # 应用图标和服务商图标
├── data/                   # 本地运行数据，不提交到 Git
├── main.py                 # 应用入口
├── app.py                  # 桌面主窗口与工作流
├── requirements.txt        # Python 运行依赖
├── requirements-build.txt  # PyInstaller 构建依赖
└── AI智阅小助手.spec       # PyInstaller 打包配置
```

测试文件以 `test_*.py` 命名，位于项目根目录。

## 本地数据与隐私

`data/` 中的配置可能含有 API Key，历史记录可能包含学生答案、评分和截图。该目录已加入 `.gitignore`，请勿将其中的内容公开上传。首次运行时应用会按需创建缺失的数据文件。

运行日志、截图、Python 缓存、测试缓存和打包产物也会被 Git 忽略。

## 购买与交付

本软件无需激活码。AI 服务商的 API Key 和调用费用由使用者自行承担。

## 许可证
