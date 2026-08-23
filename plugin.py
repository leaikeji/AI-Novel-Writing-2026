"""QwenPaw plugin entry point for AI小说世界2026."""

from pathlib import Path
from typing import Any

from .backend.app import pawapp
from .backend.tools import novel_get_context, novel_get_document, novel_search

PLUGIN_ROOT = Path(__file__).resolve().parent


class AINovelWorldPlugin:
    """Register only the public PawApp, Skill, and tool contracts."""

    def register(self, api: Any) -> None:
        pawapp.register(api)
        api.register_skill_provider(
            PLUGIN_ROOT / "skills",
            enabled_by_default=False,
            channels=["console"],
        )
        api.register_tool(
            tool_name="novel_get_context",
            tool_func=novel_get_context,
            description="读取指定小说的当前章节、前文和正式故事事实（只读）",
            icon="📚",
            enabled=False,
            tool_type="internal",
        )
        api.register_tool(
            tool_name="novel_get_document",
            tool_func=novel_get_document,
            description="读取指定小说文档的当前 working copy 与版本元数据（只读）",
            icon="📄",
            enabled=False,
            tool_type="internal",
        )
        api.register_tool(
            tool_name="novel_search",
            tool_func=novel_search,
            description="在指定小说当前正文中进行关键词检索（只读）",
            icon="🔎",
            enabled=False,
            tool_type="internal",
        )


plugin = AINovelWorldPlugin()
