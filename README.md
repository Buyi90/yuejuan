# AI 智阅小助手

面向教师的 Windows 桌面辅助阅卷工具，支持答题区域识别、AI 辅助评分、批量阅卷流程与结果导出。

## 功能

- 配置识别框、打分框和提交框，辅助网页阅卷操作
- 通过 OpenAI 兼容接口调用 AI 服务进行识别和评分
- 支持单评、双评与分歧仲裁工作流
- 保存配置方案与阅卷历史，并导出 JSON、CSV、HTML、Word、Excel 或 PDF
- 支持 Ollama 本地模型

## 环境要求

- Windows 10 或更新版本
- Python 3.10+
- 可用的 AI 服务 API Key；使用 Ollama 时需安装并启动 Ollama

## 安装与启动

### 构建可分发版本

首次构建时安装打包依赖：python -m pip install -r requirements-build.txt，然后双击“构建软件.bat”。构建完成后，将 dist/AI智阅小助手.exe 复制到目标 Windows 10/11 x64 电脑并双击运行；目标电脑不需要安装 Python。程序首次运行会在用户的 Roaming 应用数据目录创建配置和历史文件。AI 在线评分仍需使用者配置自己的 API Key；使用 Ollama 时目标电脑需单独安装并启动 Ollama。Windows 可能对未签名的自制程序显示安全提示。

在项目目录打开 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

也可以在已配置好 Python 环境的 Windows 电脑上双击 `启动软件.bat`。

## 开发与测试

运行测试：

```powershell
python -m pytest
```

运行代码检查测试：

```powershell
python test_code_health.py
```

打包配置保存在 AI智阅小助手.spec，路径会根据项目目录及当前 Python 环境自动解析，不绑定某台电脑的用户名或 Python 安装位置。requirements-build.txt 单独列出打包依赖。build/ 和 dist/ 是本地生成目录，不需要提交到源码仓库。

## 项目结构

```text
.
├── assets/                 # 应用图标和服务商图标
├── data/                   # 本地运行数据，不提交到 Git
├── main.py                 # 应用入口
├── app.py                  # 桌面主窗口与工作流
├── requirements.txt        # Python 依赖
└── AI智阅小助手.spec       # PyInstaller 打包配置
```

测试文件以 `test_*.py` 命名，位于项目根目录。

## 本地数据与隐私

`data/` 中的配置可能含有 API Key，历史记录可能包含学生答案、评分和截图。该目录已加入 `.gitignore`，请勿将其中的内容公开上传。首次运行时应用会按需创建缺失的数据文件。

运行日志、截图、Python 缓存、测试缓存和打包产物也会被 Git 忽略。

## 购买与交付

本软件无需激活码。AI 服务商的 API Key 和调用费用由使用者自行承担。

## 许可证
