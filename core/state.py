"""KBState —— 全局状态 Schema。

设计原则（需求第6节）：每个字段只由唯一一个 agent 负责写入，其余 agent 只读，
避免多节点写同一字段导致状态互相覆盖（此前项目卡住的主要原因）。

字段写入归属：
- source_type / raw_content / processed_note → Ingestion Agent 写
- retrieved_chunks                            → Retrieval/QA Agent 写
- related_notes                               → Correlation Agent 写
- answer                                      → Retrieval/QA Agent 写
- related_note_links                          → v2 预留，本期不写入逻辑
- messages                                    → 各节点追加（标准 reducer）

注意：intent 字段已移除——路由由 MCP Host 选工具完成，图内不再二次判断。
"""

from __future__ import annotations

from typing import Annotated, List, Optional, TypedDict

try:
    from langgraph.graph.message import add_messages
except ImportError:  # langgraph 未安装时仍可导入本模块做静态检查
    def add_messages(left, right):  # type: ignore[no-redef]
        return (left or []) + (right or [])


from typing import Literal  # noqa: E402


class KBState(TypedDict, total=False):
    """三个 Agent 共享的状态结构（total=False：字段皆可选，各子图按需使用）。"""

    # 用户输入（提问内容 / 摄取来源描述）
    user_input: str

    # ---- Ingestion Agent 写 ----
    source_type: Optional[Literal["video_url", "note_path", "raw_text"]]
    raw_content: Optional[str]          # Ingestion 的原始输入（转写文本 / 导入文本）
    processed_note: Optional[str]       # Ingestion 处理完的笔记内容（含 frontmatter）
    note_path: Optional[str]            # 落地后的笔记相对路径

    # ---- Correlation Agent 写 ----
    related_notes: List[dict]           # 建议关联列表：[{path, reason, score}]
    # 预留：v2 图谱感知检索用，本期不写入逻辑
    related_note_links: Optional[List[str]]

    # ---- Retrieval/QA Agent 写 ----
    retrieved_chunks: List[dict]        # 召回结果：[{content, path, score}]
    answer: Optional[str]               # 最终返回内容（含引用来源）

    # ---- 共享：对话历史，标准 reducer，节点追加不互相覆盖 ----
    messages: Annotated[list, add_messages]
