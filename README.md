# UEGuide: 职教虚幻引擎（UE）智能教学答疑助手

<p align="center">
  <img src="assets/ueguide-logo.png" alt="UEGuide Logo" width="280">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://github.com/HKUDS/nanobot"><img src="https://img.shields.io/badge/Framework-Nanobot-orange" alt="Framework"></a>
  <img src="https://img.shields.io/badge/Field-Vocational_Education-green" alt="Field">
</p>

## 项目摘要

本项目聚焦职业院校虚幻引擎（UE）课程中**「课后答疑难、学习资源散、师资辅导少」**的核心痛点，创新研发了 **UEGuide** 智能教学答疑助手。项目依托轻量级开源 AI 助手框架 **Nanobot**，打破传统 AI 答疑「无据可依、脱离课程」的局限，构建**「教案为本、官方为据」**的垂直服务模式。

UEGuide 针对 UE 课程深度定制：自动识别专业问题并实时加载本地校本教案与 Epic Games 官方权威资源，通过**上下文注入技术**生成贴合课程进度、符合官方标准的精准应答，为用户提供 **24 小时全天候**精准可信的个性化辅导。面向群体广泛，包含职业院校师生乃至个人开发者，应用场景涵盖**学习资源推荐、答疑辅导、就业指导**等多领域。

系统支持 **OpenRouter、DeepSeek、通义、vLLM** 等多模型适配，兼容**命令行、飞书**等多通道使用，具备部署成本极低、自主可控性强、可快速复用至其他职业技能课程等优势，积极响应国家职业教育数字化改革政策，兼具深远的社会价值与市场潜力。

---

## 核心痛点与对策

| 现状 | UEGuide 对策 |
|------|----------------|
| 全国超 1200 所职业院校面临约 31 万专业教师缺口；通用大模型易脱离教学实际、存在幻觉 | 通过**上下文注入**实时加载本地校本教案与 Epic Games 官方资源，回答贴合课程与官方文档 |
| 资源分散、答疑不及时；自学群体规模超 50 万、易因资源杂乱产生挫败感 | 关键词触发预加载（教案索引 + 课时正文 + Tavily/官方页），一次提问即可获得结构化答复与系统化学习路径引导 |

---

## 核心特性

- **精准垂直**：识别 UE/教案相关提问，自动注入教案与 Epic 官方内容，回答有据可依。
- **多模型适配**：支持 DeepSeek、MiniMax、通义千问、OpenRouter、vLLM 等，可配置切换。
- **多端覆盖**：命令行（CLI）、Web 界面、飞书/钉钉/Telegram 机器人，同一套配置与教案。
- **极简部署**：基于 Nanobot 轻量框架，部署成本低，可复用至其他职业技能课程。

---

## 快速上手（Windows）

### 1. 环境准备

- 已安装 **Python 3.11+**
- 克隆本仓库并进入项目目录：

```bash
git clonehttps://github.com/Carrie-Ww/UEGuide.git
cd UEGuide
```

### 2. 安装 Nanobot 核心

从项目内的 `nanobot` 目录以开发模式安装（含 UEGuide 定制逻辑）：

```bash
cd nanobot
pip install -e .
```

如需 **Web 对话界面**：

```bash
pip install -e ".[web]"
```

### 3. 创建配置文件

- **路径**：`C:\Users\你的用户名\.nanobot\config.json`  
- 该文件夹默认可能隐藏，请在资源管理器中：**查看 → 显示 → 隐藏的项目**。

将以下内容写入 `config.json`，并按实际情况修改 **模型名**、**API Key** 和 **workspace 绝对路径**：

```json
{
  "agents": {
    "defaults": {
      "model": "deepseek-chat",
      "workspace": "C:/你的存放路径/UEGuide/workspace"
    }
  },
  "providers": {
    "deepseek": {
      "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxx",
      "api_base": "https://api.deepseek.com"
    }
  }
}
```

> **说明**：`workspace` 需指向**本项目内**包含 UE 教案的目录（即仓库下的 `workspace` 文件夹）。  
> 使用其他模型时，在 `agents.defaults.model` 中填写对应模型名（如 `anthropic/claude-3-5-sonnet`），并在 `providers` 中配置相应 `api_key` / `api_base`。

### 4. 启动运行

| 方式 | 命令 | 说明 |
|------|------|------|
| **Web 界面**（推荐） | `nanobot web` | 浏览器打开本地对话页 |
| **命令行交互** | `nanobot agent` | 持续对话，输入 `exit` 或 Ctrl+C 退出 |
| **单次提问** | `nanobot agent -m "如何在 UE5 中优化 Nanite 显存占用？" --logs` | 单条消息并查看日志 |
| **多通道（飞书/钉钉等）** | `nanobot gateway` | 需在 config 的 `channels` 中启用对应机器人 |

---

## 项目结构

```
UEGuide/
├── nanobot/                    # Nanobot 框架 + UEGuide 定制（Agent 循环、UE 预加载、多通道）
│   ├── agent/                  # 核心 Agent（loop.py 含 UE 关键词与教案预加载）
│   ├── channels/               # 飞书、钉钉、Telegram 等
│   ├── config/                 # 配置 schema 与加载
│   ├── session/                # 会话留存（~/.nanobot/sessions/*.jsonl）
│   └── ui/                     # Web、Dialog 界面
├── workspace/                  # 工作区（需在 config 中指向此处）
│   ├── curriculum/
│   │   ├── index.json          # 课程索引（lessons[]、keywords、file_path）
│   │   └── lessons/*.md        # 课时正文（如 64 课时 VR 课程、10 课时职院教案）
│   └── knowledge/              # 可选：ue-videos.md 等推荐资源
├── scripts/                    # 如 run_ueguide_test.py 批量测试
└── README.md
```

---

## 社会价值与前景

UEGuide 精准对接多方刚需，积极响应国家职业教育数字化改革政策：

- **赋能院校**：为全国超 1200 所面临师资缺口的职业院校提供低成本、易部署的数字化转型方案，助力缓解约 31 万教师缺口压力。
- **提升效率**：显著提升培训机构的教学效率，满足日益增长的在职技能提升与即时答疑需求。
- **助力自学**：针对规模超 50 万、因资源杂乱而易产生挫败感的自学群体，提供系统化的学习路径引导与贴合课程与官方文档的问答支持。

项目致力于为国家高技能人才培养体系贡献智慧力量，兼具深远的社会价值与巨大的市场潜力。

---

## 开源协议

本项目基于 **MIT License** 开源。

若 UEGuide 对您的教学或学习有帮助，欢迎在 GitHub 点 ⭐ **Star**。
