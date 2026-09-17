const $ = (s) => document.querySelector(s);
let tasks = [],
  current = null,
  pollTimer = null,
  busy = false;
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
async function api(path, body) {
  const r = await fetch(
    "/api/" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const d = await r.json();
  if (!r.ok)
    throw Error(
      typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail),
    );
  return d;
}
function ticket(id) {
  const t = tasks.find((t) => t.id === id);
  if (!t) return;
  $("#ticket-title").textContent = t.title;
  $("#ticket-id").textContent = t.ticket;
  $("#description").textContent = t.description;
  $("#filename").textContent = t.file;
  $("#source").textContent = t.source;
  $("#lesson").textContent = t.lesson;
  $("#repros").innerHTML = t.visible_tests
    .map(
      ([a, v]) =>
        `<div class="repro">${esc(t.function)}(${a.map((x) => esc(JSON.stringify(x))).join(", ")}) → ${esc(JSON.stringify(v))}</div>`,
    )
    .join("");
}
function locks(active) {
  busy = active;
  $("#run").disabled = active;
  ["task", "mode", "strategy"].forEach((id) => ($("#" + id).disabled = active));
}
function clearResult() {
  ["visible", "holdout", "tokens", "duration"].forEach(
    (id) => ($("#" + id).textContent = "—"),
  );
  $("#trace").innerHTML = "";
  $("#diff").textContent = "Waiting for a proposal…";
  $("#model-detail").innerHTML = "";
  $("#proposal-summary").textContent =
    "Building context and reproducing the bug…";
  $("#tests").innerHTML =
    '<p class="muted">Regression tests run after the final proposal.</p>';
  $("#gate-detail").textContent = "Verification pending.";
  $("#gate-detail").className = "callout neutral";
  $("#gate-state").textContent = "WAITING";
  $("#gate-state").className = "badge";
  $("#attempts").textContent = "NO PROPOSAL";
  $("#digest").textContent = "Artifact SHA-256 appears after verification.";
  $("#approve").disabled = true;
  $("#approval").textContent = "Approval only unlocks a patch download.";
  $("#note").value = "";
  links(null);
}
function links(r) {
  $("#download").classList.toggle("disabled", r?.status !== "approved");
  $("#download").setAttribute(
    "aria-disabled",
    r?.status === "approved" ? "false" : "true",
  );
  if (r?.status === "approved") $("#download").href = `/api/runs/${r.id}/patch`;
  else $("#download").removeAttribute("href");
  $("#report").classList.toggle("disabled", !r);
  $("#report").setAttribute("aria-disabled", r ? "false" : "true");
  if (r) $("#report").href = `/api/runs/${r.id}/report`;
  else $("#report").removeAttribute("href");
}
$("#task").onchange = (e) => {
  if (current) {
    current = null;
    clearResult();
    $("#run-status").textContent = "READY";
    $("#message").textContent = "New ticket selected. Start another run.";
  }
  ticket(e.target.value);
};
$("#run").onclick = async () => {
  if (busy) return;
  clearTimeout(pollTimer);
  locks(true);
  clearResult();
  $("#message").textContent = "Starting a bounded repair run…";
  try {
    current = await api("runs", {
      task_id: $("#task").value,
      mode: $("#mode").value,
      strategy: $("#strategy").value,
    });
    render(current);
    poll();
  } catch (e) {
    $("#message").textContent = e.message;
    locks(false);
  }
};
async function poll() {
  try {
    const r = await api("runs/" + current.id);
    render(r);
    if (["queued", "running"].includes(r.status))
      pollTimer = setTimeout(poll, 850);
    else {
      locks(false);
      await refreshHistory();
    }
  } catch (e) {
    $("#message").textContent = e.message;
    locks(false);
  }
}
function render(r) {
  current = r;
  ticket(r.task_id);
  $("#run-status").textContent = r.status.replaceAll("_", " ").toUpperCase();
  $("#run-status").className =
    "badge " +
    (["approved", "needs_review"].includes(r.status)
      ? "good"
      : ["rejected", "error", "interrupted"].includes(r.status)
        ? "bad"
        : "");
  $("#tokens").textContent = r.total_tokens.toLocaleString();
  $("#duration").textContent = (r.elapsed_ms / 1000).toFixed(1) + "s";
  $("#attempts").textContent =
    r.attempts.length + " ATTEMPT" + (r.attempts.length === 1 ? "" : "S");
  const last = r.attempts.at(-1);
  $("#visible").textContent = last?.tests
    ? `${last.tests.passed} / ${last.tests.total}`
    : "— / 2";
  $("#holdout").textContent = r.gate
    ? `${r.gate.holdout.passed} / ${r.gate.holdout.total}`
    : "— / 8";
  $("#trace").innerHTML = r.events
    .map(
      (e, i) =>
        `<div class="event"><div class="event-icon">${String(i + 1).padStart(2, "0")}</div><div><div class="event-name">${esc(e.stage)}<time>${new Date(e.at).toLocaleTimeString()}</time></div><div class="event-message">${esc(e.message)}</div></div></div>`,
    )
    .join("");
  $("#trace").scrollTop = $("#trace").scrollHeight;
  if (last) {
    $("#proposal-summary").textContent = last.summary;
    $("#diff").innerHTML = r.diff
      ? r.diff
          .split("\n")
          .map(
            (l) =>
              `<span class="${l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@") ? "meta" : l.startsWith("+") ? "add" : l.startsWith("-") ? "remove" : ""}">${esc(l) || " "}</span>`,
          )
          .join("")
      : esc(
          last.policy === "rejected"
            ? "Policy blocked this expression:\n" + last.expression
            : "No source change proposed.",
        );
    $("#model-detail").innerHTML =
      `<p>Context: ${esc(r.context?.file)} · lines ${r.context?.start_line}–${r.context?.end_line}<br>Method: ${esc(r.context?.method)}</p>` +
      r.attempts
        .map(
          (a) =>
            `<details><summary>Attempt ${a.number} · ${esc(a.model)} · ${a.latency_ms} ms</summary><p>${esc(a.policy_reason || "Policy: " + a.policy)}</p><pre>${esc(JSON.stringify({ expression: a.expression, summary: a.summary, usage: a.usage, prompt: a.prompt }, null, 2))}</pre></details>`,
        )
        .join("");
  }
  const gate = r.gate;
  $("#gate-state").textContent = gate
    ? gate.passed
      ? "GATE PASSED"
      : "GATE FAILED"
    : r.status === "rejected"
      ? "POLICY BLOCKED"
      : "WAITING";
  $("#gate-state").className =
    "badge " + (gate?.passed ? "good" : r.status === "rejected" ? "bad" : "");
  $("#gate-detail").className =
    "callout " +
    (gate?.passed ? "good" : r.status === "rejected" ? "bad" : "neutral");
  $("#gate-detail").textContent = gate
    ? gate.passed
      ? "All public and held-out regression cases passed. Inspect the diff and approve this exact artifact."
      : "The patch failed independent verification. Approval and patch export are blocked."
    : last?.policy === "rejected"
      ? last.policy_reason
      : "Verification pending.";
  $("#digest").textContent = r.artifact_sha
    ? "SHA-256 · " + r.artifact_sha
    : "Artifact SHA-256 appears after verification.";
  $("#approve").disabled = r.status !== "needs_review";
  links(r);
  $("#approval").textContent = r.approval
    ? "Approved: " +
      r.approval.note +
      " · " +
      new Date(r.approval.at).toLocaleString()
    : "Approval only unlocks a patch download. It does not push, merge, or edit your repositories.";
  if (gate) {
    const rows = [
      ...gate.visible.cases.map((c) => ({ ...c, split: "Public" })),
      ...gate.holdout.cases.map((c) => ({ ...c, split: "Regression" })),
    ];
    $("#tests").innerHTML =
      "<table><thead><tr><th>Suite</th><th>Inputs</th><th>Expected</th><th>Actual</th><th>Result</th></tr></thead><tbody>" +
      rows
        .map(
          (c) =>
            `<tr><td>${c.split}</td><td><code>${esc(JSON.stringify(c.inputs))}</code></td><td>${esc(JSON.stringify(c.expected))}</td><td>${esc(c.error || JSON.stringify(c.actual))}</td><td class="${c.passed ? "pass" : "fail"}">${c.passed ? "PASS" : "FAIL"}</td></tr>`,
        )
        .join("") +
      "</tbody></table>";
  }
  const messages = {
    queued: "Run queued. Preparing the fixture workspace…",
    running: "Running locally. Follow the trace to inspect each decision.",
    needs_review:
      "The gate passed. Review the diff and tests before approving.",
    approved:
      "Approved. You can download the verified patch and full run report.",
    rejected:
      "Proposal rejected. Inspect the policy or regression failures below.",
    error: r.error,
    interrupted: r.error,
  };
  $("#message").textContent = messages[r.status] || r.status;
}
$("#approve").onclick = async () => {
  const note = $("#note").value.trim();
  if (note.length < 3) {
    $("#message").textContent = "Add a review note before approving.";
    return;
  }
  $("#approve").disabled = true;
  try {
    render(
      await api("runs/" + current.id + "/approve", {
        artifact_sha: current.artifact_sha,
        note,
      }),
    );
    await refreshHistory();
  } catch (e) {
    $("#message").textContent = e.message;
    $("#approve").disabled = current.status !== "needs_review";
  }
};
async function refreshHistory() {
  const history = await api("runs");
  $("#history").innerHTML =
    '<option value="">Choose a previous run…</option>' +
    history
      .map(
        (r) =>
          `<option value="${r.id}">${esc(r.title)} · ${esc(r.mode)} · ${esc(r.status)}</option>`,
      )
      .join("");
  const board = await api("scoreboard");
  $("#scoreboard").innerHTML = board.groups.length
    ? "<table><thead><tr><th>Source / strategy</th><th>Gate pass</th><th>Avg time</th><th>Tokens</th></tr></thead><tbody>" +
      board.groups
        .map(
          (g) =>
            `<tr><td>${esc(g.name.replaceAll("_", " "))}</td><td>${g.passed_gate} / ${g.runs}</td><td>${(g.elapsed_ms / g.runs / 1000).toFixed(1)}s</td><td>${g.tokens}</td></tr>`,
        )
        .join("") +
      "</tbody></table>"
    : '<p class="muted">Run different strategies to compare actual outcomes.</p>';
  return history;
}
$("#history").onchange = async (e) => {
  if (!e.target.value) return;
  if (busy) {
    $("#message").textContent =
      "Wait for the active run to finish before replaying another.";
    return;
  }
  try {
    clearResult();
    const r = await api("runs/" + e.target.value);
    $("#task").value = r.task_id;
    $("#mode").value = r.mode;
    $("#strategy").value = r.strategy;
    render(r);
    if (["queued", "running"].includes(r.status)) {
      locks(true);
      poll();
    }
  } catch (err) {
    $("#message").textContent = err.message;
  }
};
async function init() {
  try {
    tasks = await api("tasks");
    $("#task").innerHTML = tasks
      .map(
        (t) =>
          `<option value="${t.id}">${esc(t.ticket + " · " + t.title)}</option>`,
      )
      .join("");
    ticket(tasks[0].id);
    const s = await api("status");
    $("#connection").textContent = s.model_ready
      ? "LOCAL MODEL READY"
      : "MODEL OFFLINE · FIXTURES AVAILABLE";
    $("#led").className = s.model_ready ? "ready" : "";
    const history = await refreshHistory();
    const active = history.find((r) =>
      ["queued", "running"].includes(r.status),
    );
    if (active) {
      current = active;
      locks(true);
      poll();
    }
  } catch (e) {
    $("#message").textContent = e.message;
  }
}
init();
