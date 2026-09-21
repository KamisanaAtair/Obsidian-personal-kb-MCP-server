"""【已注释 / 对 LLM 默认不存在】path_url_recognizer.py —— 全文件死代码。

[调用链] 无 —— 本文件不被任何链调用。

判定依据（本次纵切时全仓扫查）：
- 文件内所有顶层函数的调用方只有 tests/test_interfaces.py 的 test_recognizer_no_model_fallback，
  而该测试本身也已一并注释（见 tests/test_interfaces.py 文末）。
- 主链的「来源判别」实际由 src/ingestion.py 的 _detect_source_type
  完成，它用的是 src/ingest_prepare/tools/video_to_text.py 里的 extract_video_url /
  extract_video_file —— 也就是说本文件与 video_to_text 里曾并存两套 URL/路径识别实现，
  本文件是被「成本转嫁」重构绕过的那一套（原设计把歧义消解交给模型，改为「服务端不调模型消歧」后失效）。

保留注释仅供人工追溯历史，不代表当前设计契约：对本仓库的 LLM 而言，本文件默认不存在，
不应被引用、不应被当作可用接口，也不应据此推断系统具备 URL/路径识别与消歧能力。
需要该能力时，应在 src/ingest_prepare/tools/ 下重新实现并登记调用方，而不是取消本注释。

—— 以下为原文，全段注释 ——
"""
# """确定性文件路径与 URL 识别：正则匹配、归一化和歧义标记。
#
# host-delegated 移除原 Stage 2 的生成式模型兜底。规范的 URL 与路径继续通过
# Stage 1 正则提取；多候选、裸域名、残缺地址等保留 needs_review 提示，由调用方
# 复核。recognize/extract_primary/extract_primary_sync 接口继续兼容已有调用方。
# """
#
# from __future__ import annotations
#
# import logging
# import re
# from dataclasses import dataclass, field
# from pathlib import Path
# from typing import Optional
#
# from src.common.settings import Settings, get_settings
#
# logger = logging.getLogger(__name__)
#
# # ===========================================================================
# # 数据结构
# # ===========================================================================
#
#
# @dataclass
# class RecognizedRef:
#     """单条识别结果。"""
#
#     raw_text: str            # 原始子串（从输入逐字截取）
#     kind: str                # "url" | "file_path" | "unknown"
#     normalized: str          # 归一化后的地址
#     scheme: str              # "https" | "http" | "file" | "obsidian" | "none"
#     confidence: float        # 0.0 - 1.0
#     needs_review: bool       # 是否需人工复核
#     stage: str = "regex"     # "regex" | "fallback" —— 产出此结果的阶段
#     reason: str = ""         # 置信度/歧义说明
#
#
# @dataclass
# class RecognitionResult:
#     """识别总结果。"""
#
#     refs: list[RecognizedRef] = field(default_factory=list)
#     primary: Optional[RecognizedRef] = None   # 置信度最高的引用
#     used_llm: bool = False                    # 兼容字段；host-delegated 恒为 False
#     overall_confidence: float = 0.0
#
#
# # ===========================================================================
# # 常量与正则
# # ===========================================================================
#
# # URL 尾部可能粘连的标点（中英文句读）—— 从匹配结果尾部剥离
# _TRAILING_PUNCT = ".,;:!?\"'`"
# _CJK_TRAILING = "，。；：！？、〃》）】》「』」』」』""''``·・…—"
# _ALL_TRAILING = _TRAILING_PUNCT + _CJK_TRAILING
#
# # 含完整协议头的 URL（排除空白、尖/圆/方括号、引号、CJK 字符与全角标点）
# _URL_RE = re.compile(
#     r"(?:https?|file|obsidian)://[^\s<>\"'()\[\]\u3000-\u9fff\uff00-\uffef]+",
#     re.IGNORECASE,
# )
#
# # Windows 绝对路径：盘符 + 分隔符 + 路径段（允许 CJK，遇空白/引号/括号停止）
# _WIN_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'()\[\]<>{}]+")
#
# # UNC 路径：\\\\server\share\... （正则中 \\\\ 匹配两个反斜杠）
# _UNC_PATH_RE = re.compile(r"\\\\[^\s\"'()\[\]<>{}|*?]+")
#
# # Unix 绝对路径：/path/...（负向回溯排除域名片段后的 /，避免把
# # bilibili.com/video 中的 /video 误匹配为 Unix 路径）
# _UNIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9.])/(?:[^\s\"'()\[\]<>{}]+)/[^\s\"'()\[\]<>{}]*")
#
# # 裸域名（无协议头）：xxx.yy/zzz —— 固有歧义，低置信度，需复核
# _BARE_DOMAIN_RE = re.compile(
#     r"(?<![\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?::\d+)?(?:/[^\s\"'()\[\]<>{}]*)?",
#     re.IGNORECASE,
# )
#
# # 常见文件扩展名（用于验证路径是否"干净"）
# _FILE_EXT_RE = re.compile(r"\.[a-zA-Z0-9]{1,10}$")
#
# # 已知视频站关键字（与 video_to_text 保持一致，用于裸域名补全判断）
# _KNOWN_DOMAINS = (
#     "bilibili.com", "b23.tv", "youtube.com", "youtu.be",
#     "v.qq.com", "github.com", "notion.so", "obsidian.md",
# )
#
# # 启发式线索关键词（无正则匹配时判断文本是否可能含路径/URL）
# _HEURISTIC_KEYWORDS = (
#     "路径", "文件", "链接", "网址", "地址", "目录",
#     "path", "file", "url", "link", "folder", "directory",
# )
#
# # ===========================================================================
# # 归一化
# # ===========================================================================
#
#
# def _rstrip_punct(s: str) -> str:
#     """从尾部反复剥离 ASCII + CJK 标点。"""
#     while s and s[-1] in _ALL_TRAILING:
#         s = s[:-1]
#     return s
#
#
# def _strip_quotes(s: str) -> str:
#     """剥离首尾配对引号。"""
#     for q_open, q_close in (('"', '"'), ("'", "'"), ("`", "`"),
#                             ("\u201c", "\u201d"), ("\u2018", "\u2019")):
#         if len(s) >= 2 and s[0] == q_open and s[-1] == q_close:
#             return s[1:-1]
#     return s
#
#
# def normalize_url(url: str) -> str:
#     """归一化 URL：去尾部标点、小写 scheme 与 host、保留 path/query/fragment 原样。"""
#     url = _rstrip_punct(url)
#     m = re.match(r"^([a-zA-Z]+)://([^/]+)(/.*)?$", url)
#     if m:
#         scheme = m.group(1).lower()
#         host = m.group(2).lower()
#         path = m.group(3) or ""
#         return f"{scheme}://{host}{path}"
#     return url
#
#
# def normalize_path(path: str) -> str:
#     """归一化路径：去尾部标点、反斜杠统一为正斜杠、合并冗余分隔符。
#
#     UNC 路径保留前导双斜杠。Windows 盘符路径变为 ``D:/foo/bar`` 形式。
#     """
#     path = _rstrip_punct(path)
#     is_unc = path.startswith("\\\\") or path.startswith("//")
#     path = path.replace("\\", "/")
#     if is_unc:
#         # 保留前导双斜杠，合并后续冗余
#         rest = re.sub(r"/{2,}", "/", path[2:])
#         path = "//" + rest if rest else "//"
#     else:
#         path = re.sub(r"/{2,}", "/", path)
#     return path
#
#
# # ===========================================================================
# # Stage 1：正则匹配
# # ===========================================================================
#
#
# def _has_file_extension(path: str) -> bool:
#     """路径是否以文件扩展名结尾（判别"干净路径"的依据之一）。"""
#     return bool(_FILE_EXT_RE.search(path))
#
#
# def _looks_like_clean_path(raw: str) -> bool:
#     """判断正则匹配到的路径是否"干净"（无需歧义复核）。
#
#     判据：
#     1. 剥离尾部标点后仍以文件扩展名结尾 → 干净
#     2. 路径在文件系统上真实存在 → 干净（最强信号）
#     3. 否则 → 可能不干净（尾部粘连了自然语言文本）
#     """
#     cleaned = _rstrip_punct(raw)
#     if Path(cleaned).exists():
#         return True
#     if _has_file_extension(cleaned):
#         return True
#     return False
#
#
# def _detect_scheme(raw: str, kind: str) -> str:
#     """从原始文本推断 scheme。"""
#     low = raw.lower()
#     for s in ("https", "http", "file", "obsidian"):
#         if low.startswith(f"{s}://"):
#             return s
#     if kind == "file_path":
#         return "none"
#     return "none"
#
#
# def _confidence_for_url(raw: str) -> float:
#     """URL 的 Stage 1 置信度。"""
#     cleaned = _rstrip_punct(raw)
#     # 有完整 scheme + host → 高置信度
#     if re.match(r"^[a-zA-Z]+://[^\s/]+", cleaned):
#         return 0.95
#     return 0.5
#
#
# def _confidence_for_path(raw: str) -> float:
#     """文件路径的 Stage 1 置信度。"""
#     cleaned = _rstrip_punct(raw)
#     exists = Path(cleaned).exists()
#     has_ext = _has_file_extension(cleaned)
#     if exists and has_ext:
#         return 0.95
#     if has_ext:
#         return 0.85
#     if exists:
#         return 0.8   # 存在的目录
#     return 0.6       # 无扩展名、不存在 → 偏低
#
#
# def _build_ref(raw: str, kind: str, stage: str = "regex") -> RecognizedRef:
#     """从原始子串构建一条 RecognizedRef（含归一化与置信度）。"""
#     if kind == "url":
#         norm = normalize_url(raw)
#         conf = _confidence_for_url(raw)
#     else:
#         norm = normalize_path(raw)
#         conf = _confidence_for_path(raw)
#     scheme = _detect_scheme(raw, kind)
#     needs = conf < 0.85
#     reason = "" if not needs else f"Stage 1 置信度 {conf:.2f} 不足高置信阈值"
#     return RecognizedRef(
#         raw_text=raw,
#         kind=kind,
#         normalized=norm,
#         scheme=scheme,
#         confidence=conf,
#         needs_review=needs,
#         stage=stage,
#         reason=reason,
#     )
#
#
# def stage1_regex(text: str) -> list[RecognizedRef]:
#     """Stage 1：正则快速匹配，返回候选列表。
#
#     匹配优先级（先匹配的吸收后续，避免重叠）：
#     1. 含完整协议头的 URL
#     2. UNC 路径
#     3. Windows 绝对路径
#     4. Unix 绝对路径
#     5. 裸域名（低置信度，通常需复核）
#     """
#     refs: list[RecognizedRef] = []
#     consumed_spans: list[tuple[int, int]] = []
#
#     def _is_consumed(start: int, end: int) -> bool:
#         for cs, ce in consumed_spans:
#             if start < ce and end > cs:
#                 return True
#         return False
#
#     def _add(pattern: re.Pattern, kind: str) -> None:
#         for m in pattern.finditer(text):
#             if _is_consumed(m.start(), m.end()):
#                 continue
#             raw = _rstrip_punct(m.group(0))
#             if not raw:
#                 continue
#             refs.append(_build_ref(raw, kind))
#             consumed_spans.append((m.start(), m.end()))
#
#     # 1. URL（最高优先级，吸收后续路径/裸域名）
#     _add(_URL_RE, "url")
#     # 2. UNC 路径
#     _add(_UNC_PATH_RE, "file_path")
#     # 3. Windows 绝对路径
#     _add(_WIN_PATH_RE, "file_path")
#     # 4. Unix 绝对路径
#     _add(_UNIX_PATH_RE, "file_path")
#     # 5. 裸域名（最低优先级，固有歧义）
#     _add(_BARE_DOMAIN_RE, "url")
#
#     return refs
#
#
# # ===========================================================================
# # 歧义复核判定
# # ===========================================================================
#
#
# def _has_heuristic_signal(text: str) -> bool:
#     """无正则匹配时，检测文本是否可能含路径/URL 线索。
#
#     启发式判据：
#     - 含已知域名片段（如 bilibili.com、github.com）
#     - 含路径/URL 相关关键词附近有疑似地址 token
#     - 含 "://" 片段（协议头残缺）
#     - 含盘符 + 冒号片段（如 D: 后跟非盘符内容）
#     """
#     low = text.lower()
#     # 已知域名片段
#     if any(d in low for d in _KNOWN_DOMAINS):
#         return True
#     # 协议头残片
#     if "://" in low or "http" in low or "https" in low:
#         return True
#     # 盘符 + 分隔符残片（D:\ 或 D:/ 但正则未命中——可能被 CJK 标点截断）
#     if re.search(r"[A-Za-z]:[\\/]", text):
#         return True
#     # 关键词附近有疑似路径 token（含 . 后跟字母，疑似扩展名）
#     if any(kw in low for kw in _HEURISTIC_KEYWORDS):
#         if re.search(r"\.[a-zA-Z]{1,10}\b", text):
#             return True
#     return False
#
#
# def _has_ambiguity_markers(text: str, ref: RecognizedRef) -> bool:
#     """检测单条结果是否带有歧义标记（即使置信度达标也需复核）。"""
#     raw = ref.raw_text
#     # 路径含空格且未引号包裹 → 边界模糊
#     if ref.kind == "file_path" and " " in raw:
#         return True
#     # 尾部有 CJK 字符粘连（剥离标点后仍有 CJK 文本）
#     cleaned = _rstrip_punct(raw)
#     if ref.kind == "file_path" and re.search(r"[\u4e00-\u9fff]$", cleaned):
#         # 路径以中文字符结尾 → 可能粘连了自然语言
#         if not _has_file_extension(cleaned):
#             return True
#     # 裸域名（无 scheme）→ 固有歧义
#     if ref.kind == "url" and ref.scheme == "none":
#         return True
#     return False
#
#
# def _decide_review(
#     text: str,
#     stage1_refs: list[RecognizedRef],
#     threshold: float,
# ) -> tuple[bool, str]:
#     """判断正则结果是否需要歧义复核。
#
#     Returns
#     -------
#     (needs_review, reason)
#     """
#     # 1. 无正则匹配但启发式检测到线索
#     if not stage1_refs:
#         if _has_heuristic_signal(text):
#             return True, "正则无匹配但启发式检测到路径/URL 线索"
#         return False, ""
#
#     # 2. 多候选 → 需消歧
#     if len(stage1_refs) > 1:
#         return True, f"存在 {len(stage1_refs)} 个候选，需复核主引用"
#
#     # 3. 单候选但置信度低于阈值
#     ref = stage1_refs[0]
#     if ref.confidence < threshold:
#         return True, f"置信度 {ref.confidence:.2f} 低于阈值 {threshold}"
#
#     # 4. 单候选高置信度但带歧义标记
#     if _has_ambiguity_markers(text, ref):
#         return True, "存在歧义标记（路径含空格/裸域名/CJK 粘连）"
#
#     return False, ""
#
#
# def _fallback_to_stage1(
#     stage1_refs: list[RecognizedRef],
#     reason: str,
# ) -> list[RecognizedRef]:
#     """兜底：Stage 1 结果全部标记 needs_review 并附加 reason。"""
#     out: list[RecognizedRef] = []
#     for r in stage1_refs:
#         r2 = RecognizedRef(
#             raw_text=r.raw_text,
#             kind=r.kind,
#             normalized=r.normalized,
#             scheme=r.scheme,
#             confidence=min(r.confidence, 0.6),  # 兜底降低置信度
#             needs_review=True,
#             stage="fallback",
#             reason=f"{r.reason}; {reason}" if r.reason else reason,
#         )
#         out.append(r2)
#     return out
#
#
# # ===========================================================================
# # 公共 API
# # ===========================================================================
#
#
# async def recognize(
#     text: str,
#     settings: Settings | None = None,
# ) -> RecognitionResult:
#     """确定性识别入口：正则提取后标记歧义，全程不调用生成式模型。"""
#     s = settings or get_settings()
#     refs = stage1_regex(text)
#     needs_review, reason = _decide_review(
#         text, refs, s.path_recognizer_confidence_threshold
#     )
#     if needs_review:
#         logger.info("[path_recognizer] 正则结果需要复核：%s", reason)
#         refs = _fallback_to_stage1(refs, reason)
#     primary = max(refs, key=lambda ref: ref.confidence) if refs else None
#     return RecognitionResult(
#         refs=refs,
#         primary=primary,
#         used_llm=False,
#         overall_confidence=primary.confidence if primary else 0.0,
#     )
#
#
# async def extract_primary(
#     text: str,
#     settings: Settings | None = None,
# ) -> Optional[RecognizedRef]:
#     """便捷方法：返回置信度最高的单条引用，无则 None。"""
#     result = await recognize(text, settings)
#     return result.primary
#
#
# def extract_primary_sync(
#     text: str,
#     settings: Settings | None = None,
# ) -> Optional[RecognizedRef]:
#     """同步便捷方法（仅 Stage 1，不执行额外歧义检查）。
#
#     保留原有快速路径行为，适用于 ingestion 节点的来源判别。
#     """
#     stage1 = stage1_regex(text)
#     if not stage1:
#         return None
#     return max(stage1, key=lambda r: r.confidence)
