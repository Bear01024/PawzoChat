# PawzoChat - Multi-platform LLM-powered chatbot
"""Parse reviewed conversation exports into history, examples, and memories."""

from __future__ import annotations

import copy
import json
import uuid
from collections import Counter
from typing import Any

from pawzochat.transport.models import normalize_dialog_examples

MARKING_SCHEMA = "pawzochat.dialogue-marking.v1"
_ALLOWED_STATUS = {"keep", "edit", "reject", "unreviewed"}


def _text_from_message(message: dict) -> str:
    return "\n".join(
        str(block.get("text", "")).strip()
        for block in message.get("content", [])
        if isinstance(block, dict)
        and block.get("type") == "text"
        and str(block.get("text", "")).strip()
    )


def _make_round(round_index: int, indexed: list[tuple[int, dict]]) -> dict:
    def collect(role: str) -> list[dict]:
        result = []
        for _, message in indexed:
            if message.get("role") != role:
                continue
            text = _text_from_message(message)
            if text:
                result.append({
                    "text": text,
                    "timestamp": str(message.get("timestamp", "")),
                    "source": str(message.get("source", "")),
                })
        return result

    return {
        "round_index": round_index,
        "source_message_range": [indexed[0][0], indexed[-1][0]],
        "user_messages": collect("user"),
        "assistant_messages": collect("assistant"),
        "annotation": {
            "quality": 3,
            "status": "unreviewed",
            "scenario_tags": [],
            "reason": "",
            "trigger_keywords": [],
        },
    }


def _rounds_from_messages(messages: list[dict]) -> list[dict]:
    rounds, current = [], []
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict) or raw.get("role") not in ("user", "assistant"):
            continue
        if raw.get("role") == "user" and current and current[-1][1].get("role") == "assistant":
            rounds.append(_make_round(len(rounds), current))
            current = []
        current.append((index, raw))
    if current:
        rounds.append(_make_round(len(rounds), current))
    return rounds


def _normalise_round(raw: dict, fallback_index: int) -> dict | None:
    if not isinstance(raw, dict):
        return None

    def items(values: Any) -> list[dict]:
        if not isinstance(values, list):
            return []
        output = []
        for value in values:
            item = value if isinstance(value, dict) else {"text": value}
            text = str(item.get("text", "")).strip()
            if text:
                output.append({
                    "text": text[:4000],
                    "timestamp": str(item.get("timestamp", ""))[:100],
                    "source": str(item.get("source", ""))[:100],
                })
        return output

    annotation = raw.get("annotation") if isinstance(raw.get("annotation"), dict) else {}
    status = str(annotation.get("status", "unreviewed")).lower()
    if status not in _ALLOWED_STATUS:
        status = "unreviewed"
    try:
        quality = max(1, min(5, int(annotation.get("quality", 3))))
    except (TypeError, ValueError):
        quality = 3
    users = items(raw.get("user_messages"))
    assistants = items(raw.get("assistant_messages"))
    if not users and not assistants:
        return None
    tags = annotation.get("scenario_tags", [])
    keywords = annotation.get("trigger_keywords", [])
    return {
        "round_index": int(raw.get("round_index", fallback_index)),
        "source_message_range": list(raw.get("source_message_range", []))[:2],
        "user_messages": users,
        "assistant_messages": assistants,
        "annotation": {
            "quality": quality,
            "status": status,
            "scenario_tags": [str(v).strip()[:100] for v in tags[:30] if str(v).strip()]
            if isinstance(tags, list) else [],
            "reason": str(annotation.get("reason", ""))[:1000],
            "trigger_keywords": [str(v).strip()[:100] for v in keywords[:50] if str(v).strip()]
            if isinstance(keywords, list) else [],
        },
    }


def parse_dialogue_export(payload: bytes, filename: str = "") -> dict:
    if len(payload) > 10 * 1024 * 1024:
        raise ValueError("File is too large (10 MB maximum)")
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The file is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("The JSON root must be an object")

    if data.get("schema") == MARKING_SCHEMA:
        raw_rounds = data.get("rounds", [])
        if not isinstance(raw_rounds, list):
            raise ValueError("The marked file does not contain a rounds array")
        source = data.get("source", {}) if isinstance(data.get("source"), dict) else {}
        raw_memories = data.get("memory_candidates", [])
        reviewed = True
    elif isinstance(data.get("messages"), list):
        raw_rounds = _rounds_from_messages(data["messages"])
        source = {
            "file": filename,
            "persona_id": data.get("persona_id", ""),
            "message_count": len(data["messages"]),
        }
        raw_memories = []
        reviewed = False
    else:
        raise ValueError("Unsupported dialogue JSON format")

    rounds = []
    for index, raw in enumerate(raw_rounds):
        item = _normalise_round(raw, index)
        if item:
            rounds.append(item)

    memories = []
    if isinstance(raw_memories, list):
        for item in raw_memories[:200]:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            try:
                importance = max(1, min(5, int(item.get("importance", 3))))
            except (TypeError, ValueError):
                importance = 3
            memories.append({
                "summary": summary[:2000],
                "importance": importance,
                "selected": bool(item.get("selected", True)),
            })

    counts = Counter(item["annotation"]["status"] for item in rounds)
    return {
        "job_id": uuid.uuid4().hex,
        "schema": MARKING_SCHEMA,
        "reviewed": reviewed,
        "source": source,
        "rounds": rounds,
        "memory_candidates": memories,
        "summary": {
            "round_count": len(rounds),
            "keep": counts["keep"],
            "edit": counts["edit"],
            "reject": counts["reject"],
            "unreviewed": counts["unreviewed"],
            "memory_count": len(memories),
        },
    }


def round_to_example(item: dict, source: dict) -> dict:
    annotation = item["annotation"]
    return {
        "id": f"import-{source.get('persona_id', 'unknown')}-{item['round_index']}",
        "user_messages": [message["text"] for message in item["user_messages"]],
        "assistant_messages": [message["text"] for message in item["assistant_messages"]],
        "scenario_tags": annotation["scenario_tags"],
        "trigger_keywords": annotation["trigger_keywords"],
        "quality": annotation["quality"],
        "enabled": True,
        "pinned": False,
        "source": {
            "kind": "dialogue_import",
            "persona_id": source.get("persona_id", ""),
            "round_index": item["round_index"],
        },
    }


def rounds_to_messages(rounds: list[dict]) -> list[dict]:
    output = []
    for item in rounds:
        for role, key in (("user", "user_messages"), ("assistant", "assistant_messages")):
            for message in item[key]:
                output.append({
                    "role": role,
                    "content": [{"type": "text", "text": message["text"]}],
                    "source": message.get("source", "") or "import",
                    "timestamp": message.get("timestamp", ""),
                })
    return output


def build_commit_material(job: dict, options: dict) -> dict:
    selected = options.get("selected_round_indices")
    selected_set = {int(value) for value in selected} if isinstance(selected, list) else None
    rounds = [
        copy.deepcopy(item) for item in job["rounds"]
        if selected_set is None or item["round_index"] in selected_set
    ]
    statuses = options.get("example_statuses", ["keep"])
    if not isinstance(statuses, list):
        statuses = ["keep"]
    examples = [
        round_to_example(item, job["source"]) for item in rounds
        if item["annotation"]["status"] in statuses
        and item["user_messages"] and item["assistant_messages"]
    ]
    return {
        "messages": rounds_to_messages(rounds),
        "examples": normalize_dialog_examples(examples),
        "memories": [
            item for item in job.get("memory_candidates", [])
            if item.get("selected", True)
        ],
    }
