# PawzoChat - Multi-platform LLM-powered chatbot
"""Preview and commit reviewed dialogue imports."""

from __future__ import annotations

import copy
import shutil
import threading
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from pawzochat.paths import CHATS_DIR, DATA_DIR
from pawzochat.services.dialogue_import import build_commit_material, parse_dialogue_export
from pawzochat.transport.models import normalize_dialog_examples, normalize_output_policy
from pawzochat.web.routes import get_app

api_dialogue_import_bp = Blueprint("api_dialogue_import", __name__)

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 20


def _persona_exists(app, persona_id: str) -> bool:
    return persona_id in (app.config.get("personas", default={}) or {})


def _public_job(job: dict) -> dict:
    return copy.deepcopy(job)


def _backup_persona(app, persona_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = DATA_DIR / "import_backups" / persona_id / stamp
    target.mkdir(parents=True, exist_ok=False)
    sources = {
        "conversation.json": CHATS_DIR / persona_id / f"{persona_id}.json",
        "memory.json": CHATS_DIR / persona_id / "memory.json",
        "prompt.json": app.config.prompt_path(persona_id),
    }
    for name, source in sources.items():
        if source.is_file():
            shutil.copy2(source, target / name)
    return target


@api_dialogue_import_bp.route("/<persona_id>/dialog-import/preview", methods=["POST"])
def preview_dialogue_import(persona_id: str):
    app = get_app()
    if not _persona_exists(app, persona_id):
        return jsonify({"error": "Persona not found"}), 404
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "Choose a JSON file"}), 400
    try:
        payload = uploaded.stream.read(10 * 1024 * 1024 + 1)
        job = parse_dialogue_export(payload, uploaded.filename or "")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    job["target_persona_id"] = persona_id
    with _JOBS_LOCK:
        if len(_JOBS) >= _MAX_JOBS:
            _JOBS.pop(next(iter(_JOBS)), None)
        _JOBS[job["job_id"]] = job
    return jsonify(_public_job(job)), 201


@api_dialogue_import_bp.route("/<persona_id>/dialog-import/<job_id>", methods=["GET"])
def get_dialogue_import(persona_id: str, job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job or job.get("target_persona_id") != persona_id:
            return jsonify({"error": "Import preview not found"}), 404
        return jsonify(_public_job(job))


@api_dialogue_import_bp.route("/<persona_id>/dialog-import/<job_id>", methods=["DELETE"])
def delete_dialogue_import(persona_id: str, job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job or job.get("target_persona_id") != persona_id:
            return jsonify({"error": "Import preview not found"}), 404
        _JOBS.pop(job_id, None)
    return jsonify({"ok": True})


@api_dialogue_import_bp.route("/<persona_id>/dialog-import/<job_id>/commit", methods=["POST"])
def commit_dialogue_import(persona_id: str, job_id: str):
    app = get_app()
    if not _persona_exists(app, persona_id):
        return jsonify({"error": "Persona not found"}), 404
    with _JOBS_LOCK:
        stored = _JOBS.get(job_id)
        if not stored or stored.get("target_persona_id") != persona_id:
            return jsonify({"error": "Import preview not found"}), 404
        job = copy.deepcopy(stored)

    options = request.get_json(silent=True) or {}
    overrides = options.get("round_overrides", {})
    if isinstance(overrides, dict):
        for item in job["rounds"]:
            patch = overrides.get(str(item["round_index"]))
            if not isinstance(patch, dict):
                continue
            status = patch.get("status")
            if status in ("keep", "edit", "reject", "unreviewed"):
                item["annotation"]["status"] = status
            for field, limit in (("scenario_tags", 30), ("trigger_keywords", 50)):
                if isinstance(patch.get(field), list):
                    item["annotation"][field] = [
                        str(value).strip()[:100] for value in patch[field][:limit]
                        if str(value).strip()
                    ]

    selected_memories = options.get("selected_memory_indices")
    if isinstance(selected_memories, list):
        chosen = {int(value) for value in selected_memories}
        for index, item in enumerate(job.get("memory_candidates", [])):
            item["selected"] = index in chosen

    material = build_commit_material(job, options)
    backup_dir = _backup_persona(app, persona_id)
    result = {
        "backup_dir": str(backup_dir),
        "history": {"added": 0, "skipped": 0, "total": 0},
        "examples_added": 0,
        "memories_added": 0,
    }
    try:
        if bool(options.get("import_history", True)):
            result["history"] = app.conversation_store.merge_imported_messages(
                persona_id, material["messages"],
            )
        if bool(options.get("import_examples", True)) or bool(options.get("enable_output_policy", False)):
            persona = app.config.load_personas()[persona_id]
            existing = list(persona.dialog_examples)
            additions = []
            if bool(options.get("import_examples", True)):
                known_ids = {item.get("id") for item in existing}
                additions = [
                    item for item in material["examples"]
                    if item.get("id") not in known_ids
                ]
            policy = normalize_output_policy(persona.output_policy)
            if bool(options.get("enable_output_policy", False)):
                policy["enabled"] = True
                policy["preferred_max_segments"] = 2
                policy["max_segments"] = 3
            app.config.save_dialogue_guidance(
                persona_id,
                normalize_dialog_examples(existing + additions),
                policy,
            )
            result["examples_added"] = len(additions)
            result["output_policy_enabled"] = policy["enabled"]
        if bool(options.get("import_memories", True)):
            existing_summaries = {
                str(item.get("summary", "")).strip()
                for item in app.memory_service.load_memories(persona_id).get("memories", [])
            }
            for item in material["memories"]:
                if item["summary"] in existing_summaries:
                    continue
                app.memory_service.add_memory(
                    persona_id, item["summary"], item["importance"],
                )
                existing_summaries.add(item["summary"])
                result["memories_added"] += 1
    except Exception as exc:
        return jsonify({
            "error": f"Import failed; backup retained: {exc}",
            "backup_dir": str(backup_dir),
        }), 500

    with _JOBS_LOCK:
        _JOBS.pop(job_id, None)
    return jsonify({"ok": True, **result})
