"""KBState —— 四条链共享的扁平状态 Schema。

[公共文件] 被以下链调用：
  - ingest_prepare   写 prepare_id / source_type / raw_content / prompt_for_host
  - ingest_finalize  读 prepare_id / note_content，写 processed_note / note_path / error
  - correlate        写 candidates
  - query            写 retrieved_chunks / no_hit_message

注意：本字段划分按「哪个节点写」组织，不是按链隔离的契约——改任一字段前请确认四条链
的读写都不受影响。

prepare 取得原文并创建会话，finalize 接收 Host 正文并创建 staged 笔记。
关联发现只返回 candidates；问答只返回 retrieved_chunks，生成式判断均由 Host 完成。
prompt_for_host 由 prepare/correlation/retrieval 三个独立入口分别写入。
related_note_links 中的 v2 仍指图谱感知检索，与本次 host-delegated 改造无关。
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional, TypedDict

try:
    from langgraph.graph.message import add_messages
except ImportError:
    def add_messages(left, right):
        return (left or []) + (right or [])


class KBState(TypedDict, total=False):
    """四个子图（prepare/finalize/correlation/retrieval）共享的状态结构。"""

    user_input: str

    # ---- ingestion_prepare_node 写 ----
    source_type: Optional[Literal["video_url", "video_file", "note_path", "raw_text"]]
    raw_content: Optional[str]          # 转写文本 / 导入文本（未格式化）
    prepare_id: Optional[str]           # finalize 靠会话 ID 查回权威来源

    # ---- ingestion_finalize_node 读/写 ----
    note_content: Optional[str]         # 输入：Host 生成的 Markdown 正文
    processed_note: Optional[str]       # 输出：补全 frontmatter 并强制 staged 的正文
    note_path: Optional[str]            # 输出：笔记相对 Vault 根目录的路径
    error: Optional[str]                # 校验错误必须进入 schema，避免被 LangGraph 丢弃

    # ---- correlation_node 写 ----
    candidates: List[dict]              # 未经生成处理的 [{path, snippet, score}]
    # 预留：v2 图谱感知检索用，本期不写入逻辑
    related_note_links: Optional[List[str]]

    # ---- retrieval_qa_node 写 ----
    retrieved_chunks: List[dict]        # [{content, path, score, source}]
    no_hit_message: Optional[str]       # 无命中时的确定性文案
    # answer: Optional[str]
    # host-delegated 起答案合成转移到 Host，服务端不再写入，保留注释便于比对。

    # ---- 共享：交给 Host 执行生成判断的指令 ----
    prompt_for_host: Optional[str]

    # ---- 共享：对话历史，标准 reducer ----
    messages: Annotated[list, add_messages]
