# PawzoChat - Multi-platform LLM-powered chatbot
"""Structured few-shot selection and deterministic outbound reply policies."""

from __future__ import annotations

import re
from typing import Iterable

from pawzochat.transport.models import normalize_output_policy

_NON_TEXT_RE = re.compile(r"[^0-9a-zA-Z\u3400-\u9fff]+")
_SEGMENT_RE = re.compile(r"[\\$\n]+")
_ELLIPSIS_RE = re.compile(r"…|\.{3,}|。{3,}|．{3,}")
_BRACKET_RE = re.compile(r"[()（）\[\]【】]")
_TIMESTAMP_RE = re.compile(
    r"(?:\d{4}[-年/]\d{1,2}[-月/]\d{1,2}(?:日)?|\d{1,2}:\d{2})"
)


def _normalise_text(text: str) -> str:
    return _NON_TEXT_RE.sub("", (text or "").lower())


def _bigrams(text: str) -> set[str]:
    value = _normalise_text(text)
    if len(value) < 2:
        return {value} if value else set()
    return {value[i:i + 2] for i in range(len(value) - 1)}


def _example_text(example: dict) -> str:
    return "\n".join(example.get("user_messages", []))


def _score_example(example: dict, query: str) -> float:
    if not example.get("enabled", True):
        return float("-inf")
    score = 1000.0 if example.get("pinned") else 0.0
    query_norm = _normalise_text(query)
    for keyword in example.get("trigger_keywords", []):
        key = _normalise_text(keyword)
        if key and key in query_norm:
            score += 20.0 + min(10.0, len(key))
    for tag in example.get("scenario_tags", []):
        key = _normalise_text(tag)
        if key and key in query_norm:
            score += 12.0
    left = _bigrams(query)
    right = _bigrams(_example_text(example))
    if left and right:
        score += 20.0 * len(left & right) / len(left | right)
    score += float(example.get("quality", 3)) * 0.5
    return score


def select_relevant_examples(
    examples: Iterable[dict],
    query: str,
    *,
    max_items: int = 4,
    max_chars: int = 1200,
) -> list[dict]:
    """Select pinned and locally relevant examples within a strict char budget."""
    ranked = sorted(
        ((_score_example(example, query), example) for example in examples),
        key=lambda pair: pair[0],
        reverse=True,
    )
    selected: list[dict] = []
    used = 0
    for score, example in ranked:
        if score == float("-inf"):
            continue
        if not example.get("pinned") and score <= 2.5:
            continue
        size = sum(len(v) for v in example.get("user_messages", []))
        size += sum(len(v) for v in example.get("assistant_messages", []))
        if selected and used + size > max_chars:
            continue
        selected.append(example)
        used += size
        if len(selected) >= max_items:
            break
    return selected


def build_example_messages(examples: Iterable[dict]) -> list[dict]:
    """Build explicit few-shot turns, separated from real conversation history."""
    items = list(examples)
    if not items:
        return []
    messages: list[dict] = [{
        "role": "system",
        "content": (
            "[相关行为示例]\n以下用户与角色对话仅示范说话方式和应对逻辑，"
            "不代表这些事件正在发生，也不是当前聊天历史。"
        ),
    }]
    for item in items:
        messages.append({"role": "user", "content": "\n".join(item["user_messages"])})
        messages.append({
            "role": "assistant",
            "content": "\\".join(item["assistant_messages"]),
        })
    return messages


def is_silence_reply(text: str, policy: dict) -> bool:
    """Recognize the configured silence token without case sensitivity."""
    token = normalize_output_policy(policy).get("silence_token", "<SILENT>")
    value = (text or "").strip()
    return bool(token) and value.casefold() == token.casefold()


def policy_prompt(policy: dict) -> str:
    p = normalize_output_policy(policy)
    if not p["enabled"]:
        return ""
    rules = [
        "[结构化输出规则]",
        f"通常回复1至{p['preferred_max_segments']}句，确有必要时最多{p['max_segments']}句。",
        f"总可见字符不超过{p['max_visible_chars']}字。",
        f"多句使用 {p['separator']} 分隔。",
        f"确实无需回复时只输出 {p['silence_token']}，不得输出说明文字。",
    ]
    if p["forbid_ellipsis"]:
        rules.append("任何位置都不要使用省略号。")
    if p["forbid_brackets"]:
        rules.append("不要使用括号或方括号描写动作、神态、场景或心理。")
    if p["forbid_timestamps"]:
        rules.append("不要在回复中输出日期或时间戳。")
    if p["banned_terms"]:
        rules.append("不要使用这些词语：" + "、".join(p["banned_terms"]))
    return "\n".join(rules)


def validate_reply(text: str, policy: dict) -> list[str]:
    """Return human-readable violations; an empty list means sendable."""
    p = normalize_output_policy(policy)
    if not p["enabled"] or is_silence_reply(text, p):
        return []
    value = (text or "").strip()
    if not value:
        return []
    violations: list[str] = []
    visible = re.sub(r"[\s\\$]", "", value)
    if len(visible) > p["max_visible_chars"]:
        violations.append(
            f"可见字符为{len(visible)}，超过上限{p['max_visible_chars']}"
        )
    segments = [part.strip() for part in _SEGMENT_RE.split(value) if part.strip()]
    if len(segments) > p["max_segments"]:
        violations.append(f"回复共{len(segments)}句，超过上限{p['max_segments']}")
    if p["forbid_ellipsis"] and _ELLIPSIS_RE.search(value):
        violations.append("包含省略号")
    if p["forbid_brackets"] and _BRACKET_RE.search(value):
        violations.append("包含括号或方括号")
    if p["forbid_timestamps"] and _TIMESTAMP_RE.search(value):
        violations.append("包含日期或时间戳")
    used_terms = [term for term in p["banned_terms"] if term and term in value]
    if used_terms:
        violations.append("包含禁用词：" + "、".join(used_terms))
    return violations
