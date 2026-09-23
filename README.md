# AI 智阅小助手

面向教师的 Windows 桌面辅助阅卷工具，支持答题区域识别、AI 辅助评分、批量阅卷流程与结果导出。

> AI 评分仅用于辅助初评。正式成绩和重要考试结果请由教师复核。

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

打包配置保存在 `AI智阅小助手.spec`。`build/` 和 `dist/` 是本地生成目录，不需要提交到源码仓库。

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

本软件为直接售卖的软件，购买后可使用完整功能，无需激活码。AI 服务商的 API Key 和调用费用由使用者自行承担。

## 许可证

本仓库当前未声明开源许可证。未经作者明确授权，不应假定代码可按任意开源许可证复制、修改或分发。
