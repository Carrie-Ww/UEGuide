# -*- coding: utf-8 -*-
"""
浏览器版对话界面：提供 Web 服务与单页前端，在浏览器中与 UE 智能教学助手对话。
"""

from __future__ import annotations

import webbrowser
from pathlib import Path


def _call_agent(content: str, media: list[str] | None = None) -> str:
    """调用 agent.process_direct，供 Web 使用（与 dialog_app 共用逻辑）。Web 默认不传历史，每次当新对话。"""
    from nanobot.ui.dialog_app import _call_agent as _impl
    return _impl(content, media or [], use_history=False)


def create_app():
    """创建 Flask 应用：/ 为聊天页，/api/chat 为对话接口，/static 为静态资源（如 UEGuide logo）。"""
    try:
        from flask import Flask, request, jsonify, send_file
    except ImportError:
        raise ImportError("请安装 Flask: pip install flask 或 pip install nanobot-ai[web]")

    ui_dir = Path(__file__).resolve().parent
    static_dir = ui_dir / "static"
    app = Flask(
        __name__,
        static_folder=str(static_dir) if static_dir.exists() else None,
        static_url_path="/static",
    )

    def get_index_path():
        p = Path(__file__).resolve().parent / "web_index.html"
        if p.exists():
            return p
        return None

    @app.route("/")
    def index():
        p = get_index_path()
        if p:
            return send_file(p, mimetype="text/html; charset=utf-8")
        return "<h1>web_index.html not found</h1>", 404

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = request.get_json(silent=True) or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "content required"}), 400
        try:
            reply = _call_agent(content, data.get("media"))
            return jsonify({"content": reply or ""})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


def run_web(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    """启动 Web 服务并在默认浏览器中打开聊天页。"""
    app = create_app()
    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")
    app.run(host=host, port=port, threaded=True, use_reloader=False)
