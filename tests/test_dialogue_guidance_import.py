import json
import tempfile
import unittest
from pathlib import Path

from pawzochat.services.dialogue_guidance import (
    is_silence_reply,
    policy_prompt,
    select_relevant_examples,
    validate_reply,
)
from pawzochat.services.dialogue_import import (
    build_commit_material,
    parse_dialogue_export,
)
from pawzochat.store.conversation import ConversationStore
from pawzochat.transport.models import normalize_output_policy


def _message(role, text, timestamp):
    return {
        "role": role,
        "content": [{"type": "text", "text": text}],
        "source": "web",
        "timestamp": timestamp,
    }


def test_output_policy_prefers_two_but_allows_three():
    policy = normalize_output_policy({"enabled": True})
    assert policy["preferred_max_segments"] == 2
    assert policy["max_segments"] == 3
    assert "1" in policy_prompt(policy)
    assert validate_reply("a\\b\\c", policy) == []
    assert validate_reply("a\\b\\c\\d", policy)


def test_silence_token_is_a_real_empty_send_signal():
    policy = {"enabled": True, "silence_token": "<SILENT>"}
    assert is_silence_reply("<SILENT>", policy)
    assert is_silence_reply("  <silent>\n", policy)
    assert validate_reply("<silent>", policy) == []


def test_local_example_selection_respects_relevance_and_disabled():
    examples = [
        {
            "id": "sleep",
            "user_messages": ["cannot sleep"],
            "assistant_messages": ["rest"],
            "trigger_keywords": ["sleep"],
            "quality": 5,
            "enabled": True,
        },
        {
            "id": "disabled",
            "user_messages": ["cannot sleep"],
            "assistant_messages": ["bad"],
            "trigger_keywords": ["sleep"],
            "quality": 5,
            "enabled": False,
        },
    ]
    selected = select_relevant_examples(examples, "I cannot sleep", max_items=2)
    assert [item["id"] for item in selected] == ["sleep"]


def test_marked_import_defaults_examples_to_keep_only():
    marked = {
        "schema": "pawzochat.dialogue-marking.v1",
        "source": {"persona_id": "cloud"},
        "rounds": [
            {
                "round_index": 0,
                "user_messages": [{"text": "u0"}],
                "assistant_messages": [{"text": "a0"}],
                "annotation": {"status": "keep", "quality": 5},
            },
            {
                "round_index": 1,
                "user_messages": [{"text": "u1"}],
                "assistant_messages": [{"text": "a1"}],
                "annotation": {"status": "edit", "quality": 3},
            },
            {
                "round_index": 2,
                "user_messages": [{"text": "u2"}],
                "assistant_messages": [{"text": "a2"}],
                "annotation": {"status": "reject", "quality": 1},
            },
        ],
        "memory_candidates": [{"summary": "memory", "importance": 5}],
    }
    job = parse_dialogue_export(json.dumps(marked).encode())
    material = build_commit_material(job, {})
    assert job["summary"] == {
        "round_count": 3,
        "keep": 1,
        "edit": 1,
        "reject": 1,
        "unreviewed": 0,
        "memory_count": 1,
    }
    assert [item["id"] for item in material["examples"]] == ["import-cloud-0"]
    assert len(material["messages"]) == 6
    assert material["memories"][0]["summary"] == "memory"


def test_raw_history_is_previewed_as_unreviewed():
    raw = {
        "persona_id": "cloud",
        "messages": [
            _message("user", "hello", "2026-01-01T00:00:00+08:00"),
            _message("assistant", "hi", "2026-01-01T00:00:01+08:00"),
        ],
    }
    job = parse_dialogue_export(json.dumps(raw).encode(), "history.json")
    assert job["reviewed"] is False
    assert job["summary"]["unreviewed"] == 1
    assert build_commit_material(job, {})["examples"] == []


def test_history_merge_is_stable_and_deduplicated(tmp_path):
    store = ConversationStore(tmp_path)
    store.ensure_conversation("ange")
    imported = [
        _message("assistant", "later", "2026-01-01T00:00:02+08:00"),
        _message("user", "earlier", "2026-01-01T00:00:01+08:00"),
    ]
    first = store.merge_imported_messages("ange", imported)
    second = store.merge_imported_messages("ange", imported)
    assert first["added"] == 2
    assert second["added"] == 0
    conversation = store.get_conversation("ange")
    assert [item["role"] for item in conversation["messages"]] == ["user", "assistant"]


class DialogueGuidanceImportTests(unittest.TestCase):
    def test_policy(self):
        test_output_policy_prefers_two_but_allows_three()

    def test_silence(self):
        test_silence_token_is_a_real_empty_send_signal()

    def test_selection(self):
        test_local_example_selection_respects_relevance_and_disabled()

    def test_marked(self):
        test_marked_import_defaults_examples_to_keep_only()

    def test_raw(self):
        test_raw_history_is_previewed_as_unreviewed()

    def test_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            test_history_merge_is_stable_and_deduplicated(Path(directory))


if __name__ == "__main__":
    unittest.main()
