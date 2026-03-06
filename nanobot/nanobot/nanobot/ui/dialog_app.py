# -*- coding: utf-8 -*-
"""
可视化对话框应用：在保留终端对话能力的前提下，新增截图标注、流程图演示、视频链接交互。

与 nanobot 衔接点：
- 使用与 CLI 相同的 load_config()、AgentLoop、process_direct(content, media=...)；
- process_direct 的 media 参数在 nanobot/agent/loop.py 中已扩展，传入本地图片路径列表。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Any

# 可选：流程图在线渲染
try:
    from urllib.request import urlopen, Request
    from urllib.parse import quote
except ImportError:
    urlopen = Request = quote = None  # type: ignore


def _run_async_in_thread(coro):
    """在后台线程运行 asyncio 协程，返回可等待的结果（通过 loop.run_until_complete）。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_nanobot_agent_loop():
    """与 nanobot CLI 一致：加载配置并构建 AgentLoop。"""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop

    config = load_config()
    bus = MessageBus()
    # 使用 CLI 相同的 _make_provider
    from nanobot.cli.commands import _make_provider
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


def _call_agent(content: str, media: list[str] | None, use_history: bool = True) -> str:
    """在后台线程调用 agent.process_direct，供 GUI 使用。use_history=False 时不带历史，每次当新对话。"""
    agent = _get_nanobot_agent_loop()
    return _run_async_in_thread(
        agent.process_direct(
            content,
            session_key="gui:default",
            channel="gui",
            chat_id="default",
            media=media or [],
            use_history=use_history,
        )
    )


# ---------------------------------------------------------------------------
# 截图标注窗口（箭头、矩形、文字、涂鸦）
# ---------------------------------------------------------------------------

class AnnotationWindow:
    """内置标注工具栏：画箭头、矩形、文字、高亮涂鸦；标注后合成图片并保存，供回传对话框。"""

    def __init__(self, parent, image_path: str, on_save):
        self.parent = parent
        self.image_path = image_path
        self.on_save = on_save  # callback(save_path: str)
        self.save_path: str | None = None
        self._shapes = []  # 绘制记录，用于与底图合成
        try:
            from PIL import Image
        except ImportError:
            raise ImportError("请安装 Pillow: pip install Pillow")
        self._PIL_Image = Image

    def run(self):
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox

        win = tk.Toplevel(self.parent)
        win.title("截图标注")
        win.geometry("900x700")
        win.configure(bg="#f0f0f0")

        try:
            from PIL import Image, ImageTk
        except ImportError:
            tk.Label(win, text="请安装 Pillow: pip install Pillow").pack()
            return

        img = Image.open(self.image_path).convert("RGB")
        # 限制显示尺寸，便于操作
        max_w, max_h = 800, 600
        r = min(max_w / img.width, max_h / img.height, 1.0)
        if r < 1:
            img = img.resize((int(img.width * r), int(img.height * r)), Image.Resampling.LANCZOS)
        self._display_img = img
        self._original_size = (img.width, img.height)
        self._scale = r

        # 工具栏
        toolbar = ttk.Frame(win)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        mode_var = tk.StringVar(value="arrow")
        ttk.Radiobutton(toolbar, text="箭头", variable=mode_var, value="arrow").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(toolbar, text="矩形", variable=mode_var, value="rect").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(toolbar, text="文字", variable=mode_var, value="text").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(toolbar, text="涂鸦", variable=mode_var, value="pen").pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(toolbar, text="确认使用", command=lambda: self._save_and_close(win)).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="取消", command=win.destroy).pack(side=tk.LEFT, padx=2)

        # 画布
        self._photo = ImageTk.PhotoImage(self._display_img)
        canvas = tk.Canvas(win, width=self._display_img.width, height=self._display_img.height, bg="gray85")
        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self._canvas = canvas
        self._mode_var = mode_var
        self._start_x = self._start_y = None
        self._current_id = None
        self._text_ids = []
        self._pen_ids = []
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)

        win.transient(self.parent)
        win.grab_set()

    def _on_press(self, ev):
        self._start_x, self._start_y = ev.x, ev.y
        if self._mode_var.get() == "text":
            from tkinter import simpledialog
            s = simpledialog.askstring("文字批注", "输入批注文字:", parent=self._canvas.winfo_toplevel())
            if s:
                id_ = self._canvas.create_text(ev.x, ev.y, text=s, fill="red", font=("Arial", 12, "bold"))
                self._text_ids.append((id_, ev.x, ev.y, s))
        elif self._mode_var.get() == "pen":
            self._current_id = self._canvas.create_line(ev.x, ev.y, ev.x, ev.y, fill="red", width=4, capstyle=tk.ROUND)
            self._pen_ids.append(self._current_id)

    def _on_drag(self, ev):
        if self._mode_var.get() == "pen" and self._current_id is not None:
            coords = list(self._canvas.coords(self._current_id))
            self._canvas.coords(self._current_id, coords[0], coords[1], ev.x, ev.y)
        elif self._start_x is None:
            return
        mode = self._mode_var.get()
        if self._current_id:
            self._canvas.delete(self._current_id)
        if mode == "arrow":
            self._current_id = self._canvas.create_line(
                self._start_x, self._start_y, ev.x, ev.y, fill="red", width=3,
                arrow=tk.LAST, arrowshape=(12, 14, 6)
            )
        elif mode == "rect":
            self._current_id = self._canvas.create_rectangle(
                self._start_x, self._start_y, ev.x, ev.y, outline="red", width=3
            )

    def _on_release(self, ev):
        if self._mode_var.get() in ("arrow", "rect") and self._current_id is not None:
            self._shapes.append((self._mode_var.get(), self._canvas.coords(self._current_id)))
        self._current_id = None
        self._start_x = self._start_y = None

    def _save_and_close(self, win):
        """将画布上的标注与底图合成，保存到临时文件并回调 on_save。"""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            win.destroy()
            return
        base = self._display_img.copy()
        draw = ImageDraw.Draw(base, "RGBA")
        for item in self._canvas.find_all():
            kind = self._canvas.type(item)
            coords = self._canvas.coords(item)
            if kind == "line":
                if len(coords) >= 4:
                    draw.line(coords, fill="red", width=3)
            elif kind == "rectangle":
                if len(coords) >= 4:
                    draw.rectangle(coords, outline="red", width=3)
            elif kind == "text":
                txt = self._canvas.itemcget(item, "text")
                if coords:
                    x, y = int(coords[0]), int(coords[1])
                    draw.text((x, y), txt, fill="red")
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        base.save(path)
        self.save_path = path
        self.on_save(path)
        win.destroy()


# ---------------------------------------------------------------------------
# 主对话框界面
# ---------------------------------------------------------------------------

class DialogApp:
    """可视化主界面：聊天区、输入框、上传/标注、发送；解析回复中的 Mermaid 与视频链接。"""

    def __init__(self, minimal: bool = False):
        self.minimal = minimal  # 极简版：仅截图标注，不解析流程图/视频
        self.root = None
        self._pending_media: list[str] = []  # 当前待发送的图片路径（上传或标注后）
        self._agent_thread = None
        self._after_id = None

    def run(self):
        import tkinter as tk
        from tkinter import ttk, scrolledtext, filedialog, messagebox

        root = tk.Tk()
        root.title("UE 智能教学助手")
        root.geometry("800x620")
        root.minsize(540, 480)
        self.root = root

        # 整体背景与样式（偏现代浅色）
        root.configure(bg="#f1f5f9")
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f1f5f9")
        style.configure("TLabel", background="#f1f5f9", font=("Segoe UI", 10), foreground="#64748b")
        style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 8),
                       background="#2563eb", foreground="white")
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("pressed", "#1e40af")],
                  foreground=[("active", "white")])

        # 顶部：标题与简要说明
        top = ttk.Frame(root, padding=(16, 14))
        top.pack(side=tk.TOP, fill=tk.X)
        title_lbl = tk.Label(top, text="UE 智能教学助手", font=("Segoe UI", 18, "bold"),
                             fg="#1e293b", bg="#f1f5f9")
        title_lbl.pack(side=tk.LEFT)
        sub_lbl = tk.Label(top, text="  文字对话 · 流程图 · 视频链接", font=("Segoe UI", 10),
                           fg="#64748b", bg="#f1f5f9")
        sub_lbl.pack(side=tk.LEFT)
        if self.minimal:
            tk.Label(top, text="  [极简版]", font=("Segoe UI", 9), fg="#94a3b8", bg="#f1f5f9").pack(side=tk.LEFT)

        # 聊天区
        chat_frame = ttk.Frame(root, padding=(12, 8))
        chat_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.chat = scrolledtext.ScrolledText(
            chat_frame, wrap=tk.WORD, font=("Segoe UI", 11), state=tk.DISABLED,
            height=20, padx=14, pady=12,
            bg="#ffffff", fg="#334155", insertbackground="#2563eb",
            selectbackground="#dbeafe", selectforeground="#1e293b",
            relief=tk.FLAT, borderwidth=1, highlightthickness=1, highlightbackground="#e2e8f0"
        )
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.tag_configure("user", foreground="#1e40af", font=("Segoe UI", 11, "bold"))
        self.chat.tag_configure("assistant", foreground="#047857", font=("Segoe UI", 11))
        self.chat.tag_configure("link", foreground="#2563eb", underline=True, font=("Segoe UI", 11))
        self.chat.tag_configure("system", foreground="#64748b", font=("Segoe UI", 10))
        # Markdown 渲染用标签
        self.chat.tag_configure("md_bold", font=("Segoe UI", 11, "bold"), foreground="#0f172a")
        self.chat.tag_configure("md_code", font=("Consolas", 10), background="#e2e8f0", relief=tk.FLAT)
        self.chat.tag_configure("md_code_block", font=("Consolas", 10), background="#f1f5f9", lmargin1=24, lmargin2=24, rmargin=24, spacing1=4, spacing3=4)
        self.chat.tag_configure("md_h1", font=("Segoe UI", 14, "bold"), foreground="#0f172a", spacing1=8, spacing2=2)
        self.chat.tag_configure("md_h2", font=("Segoe UI", 13, "bold"), foreground="#1e293b", spacing1=6, spacing2=2)
        self.chat.tag_configure("md_h3", font=("Segoe UI", 12, "bold"), foreground="#334155", spacing1=4, spacing2=2)
        self.chat.tag_configure("md_quote", font=("Segoe UI", 11), foreground="#475569", lmargin1=24, lmargin2=24, background="#f8fafc")
        self.chat.tag_configure("md_table", font=("Consolas", 10), foreground="#334155")

        # 输入区：输入框 + 发送（保证底部完整显示）
        input_frame = ttk.Frame(root, padding=(12, 10))
        input_frame.pack(side=tk.BOTTOM, fill=tk.X)
        input_frame.pack_propagate(True)
        self.input_var = tk.StringVar()
        self.input_entry = tk.Entry(
            input_frame, textvariable=self.input_var, font=("Segoe UI", 12),
            width=42, relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#e2e8f0",
            highlightcolor="#2563eb", bg="#ffffff", fg="#334155", insertbackground="#2563eb"
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=8, ipadx=10)
        self.input_entry.bind("<Return>", lambda e: self._send())
        ttk.Button(input_frame, text="发送", command=self._send, style="Primary.TButton").pack(side=tk.LEFT, padx=2)

        self._append_system("已就绪。输入问题后点「发送」。")

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.mainloop()

    def _append_system(self, text: str):
        self._append("系统", text, "system")

    def _insert_markdown_text(self, text: str):
        """将 Markdown 解析后插入聊天区，并应用加粗、代码、标题等样式。"""
        import tkinter as tk
        self.chat.config(state=tk.NORMAL)
        # 先按 ``` 拆出代码块
        parts = re.split(r"```", text)
        for i, part in enumerate(parts):
            if i % 2 == 1:
                # 代码块内容：去掉首行语言标识（mermaid、python 等）
                block = part.strip()
                lines = block.split("\n")
                if lines:
                    first = lines[0].strip().lower()
                    if first in ("mermaid", "python", "javascript", "js", "json", "text", "bash", "sh"):
                        block = "\n".join(lines[1:]).strip()
                start = self.chat.index(tk.END)
                self.chat.insert(tk.END, block + "\n", "assistant")
                end = self.chat.index(tk.END)
                self.chat.tag_add("md_code_block", start, end)
                continue
            # 普通段落：按行处理
            for line in part.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    self.chat.insert(tk.END, "\n", "assistant")
                    continue
                if line_stripped.startswith("### "):
                    start = self.chat.index(tk.END)
                    self.chat.insert(tk.END, line_stripped[4:] + "\n", "assistant")
                    end = self.chat.index(tk.END)
                    self.chat.tag_add("md_h3", start, end)
                elif line_stripped.startswith("## "):
                    start = self.chat.index(tk.END)
                    self.chat.insert(tk.END, line_stripped[3:] + "\n", "assistant")
                    end = self.chat.index(tk.END)
                    self.chat.tag_add("md_h2", start, end)
                elif line_stripped.startswith("# "):
                    start = self.chat.index(tk.END)
                    self.chat.insert(tk.END, line_stripped[2:] + "\n", "assistant")
                    end = self.chat.index(tk.END)
                    self.chat.tag_add("md_h1", start, end)
                elif line_stripped.startswith("> "):
                    start = self.chat.index(tk.END)
                    self.chat.insert(tk.END, line_stripped[2:] + "\n", "assistant")
                    end = self.chat.index(tk.END)
                    self.chat.tag_add("md_quote", start, end)
                elif re.match(r"^\s*\|.+\|\s*$", line_stripped):
                    # Markdown 表格行：等宽显示
                    start = self.chat.index(tk.END)
                    self.chat.insert(tk.END, line_stripped + "\n", "assistant")
                    end = self.chat.index(tk.END)
                    self.chat.tag_add("md_table", start, end)
                else:
                    self._insert_markdown_line(line)
        self.chat.insert(tk.END, "\n\n", "assistant")
        self.chat.config(state=tk.DISABLED)

    def _insert_markdown_line(self, line: str):
        """解析单行内的 **粗体**、`代码`、[文字](链接) 并插入。"""
        import tkinter as tk
        # 提取 [text](url) 并记录位置，其余按 ** 和 ` 拆分
        segs = []
        rest = line
        while True:
            m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", rest)
            if not m:
                break
            before = rest[: m.start()]
            segs.append(("text", before))
            segs.append(("link", m.group(1), m.group(2)))
            rest = rest[m.end() :]
        if rest:
            segs.append(("text", rest))
        for item in segs:
            if item[0] == "link":
                _, link_text, link_url = item
                start = self.chat.index(tk.END)
                self.chat.insert(tk.END, link_text, "assistant")
                end = self.chat.index(tk.END)
                tag = f"md_link_{id(link_url)}"
                self.chat.tag_configure(tag, foreground="#2563eb", underline=True, font=("Segoe UI", 11))
                self.chat.tag_add(tag, start, end)
                self.chat.tag_bind(tag, "<Button-1>", lambda e, u=link_url: webbrowser.open(u))
                continue
            # 处理 text 中的 ** 和 `
            self._insert_inline_markdown(item[1])
        self.chat.insert(tk.END, "\n", "assistant")

    def _insert_inline_markdown(self, s: str):
        """插入一段文字，其中 **x** 为粗体，`x` 为行内代码。"""
        import tkinter as tk
        # 按 (\*\*[^*]+\*\*|`[^`]+`) 拆分
        pattern = r"(\*\*[^*]+\*\*|`[^`]+`)"
        parts = re.split(pattern, s)
        for i, p in enumerate(parts):
            if not p:
                continue
            if p.startswith("**") and p.endswith("**"):
                start = self.chat.index(tk.END)
                self.chat.insert(tk.END, p[2:-2], "assistant")
                end = self.chat.index(tk.END)
                self.chat.tag_add("md_bold", start, end)
            elif p.startswith("`") and p.endswith("`"):
                start = self.chat.index(tk.END)
                self.chat.insert(tk.END, p[1:-1], "assistant")
                end = self.chat.index(tk.END)
                self.chat.tag_add("md_code", start, end)
            else:
                self.chat.insert(tk.END, p, "assistant")

    def _append(self, role: str, text: str, tag: str = None):
        import tkinter as tk
        text = text.strip()
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"[{role}]\n", tag or role)
        if role == "助手":
            self._insert_markdown_text(text)
        else:
            self.chat.insert(tk.END, text + "\n\n", tag or role)
        self.chat.config(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _send(self):
        import tkinter as tk
        text = (self.input_var.get() or "").strip()
        if not text and not self._pending_media:
            return
        if not text:
            text = "（请根据我上传的截图/标注说明界面或操作步骤。）"
        self.input_var.set("")
        self._append("我", text, "user")
        if self._pending_media:
            self._append("我", f"[附 {len(self._pending_media)} 张图]", "user")
        self._append_system("正在回复…")
        media = list(self._pending_media)
        self._pending_media = []
        result_holder = [None]

        def run():
            try:
                result_holder[0] = _call_agent(text, media)
            except Exception as e:
                result_holder[0] = f"[错误] {e}"
            self.root.after(0, lambda: self._on_reply(result_holder[0] or ""))

        self._agent_thread = threading.Thread(target=run, daemon=True)
        self._agent_thread.start()

    def _on_reply(self, content: str):
        # 去掉最后一条「正在回复…」
        import tkinter as tk
        self.chat.config(state=tk.NORMAL)
        self.chat.delete("end-3l", "end-1l")
        self.chat.config(state=tk.DISABLED)
        self._append("助手", content, "assistant")
        if not self.minimal:
            self._render_mermaid_and_video(content)

    def _render_mermaid_and_video(self, content: str):
        """解析回复中的 ```mermaid：生成流程图链接并在浏览器中打开网页式展示（不追加正文中的裸链接）。"""
        import tkinter as tk
        m = re.search(r"```mermaid\s*\n(.*?)```", content, re.DOTALL)
        if m:
            code = m.group(1).strip()
            url = self._mermaid_to_image_url(code)
            if url:
                self._append_system("[流程图] 已生成，可在浏览器中查看；点击下方链接可获取图片地址。")
                self._append_link_clickable(url)
                # 在浏览器中打开 Mermaid 网页式展示（分页、可缩放，对标思维导图体验）
                self._open_mermaid_in_browser(code)
                # 可选：后台拉图弹窗（保留原有弹窗作为备选）
                def fetch_and_show():
                    try:
                        from urllib.request import urlopen, Request
                        req = Request(url, headers={"User-Agent": "nanobot-dialog/1.0"})
                        data = urlopen(req, timeout=12).read()
                        self.root.after(0, lambda: self._show_flowchart_demo(url, code, data))
                    except Exception:
                        pass
                threading.Thread(target=fetch_and_show, daemon=True).start()
            else:
                self._append_system("[流程图] 无法生成图片链接，可在浏览器中打开上方 Mermaid 页面，或复制代码到 https://mermaid.live 查看。")
        # 链接仅以 [标题](url) 形式在正文中展示，不再在文末追加裸链接

    def _show_flowchart_demo(self, image_url: str, code: str, image_data: bytes):
        """在弹窗中演示流程图图片。"""
        import tkinter as tk
        from tkinter import ttk
        try:
            from PIL import Image, ImageTk
            import io
        except ImportError:
            self._show_flowchart_fallback(image_url, code)
            return
        try:
            img = Image.open(io.BytesIO(image_data)).convert("RGB")
        except Exception:
            self._show_flowchart_fallback(image_url, code)
            return
        # 限制弹窗内显示尺寸
        max_w, max_h = 820, 520
        r = min(max_w / img.width, max_h / img.height, 1.0)
        if r < 1:
            img = img.resize((int(img.width * r), int(img.height * r)), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        win = tk.Toplevel(self.root)
        win.title("流程图演示")
        win.geometry(f"{img.width + 24}x{img.height + 80}")
        win.configure(bg="#f5f5f5")
        f = ttk.Frame(win, padding=8)
        f.pack(fill=tk.BOTH, expand=True)
        lbl = tk.Label(f, image=photo, bg="white", relief=tk.SOLID, borderwidth=1)
        lbl.image = photo
        lbl.pack(side=tk.TOP, pady=(0, 8))
        btn_frame = ttk.Frame(f)
        btn_frame.pack(side=tk.TOP)
        ttk.Button(btn_frame, text="在浏览器中打开", command=lambda: webbrowser.open(image_url)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="在 Mermaid Live 中编辑", command=lambda: webbrowser.open("https://mermaid.live")).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="关闭", command=win.destroy).pack(side=tk.LEFT, padx=4)
        self._append_system("[流程图] 已在上方弹窗中演示；可点击「在浏览器中打开」查看大图。")

    def _show_flowchart_fallback(self, image_url: str, code: str):
        """弹窗失败时提示点击上方链接（链接已在解析时追加）。"""
        self._append_system("[流程图] 弹窗加载未成功，请点击上方流程图链接在浏览器中查看。")

    def _append_link_clickable(self, url: str):
        """在聊天区追加可点击链接，点击后用系统浏览器打开。"""
        import tkinter as tk
        self.chat.config(state=tk.NORMAL)
        start = self.chat.index(tk.END)
        self.chat.insert(tk.END, f"🔗 {url}\n", "link")
        end = self.chat.index(tk.END)
        self.chat.config(state=tk.DISABLED)
        tag = f"link_{id(url)}"
        self.chat.tag_add(tag, start, end)
        self.chat.tag_config(tag, foreground="blue", underline=True)
        self.chat.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))

    def _mermaid_to_image_url(self, code: str) -> str | None:
        """通过 mermaid.ink 将 Mermaid 代码转为图片 URL（不请求校验，避免网络失败时无链接）。"""
        try:
            from base64 import b64encode
            payload = b64encode(code.encode("utf-8")).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")
            return f"https://mermaid.ink/img/{payload}"
        except Exception:
            return None

    def _open_mermaid_in_browser(self, code: str) -> None:
        """生成带 Mermaid.js 的 HTML 并在浏览器中打开，实现网页分页式、可缩放流程图展示。"""
        try:
            code_escaped = code.replace("</script>", "<\\/script>")
            html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>流程图 - UE 智能教学助手</title>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
  </script>
  <style>
    body {{ font-family: "Segoe UI", sans-serif; margin: 16px; background: #f8fafc; }}
    h1 {{ font-size: 1.1rem; color: #334155; }}
    .mermaid {{ background: #fff; padding: 16px; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>流程图</h1>
  <pre class="mermaid">{code_escaped}</pre>
</body>
</html>"""
            fd, path = tempfile.mkstemp(suffix=".html", prefix="nanobot_mermaid_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(html)
            webbrowser.open(Path(path).as_uri())
        except Exception:
            pass

    def _on_close(self):
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self.root.destroy()


def run_dialog(minimal: bool = False):
    """启动可视化对话框。minimal=True 时仅保留截图标注，不解析流程图与视频。"""
    app = DialogApp(minimal=minimal)
    app.run()


if __name__ == "__main__":
    import sys
    run_dialog(minimal="--minimal" in sys.argv)
