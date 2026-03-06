# -*- coding: utf-8 -*-
"""
UEGuide 测试脚本：用 20 道实操题依次向 UEGuide（nanobot + 教案）提问，
收集回答并保存为 Markdown，含题目与考核点说明。

使用前请确保：
1. 已配置 ~/.nanobot/config.json（或 Windows 下 C:\\Users\\<用户名>\\.nanobot\\config.json）
2. agents.defaults.workspace 指向本项目 workspace 的绝对路径（含 curriculum）
3. 模型 API 已配置并可调用

运行（在项目根目录 d:\\111science\\2026\\nanobot 下）：
  python scripts/run_ueguide_test.py

指定输出文件：
  python scripts/run_ueguide_test.py -o UEGuide测试结果.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 确保可导入 nanobot 包
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_NANOBOT_PKG_ROOT = _REPO_ROOT / "nanobot"
if _NANOBOT_PKG_ROOT.exists() and str(_NANOBOT_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_NANOBOT_PKG_ROOT))

# 20 道测试题：(模块名, 题目, 考核点)
UEGUIDE_TEST_QUESTIONS = [
    # 一、基础与上手 (操作直觉)
    (
        "一、基础与上手 (操作直觉)",
        "我的视口里找不到刚才放进去的模型了，怎么办？",
        "考察对快捷键 F (Focus) 的引导，以及大纲视图 (Outliner) 的使用。",
    ),
    (
        "一、基础与上手 (操作直觉)",
        "为什么我修改了材质的颜色，场景里所有同类模型都变色了？",
        "考察对材质实例 (Material Instance) 这一核心工作流的理解。",
    ),
    # 二、资源管理 (规范与效率)
    (
        "二、资源管理 (规范与效率)",
        "内容浏览器里东西太多了，怎么快速找到所有的静态网格体（Static Mesh）？",
        "考察对过滤器 (Filters) 的使用，而非简单的搜索文件名。",
    ),
    (
        "二、资源管理 (规范与效率)",
        "我想把项目里的一个小木屋导给同学用，怎么操作最稳妥？",
        "考察迁移 (Migrate) 功能，而非直接在文件夹里拷贝 .uasset。",
    ),
    # 三、蓝图逻辑 (实战避坑)
    (
        "三、蓝图逻辑 (实战避坑)",
        "我想做‘靠近门自动开启’，应该用什么组件监测玩家？",
        "碰撞盒 (Box Collision) 的应用及其事件触发逻辑。",
    ),
    (
        "三、蓝图逻辑 (实战避坑)",
        "蓝图里 Delay 和 Tick 有什么区别？为什么不建议在 Tick 里写复杂逻辑？",
        "对性能优化和帧率相关性的基础认知。",
    ),
    (
        "三、蓝图逻辑 (实战避坑)",
        "我有两个蓝图，怎么让 A 告诉 B 播放一个动画？",
        "考察蓝图通信 (Communication) 的基本方式（直接引用 vs 接口）。",
    ),
    (
        "三、蓝图逻辑 (实战避坑)",
        "变量里的‘可编辑 (Instance Editable)’小眼睛打开有什么用？",
        "考察对细节面板属性调节的实战理解。",
    ),
    # 四、VR 开发 (专项痛点)
    (
        "四、VR 开发 (专项痛点)",
        "戴上 VR 头显后发现视角在地下，或者高度不对，怎么重置？",
        "Reset VR Origin 或 Pawn 高度设置。",
    ),
    (
        "四、VR 开发 (专项痛点)",
        "我想实现‘瞬移’移动，虚幻引擎自带的模板里是怎么做射线检测的？",
        "对 Navigation Mesh (导航网格) 的依赖关系。",
    ),
    (
        "四、VR 开发 (专项痛点)",
        "为什么我在 VR 里看到的画面很模糊，还有重影？",
        "VR 性能优化（如取消动态模糊、调整渲染分辨率）。",
    ),
    (
        "四、VR 开发 (专项痛点)",
        "手柄按键没反应，我应该去哪里检查输入设置？",
        "增强输入系统 (Enhanced Input) 的排查路径。",
    ),
    # 五、场景与表现 (视觉基础)
    (
        "五、场景与表现 (视觉基础)",
        "为什么我放了灯光，场景里还是黑漆漆的或者提示‘需要重新构建灯光’？",
        "静态光与掉帧的关系，以及 Lumen (动态光照) 的基础开启。",
    ),
    (
        "五、场景与表现 (视觉基础)",
        "怎么让远处的大山看起来不那么‘假’，而且不卡顿？",
        "LOD (细节层次) 的基本概念。",
    ),
    (
        "五、场景与表现 (视觉基础)",
        "材质里的‘金属感 (Metallic)’和‘粗糙度 (Roughness)’怎么配合才能做出镜面效果？",
        "PBR 材质基础数值逻辑。",
    ),
    (
        "五、场景与表现 (视觉基础)",
        "我想在场景里加一点雾气，让氛围感更好，用哪个组件？",
        "指数级高度雾 (Exponential Height Fog)。",
    ),
    # 六、综合与发布 (成果转化)
    (
        "六、综合与发布 (成果转化)",
        "打包（Package）的时候报错找不到 SDK，通常是什么原因？",
        "运行环境配置与 Visual Studio 组件的关联。",
    ),
    (
        "六、综合与发布 (成果转化)",
        "我想让游戏开始时有一个全屏的 UI 菜单，怎么实现？",
        "控件蓝图 (Widget Blueprint) 的创建与 Add to Viewport。",
    ),
    (
        "六、综合与发布 (成果转化)",
        "Player Start 放在地面以下会发生什么？",
        "物理碰撞冲突导致的“出生即掉落/卡死”排查。",
    ),
    (
        "六、综合与发布 (成果转化)",
        "我的 VR 项目打包后在一体机上跑不动，最先应该优化哪里？",
        "面数控制、Draw Call 概念或纹理尺寸。",
    ),
]


def _get_agent_loop():
    """与 nanobot CLI 一致：加载配置并构建 AgentLoop（UEGuide）。"""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    from nanobot.cli.commands import _make_provider

    try:
        from loguru import logger
        logger.disable("nanobot")
    except Exception:
        pass

    config = load_config()
    bus = MessageBus()
    provider = _make_provider(config)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        max_tokens=config.agents.defaults.max_tokens,
        temperature=config.agents.defaults.temperature,
        brave_api_key=config.tools.web.search.api_key or None,
        tavily_api_key=config.tools.web.search.tavily_api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
    )
    return agent


async def run_test(output_path: Path, use_history: bool = False) -> None:
    """逐题调用 UEGuide，将题目、考核点与回答写入 output_path。"""
    agent = _get_agent_loop()
    lines = [
        "# UEGuide 测试结果",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]
    current_section = None
    for i, (section, question, checkpoint) in enumerate(UEGUIDE_TEST_QUESTIONS, start=1):
        if section != current_section:
            current_section = section
            lines.append(f"## {current_section}\n")
        lines.append(f"### 第 {i} 题\n")
        lines.append(f"**题目**：{question}\n")
        lines.append(f"**考核点**：{checkpoint}\n")
        print(f"[{i}/20] {section}：{question[:40]}...")
        try:
            response = await agent.process_direct(
                question,
                session_key="script:ueguide_test",
                channel="cli",
                chat_id="direct",
                use_history=use_history,
            )
            answer = (response or "").strip()
            lines.append("**UEGuide 回答**：\n\n")
            lines.append(answer)
            lines.append("\n\n")
        except Exception as e:
            answer = ""
            lines.append("**UEGuide 回答**：\n\n")
            lines.append(f"（请求出错：{e}）\n\n")
        print(f"  已获取回答，共 {len(answer)} 字。")
    content = "".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"\n结果已保存到：{output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="UEGuide 20 题测试并保存回答结果")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="输出文件路径（默认：项目根目录下 UEGuide测试结果_YYYYMMDD_HHMM.md）",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="是否使用会话历史（默认每题独立上下文）",
    )
    args = parser.parse_args()
    if args.output is not None:
        out = Path(args.output)
    else:
        out = _REPO_ROOT / f"UEGuide测试结果_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    asyncio.run(run_test(out, use_history=args.history))


if __name__ == "__main__":
    main()
