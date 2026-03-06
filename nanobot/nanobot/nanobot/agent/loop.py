"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager

# Epic 官方学习页，用于 UE 问答硬性注入
EPIC_LEARNING_URL = "https://dev.epicgames.com/community/unreal-engine/learning"
# UE/教案相关关键词，命中则先 read_file 教案 + web_fetch 官方页再回答
_UE_KEYWORDS = (
    "课", "教案", "虚幻", "UE", "引擎", "第一课", "安装", "蓝图", "内容浏览器",
    "关卡", "材质", "地形", "打包", "职业技术学院", "职高", "Unreal", "curriculum",
    "lumen", "PIE", "SIE", "视口", "大纲", "细节面板",
)


def _is_ue_related(content: str) -> bool:
    """判断用户消息是否与 UE/教案相关，相关则触发硬性预加载。"""
    if not content or not content.strip():
        return False
    lower = content.strip().lower()
    return any(kw in lower or kw in content for kw in _UE_KEYWORDS)


def _contains_cjk(text: str) -> bool:
    """判断文本是否包含中日韩字符（用于 DeepSeek 时把中文包装成英文请求）。"""
    if not text:
        return False
    for c in text:
        if "\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff" or "\uac00" <= c <= "\ud7af":
            return True
    return False


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        brave_api_key: str | None = None,
        tavily_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.brave_api_key = brave_api_key
        self.tavily_api_key = tavily_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        
        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            brave_api_key=brave_api_key,
            tavily_api_key=tavily_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        
        self._running = False
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))
        
        # Web tools
        self.tools.register(WebSearchTool(
            api_key=self.brave_api_key,
            tavily_api_key=self.tavily_api_key,
        ))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        
        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _preload_ue_resources(self) -> str | None:
        """
        硬性先读教案再拉取官方页，用于 UE 问答。返回注入到 system 的字符串，失败返回 None。
        """
        parts = []
        max_chars_per_section = 22000
        total_cap = 45000

        # 1) read_file 教案索引
        index_path = self.workspace / "curriculum" / "index.json"
        if not index_path.exists():
            logger.debug("UE preload: curriculum/index.json not found")
            return None
        try:
            index_content = index_path.read_text(encoding="utf-8")
            if len(index_content) > max_chars_per_section:
                index_content = index_content[:max_chars_per_section] + "\n...(已截断)"
            parts.append("## 已加载的教案索引（回答时必须优先依据）\n\n### curriculum/index.json\n```json\n" + index_content + "\n```")
        except Exception as e:
            logger.debug(f"UE preload: read index failed: {e}")
            return None

        # 2) read_file 第一份教案正文（从 index 取 file_path）
        lesson_content = ""
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
            lessons = index_data.get("lessons") or []
            if lessons:
                first_path = lessons[0].get("file_path", "")
                if first_path:
                    lesson_path = self.workspace / "curriculum" / first_path
                    if lesson_path.exists():
                        lesson_content = lesson_path.read_text(encoding="utf-8")
                        if len(lesson_content) > max_chars_per_section:
                            lesson_content = lesson_content[:max_chars_per_section] + "\n...(已截断)"
        except Exception as e:
            logger.debug(f"UE preload: read lesson failed: {e}")

        if lesson_content:
            parts.append("\n\n### 教案正文（第一份）\n\n" + lesson_content)

        # 2.5) 推荐视频列表（可选，用于回答时推荐视频）
        videos_path = self.workspace / "knowledge" / "ue-videos.md"
        if videos_path.exists():
            try:
                videos_content = videos_path.read_text(encoding="utf-8")
                if videos_content.strip():
                    if len(videos_content) > 8000:
                        videos_content = videos_content[:8000] + "\n...(已截断)"
                    parts.append("\n\n### 推荐视频（回答时可选用并给出链接）\n\n" + videos_content)
            except Exception as e:
                logger.debug(f"UE preload: read ue-videos.md failed: {e}")

        # 3) Epic 官方学习内容：优先用 Tavily 联网搜索，无 Tavily 时回退到 web_fetch 固定 URL
        epic_block = ""
        if self.tavily_api_key:
            try:
                search_result = await self.tools.execute(
                    "web_search",
                    {
                        "query": "Epic Games Unreal Engine official learning documentation tutorial 2025",
                        "count": 8,
                    },
                )
                if search_result and "Error:" not in search_result:
                    if len(search_result) > max_chars_per_section:
                        search_result = search_result[:max_chars_per_section] + "\n...(已截断)"
                    epic_block = "\n\n### Epic 官方学习（Tavily 联网检索）\n\n" + search_result
                    logger.debug("UE preload: using Tavily search for Epic learning content")
            except Exception as e:
                logger.debug(f"UE preload: Tavily search failed: {e}")
        if not epic_block:
            try:
                fetch_result = await self.tools.execute(
                    "web_fetch",
                    {"url": EPIC_LEARNING_URL, "extractMode": "markdown"},
                )
                fetch_str = (fetch_result or "").strip()
                if fetch_str:
                    try:
                        data = json.loads(fetch_str)
                        if "error" not in data:
                            text = data.get("text", "") or ""
                            if len(text) > max_chars_per_section:
                                text = text[:max_chars_per_section] + "\n...(已截断)"
                            epic_block = "\n\n### Epic 官方学习页（补充参考）\n\n" + text
                    except json.JSONDecodeError:
                        if len(fetch_str) > max_chars_per_section:
                            fetch_str = fetch_str[:max_chars_per_section] + "\n...(已截断)"
                        epic_block = "\n\n### Epic 官方学习页（补充参考）\n\n" + fetch_str
            except Exception as e:
                logger.debug(f"UE preload: web_fetch failed: {e}")
        if epic_block:
            parts.append(epic_block)

        if not parts:
            return None
        block = "\n".join(parts)
        if len(block) > total_cap:
            block = block[:total_cap] + "\n...(已截断)"
        header = """**你正在帮助一位学习虚幻引擎（UE）的学生。** 回答须严格依据下方已加载的教案与网络资源。

**【严禁】** 回答中**禁止出现**任何“已经回答过 / 之前说过 / 详细解释过”之类的表述。每次提问都当作**第一次问**，直接给完整答案，不提及对话历史里是否答过。

---

**一、整体风格**
- 语言专业、清晰、自然，兼具技术准确性与阅读舒适度。
- 技术准确、格式规范，表达自然不刻板；优先保证实用性，再兼顾视觉美观。

**二、格式与 Markdown 渲染**
- 所有内容**严格遵循标准 Markdown 语法**，确保在对话框中能 100% 正常渲染。
- 必须完整正确使用：标题层级（# / ## / ###）、有序列表（1. 2. 3.）、无序列表（- 或 *）、**粗体**、*斜体*、代码块（```）、行内代码（`）、表格（| 列 | 列 |）、引用块（> ）。
- **禁止**使用全角空格、易干扰解析的特殊分隔符；段落之间可用 --- 分隔，小标题用 ## 或 ###。

**三、链接展示（必须遵守）**
- **所有链接只显示标题，不暴露原始 URL。**
- 统一格式：**[内容标题](链接地址)**，标题简洁概括内容（如 [官方蓝图文档](https://...)）。
- **禁止直接粘贴裸链接**；所有链接必须写成 [有意义的标题](url)，不得单独一行写 https://...。

**四、流程图 / 思维导图**
- 在需要说明步骤、流程时，用 **Mermaid** 语法画出流程图或思维导图，便于在浏览器中分页式、可折叠展开地展示。
- 要求：节点 5～8 步为宜，用 flowchart TD 线性或分支；**节点内不要使用竖线 |、双引号 "、换行**，可用「和」「或」代替；不用 style、过多分支。在回复中给出 ```mermaid ... ``` 代码块。

**五、其他回答要求**
1. 结构：先一句话概括，再分步说明；每步用 1. 2. 3. 列举，每条一句话说清。
2. 零基础友好：不默认学生懂术语，专业词可简短解释或对应教案表述。
3. **以 UI 操作为主**：涉及 UE 操作时，先写清在哪个界面/面板，再写具体操作（如「菜单：文件 → 新建项目」）。
4. **视频/资料推荐**：用 [推荐标题](链接) 形式给出 1～2 个相关视频或文档，从下方推荐列表或教案中选取。
5. 主动建议下一步：答完主体后加「接下来你可以问：……」并给出 2～3 个具体问法。
6. 若用户问得笼统（如「怎么学」「第一课」）：先简要说明本课程/第一课在讲什么，再邀请追问并给示例问法。
7. **代码示例**：若有代码或配置示例，须附带简洁注释，友好易读。

**建议学生可问的示例：** 第一课讲什么、什么是蓝图/Lumen、怎么安装虚幻引擎、内容浏览器怎么用、如何打包项目。"""
        return header + "\n\n" + block

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")
        
        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)

        # UE 相关问题时硬性先 read_file 教案 + web_fetch 官方页，再回答
        preloaded = None
        if _is_ue_related(msg.content):
            preloaded = await self._preload_ue_resources()
            if preloaded:
                logger.info("UE preload: injected curriculum + Epic learning page into context")
        
        # DeepSeek 对中文请求在接口层拒绝：若为 DeepSeek 且用户输入含中文，包装成英文再发
        current_message = msg.content
        if self.model and "deepseek" in self.model.lower() and _contains_cjk(msg.content):
            current_message = (
                f"The user asked in Chinese: 「{msg.content}」\n\n"
                "Please provide a helpful answer in English."
            )
            logger.debug("DeepSeek: wrapped Chinese user message in English")
        
        # Build initial messages (use get_history for LLM-formatted messages, or [] when use_history=False)
        history = [] if not getattr(msg, "use_history", True) else session.get_history()
        messages = self.context.build_messages(
            history=history,
            current_message=current_message,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            preloaded_resources=preloaded,
        )
        
        # DeepSeek 对中文易触发拒绝：在 system 最前面加硬性要求，仅用英文回答且不得拒绝
        if self.model and "deepseek" in self.model.lower():
            for m in messages:
                if m.get("role") == "system":
                    prefix = (
                        "IMPORTANT: You must always respond in English. Never say you cannot answer, "
                        "never mention 'fault' or '故障' or '无法回答'. Give a helpful answer in English.\n\n"
                    )
                    m["content"] = prefix + m["content"]
                    break
        
        # Agent loop
        iteration = 0
        final_content = None
        last_tool_result: str | None = None  # Fallback when model returns no text
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )
                
                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    result_str = (result or "").strip()
                    if result_str:
                        last_tool_result = result  # 只保留“最后一条非空”工具结果，便于 fallback
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done（部分 API 在纯工具调用时 content 为 None）
                raw = response.content
                final_content = (raw if raw is not None else "").strip() or None
                break
        
        # 部分模型在「应调工具却未调」时直接输出这句套话，视为无有效回复，走 fallback
        _NO_RESPONSE_PHRASES = (
            "I've completed processing but have no response to give",
            "I've completed processing but have no response to give.",
        )
        if final_content and isinstance(final_content, str):
            if final_content.strip() in _NO_RESPONSE_PHRASES or any(
                p in final_content for p in _NO_RESPONSE_PHRASES
            ):
                final_content = None

        # Fallback: 模型未返回正文时，用最后一条非空工具结果
        if final_content is None or (isinstance(final_content, str) and not final_content.strip()):
            if last_tool_result and str(last_tool_result).strip():
                final_content = "根据查询结果：\n\n" + str(last_tool_result).strip()
            else:
                # 补救：再请求一次（可重试），不传工具，强制模型用一句话回答（应对 API 不稳定或模型只返回 tool call）
                final_content = None
                follow_up_msg = "请根据上述对话，用一两句话直接回答用户的问题，不要调用任何工具。若无法回答请简要说明原因。"
                for attempt in range(2):
                    try:
                        follow_up = messages + [{"role": "user", "content": follow_up_msg}]
                        resp = await self.provider.chat(
                            messages=follow_up, tools=[], model=self.model,
                            max_tokens=self.max_tokens, temperature=self.temperature,
                        )
                        if resp and getattr(resp, "content", None) and str(resp.content).strip():
                            final_content = str(resp.content).strip()
                            break
                    except Exception as e:
                        logger.debug(f"Fallback follow-up call failed (attempt {attempt + 1}): {e}")
                    if attempt < 1:
                        await asyncio.sleep(1)
                if not final_content or not str(final_content).strip():
                    final_content = (
                        "已处理完成，但模型未返回最终回复。\n\n"
                        "常见原因：**API 不稳定**（超时/限流）或模型只执行了工具调用没有返回文字。建议：\n"
                        "• 稍后**重试**或**换一种问法**（例如：「虚幻引擎怎么安装？」「第一课讲了什么？」）。\n"
                        "• 若问的是 UE 课程/教案，请确认 `~/.nanobot/config.json` 里 `agents.defaults.workspace` 指向项目下的 workspace 目录。\n\n"
                        "也可尝试更换模型（如 deepseek-chat / openrouter 其他模型）后再试。"
                    )
        
        # Log response preview
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"Response to {msg.channel}:{msg.sender_id}: {preview}")
        
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        media: list[str] | None = None,
        use_history: bool = True,
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).
            media: Optional list of local file paths (e.g. annotated screenshot) for image context.
            use_history: If False, the model sees only the current message (no prior conversation).
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content,
            media=media or [],
            use_history=use_history,
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
