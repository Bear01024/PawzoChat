/*! PawzoChat dialogue import preview */
import { esc } from "./utils.js";
import { setTopBar, registerPageRenderer, goBack } from "./navigation.js";
import { toast } from "./ui.js";

let currentPersonaId = "";
let currentJob = null;

function area() {
  return document.getElementById("content-area");
}

function base() {
  return window.PAWZOCHAT_BASE || "";
}

async function renderDialogueImport(data) {
  currentPersonaId = data.personaId;
  currentJob = null;
  setTopBar("导入历史对话", true, "");
  area().innerHTML = `<div class="page">
    <div class="card">
      <div class="card-header">先预览，再写入</div>
      <div style="padding:12px 16px;color:var(--text-2);font-size:14px;line-height:1.65">
        支持云端导出的原始历史 JSON，或已经标记好的 <code>pawzochat.dialogue-marking.v1</code> 文件。
        预览不会修改当前角色；确认导入前会自动备份聊天、记忆和提示词。
      </div>
      <div style="padding:0 16px 16px">
        <input id="dialog-import-file" type="file" accept=".json,application/json" style="display:none"
          onchange="PawzoChat.dialogImportPreview(this)">
        <button class="btn-primary" onclick="document.getElementById('dialog-import-file').click()">选择 JSON 文件</button>
      </div>
    </div>
    <div id="dialog-import-preview"></div>
  </div>`;
}

export async function dialogImportPreview(input) {
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const form = new FormData();
  form.append("file", file, file.name);
  const preview = document.getElementById("dialog-import-preview");
  preview.innerHTML = '<div class="loading-center"><div class="spinner"></div></div>';
  try {
    const response = await fetch(
      `${base()}/api/personas/${encodeURIComponent(currentPersonaId)}/dialog-import/preview`,
      { method: "POST", body: form },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "预览失败");
    currentJob = data;
    renderPreview();
  } catch (error) {
    preview.innerHTML = "";
    toast(error.message || "预览失败", "error");
  }
}

function roundRow(item) {
  const ann = item.annotation || {};
  const users = (item.user_messages || []).map(message => message.text).join(" / ");
  const assistants = (item.assistant_messages || []).map(message => message.text).join(" / ");
  return `<div class="card" data-dialog-round="${item.round_index}">
    <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
      <label style="display:flex;gap:8px;align-items:center">
        <input class="dialog-round-selected" type="checkbox" checked> 第 ${item.round_index + 1} 轮
      </label>
      <select class="dialog-round-status" style="padding:5px 8px;border:1px solid var(--divider);border-radius:7px;background:var(--bg);color:var(--text-1)">
        <option value="keep" ${ann.status === "keep" ? "selected" : ""}>保留</option>
        <option value="edit" ${ann.status === "edit" ? "selected" : ""}>待修改</option>
        <option value="reject" ${ann.status === "reject" ? "selected" : ""}>排除</option>
        <option value="unreviewed" ${ann.status === "unreviewed" ? "selected" : ""}>未审核</option>
      </select>
    </div>
    <div style="padding:8px 16px 4px;font-size:13px;color:var(--text-2)"><b>用户：</b>${esc(users || "（空）")}</div>
    <div style="padding:4px 16px 12px;font-size:13px;color:var(--text-2)"><b>安歌：</b>${esc(assistants || "（空）")}</div>
  </div>`;
}

function renderPreview() {
  const summary = currentJob.summary || {};
  const reviewedHint = currentJob.reviewed
    ? "已读取人工标记；默认只有“保留”轮次会成为长期示例。"
    : "这是原始历史，所有轮次暂为“未审核”；默认不会直接变成长期示例。";
  const memories = (currentJob.memory_candidates || []).map((item, index) => `
    <label class="card-row" style="align-items:flex-start">
      <input class="dialog-memory-selected" data-index="${index}" type="checkbox" ${item.selected !== false ? "checked" : ""} style="margin-top:3px">
      <span class="row-label" style="white-space:normal;margin-left:10px">${esc(item.summary)}（重要度 ${item.importance}）</span>
    </label>`).join("");
  document.getElementById("dialog-import-preview").innerHTML = `
    <div class="card">
      <div class="card-header">预览汇总</div>
      <div style="padding:10px 16px;line-height:1.7;font-size:14px;color:var(--text-2)">
        共 ${summary.round_count || 0} 轮：保留 ${summary.keep || 0}，待修改 ${summary.edit || 0}，
        排除 ${summary.reject || 0}，未审核 ${summary.unreviewed || 0}；记忆候选 ${summary.memory_count || 0} 条。<br>
        ${reviewedHint}
      </div>
    </div>
    <div class="card">
      <div class="card-header">写入范围</div>
      <label class="card-row"><input id="dialog-import-history" type="checkbox" checked><span class="row-label" style="margin-left:10px">合并历史记录（精确去重）</span></label>
      <label class="card-row"><input id="dialog-import-examples" type="checkbox" checked><span class="row-label" style="margin-left:10px">导入“保留”轮次为长期对话示例</span></label>
      <label class="card-row"><input id="dialog-import-memories" type="checkbox" checked><span class="row-label" style="margin-left:10px">导入勾选的关系记忆</span></label>
      <label class="card-row"><input id="dialog-import-policy" type="checkbox" checked><span class="row-label" style="margin-left:10px">启用输出规则：通常 1～2 句，最多 3 句</span></label>
    </div>
    ${memories ? `<div class="card"><div class="card-header">关系记忆候选</div>${memories}</div>` : ""}
    <div style="padding:4px 16px 8px;color:var(--text-3);font-size:13px">可在下方逐轮取消勾选或修改分类。待修改、排除、未审核默认都不会成为示例。</div>
    <div id="dialog-import-rounds">${(currentJob.rounds || []).map(roundRow).join("")}</div>
    <div class="persona-actions">
      <button class="btn-primary" onclick="PawzoChat.dialogImportCommit()">确认导入</button>
    </div>`;
}

export async function dialogImportCommit() {
  if (!currentJob) return;
  const rows = [...document.querySelectorAll("[data-dialog-round]")];
  const selected = [];
  const overrides = {};
  for (const row of rows) {
    const index = Number(row.dataset.dialogRound);
    if (row.querySelector(".dialog-round-selected")?.checked) selected.push(index);
    overrides[String(index)] = {
      status: row.querySelector(".dialog-round-status")?.value || "unreviewed",
    };
  }
  const selectedMemories = [...document.querySelectorAll(".dialog-memory-selected:checked")]
    .map(node => Number(node.dataset.index));
  const body = {
    selected_round_indices: selected,
    selected_memory_indices: selectedMemories,
    round_overrides: overrides,
    example_statuses: ["keep"],
    import_history: !!document.getElementById("dialog-import-history")?.checked,
    import_examples: !!document.getElementById("dialog-import-examples")?.checked,
    import_memories: !!document.getElementById("dialog-import-memories")?.checked,
    enable_output_policy: !!document.getElementById("dialog-import-policy")?.checked,
  };
  try {
    const response = await fetch(
      `${base()}/api/personas/${encodeURIComponent(currentPersonaId)}/dialog-import/${currentJob.job_id}/commit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "导入失败");
    toast(`导入完成：历史新增 ${data.history?.added || 0} 条，示例 ${data.examples_added || 0} 条，记忆 ${data.memories_added || 0} 条`, "success");
    currentJob = null;
    goBack();
  } catch (error) {
    toast(error.message || "导入失败", "error");
  }
}

registerPageRenderer("dialogueImport", renderDialogueImport);
