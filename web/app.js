"use strict";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { mode: "purpose", tab: "facts", split: "heldout", data: null, health: null, reports: new Map(), busy: false, benchmark: null };
const modeNames = { full: "Full context", masked: "PII masking", purpose: "Minimera" };
const actionNames = { gather_evidence: "Gather shipment evidence", prepare_delivery_evidence: "Prepare delivery evidence", check_refund: "Verify the refund", manual_review: "Route to a human reviewer", await_review: "Await the current review", no_action: "No new seller response indicated" };
const evidenceNames = { tracking: "Shipment / tracking record", delivery_confirmation: "Independent delivery confirmation", destination_match: "Delivery destination match", refund_confirmation: "Confirmed refund record", payment_link: "Verified payment-to-dispute link", deadline: "Response deadline check", resolve_conflict: "Reconcile conflicting records" };

function n(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") element.className = value;
    else if (key === "click") element.addEventListener("click", value);
    else if (key === "value") element.value = value;
    else if (value === true) element.setAttribute(key, "");
    else if (value !== false && value != null) element.setAttribute(key, value);
  }
  element.append(...children.flat().filter(x => x != null));
  return element;
}
function display(value) { return value === null ? "Not available" : typeof value === "boolean" ? (value ? "Yes" : "No") : String(value); }
function factValue(fact) {
  if (fact.key === "reason" && fact.value === "MERCHANDISE_OR_SERVICE_NOT_RECEIVED") return "Item or service not received";
  if (["case_status", "stage", "payment_status", "refund_status", "tracking_status", "goods_type"].includes(fact.key) && typeof fact.value === "string") {
    return fact.value.toLowerCase().replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  }
  return display(fact.value);
}
function formatDate(value) { return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
function percent(value) { return `${Math.round(value * 100)}%`; }
function notice(message, success = false) { const box = $("#notice"); box.textContent = message; box.classList.toggle("success", success); box.hidden = !message; }
let toastTimer;
function toast(message) { $("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 4500); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const value = await response.json();
  if (!response.ok) {
    const error = new Error(value.error?.message || value.detail?.[0]?.msg || "The request could not be completed. Please retry.");
    error.code = value.error?.code;
    throw error;
  }
  return value;
}
function setBusy(value) {
  state.busy = value;
  $("#analyze").disabled = value;
  $("#compare").disabled = value;
  $("#case-select").disabled = value;
  $("#refresh-paypal").disabled = value;
  $$("[data-mode]").forEach(b => { b.disabled = value || !state.data?.projections[b.dataset.mode]; });
  syncFreshButtons();
}
function syncFreshButtons() {
  const ready = Boolean(state.health?.model.ready);
  $$(".fresh-run").forEach(button => {
    button.disabled = state.busy || !ready;
    button.textContent = ready ? "Run fresh ↻" : "Fresh inference offline";
    button.title = ready ? "Use the configured model for a new generation" : "Fresh inference is not connected on this deployment; recorded real runs remain available";
  });
}
function download(value, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = n("a", { href: url, download: name });
  document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function factRow(fact, decision, context = false) {
  const value = n("div", { class: "fact-value" }, factValue(fact));
  const label = n("div", { class: "fact-label" }, fact.label || fact.key.replaceAll("_", " "));
  if (!context && decision && decision !== "retain") label.append(n("span", { class: "fact-status" }, decision === "exclude" ? "stays local" : "masked"));
  const row = n("div", { class: `fact-row ${decision === "exclude" ? "excluded" : decision === "mask" ? "masked" : ""}`, "data-fact-id": fact.id }, n("span", { class: "fact-id" }, fact.id), n("div", {}, label, value));
  return row;
}

function renderContext() {
  if (!state.data) return;
  const { case: current, projections } = state.data;
  const projection = projections[state.mode];
  const metrics = projection.metrics;
  const decisions = new Map(projection.ledger.map(d => [d.id, d.decision]));
  const sourceOrder = [...current.facts].sort((a, b) => (a.sensitivity === "task") - (b.sensitivity === "task"));
  $("#source-facts").replaceChildren(...sourceOrder.map(f => factRow(f, decisions.get(f.id))));
  const originals = new Map(current.facts.map(f => [f.id, f]));
  $("#context-facts").replaceChildren(...projection.payload.facts.map(f => factRow({ ...f, label: originals.get(f.id)?.label }, "retain", true)));
  $("#source-count").textContent = `${metrics.source_fields} fields`;
  $("#sent-count").textContent = metrics.sent_fields;
  $("#reduction").textContent = metrics.excluded_fields ? `−${metrics.excluded_fields} fields` : metrics.masked_fields ? `${metrics.masked_fields} masked` : "Baseline";
  $("#context-caption").textContent = `${modeNames[state.mode]} · ${projection.policy_version}`;
  $("#context-footer").textContent = `${metrics.excluded_fields} excluded · ${metrics.masked_fields} masked · ${metrics.sensitive_fields_disclosed} unrelated values sent`;
  $("#protected-count").textContent = metrics.excluded_fields;
  $("#retained-count").textContent = `${metrics.task_fields_retained}/${metrics.task_fields_total}`;
  $("#context-json").textContent = JSON.stringify(projection.model_request, null, 2);
  $("#context-ledger").replaceChildren(...projection.ledger.map(d => n("div", { class: "decision-row" }, n("span", { class: "decision-tag" }, d.decision), n("strong", {}, `${d.id} · ${d.key}`), n("p", {}, d.reason))));
  $$("[data-mode]").forEach(b => { b.setAttribute("aria-pressed", b.dataset.mode === state.mode); b.disabled = !projections[b.dataset.mode] || state.busy; });
  renderContextTab();
  const saved = state.reports.get(`${current.id}:${state.mode}`);
  if (saved) renderAnswer(saved); else renderEmpty();
}
function renderContextTab() {
  for (const tab of ["facts", "json", "ledger"]) $("#context-" + tab).hidden = state.tab !== tab;
  $$("[data-context-tab]").forEach(b => b.setAttribute("aria-pressed", b.dataset.contextTab === state.tab));
}
function renderEmpty() {
  $("#answer-content").replaceChildren(n("div", { class: "answer-empty" }, n("div", { class: "document-icon", "aria-hidden": "true" }, n("span", {}, "✦")), n("h3", {}, "Less context. Let’s test it."), n("p", {}, "Run the same AI task with the selected facts. Inspect its recommendation, citations, and reply."), n("span", { class: "empty-note" }, state.data?.recorded_modes.includes(state.mode) ? "A real, recorded model run is ready to inspect." : "Fresh analysis uses the configured model.")));
}
function renderLoading(label = "Analyzing the selected context…") {
  const detail = state.health?.model.location === "local" ? "One generation at a time. Memory is monitored throughout." : "One request at a time. Inference runs with the configured provider.";
  $("#answer-content").replaceChildren(n("div", { class: "answer-empty", role: "status", "aria-live": "polite" }, n("span", { class: "spinner", "aria-hidden": "true" }), n("h3", {}, label), n("p", { class: "loading-copy" }, "Only the request shown in the middle panel is sent."), n("span", { class: "loading-detail" }, detail)));
}
function cite(id) {
  state.tab = "facts"; renderContextTab();
  const row = [...$$("#context-facts .fact-row")].find(r => r.dataset.factId === id);
  if (row) { row.scrollIntoView({ behavior: "smooth", block: "nearest" }); row.classList.add("highlight"); setTimeout(() => row.classList.remove("highlight"), 3000); }
}
function renderAnswer(report) {
  const result = report.result;
  const analysis = result.analysis;
  const source = report.delivery === "fresh" ? "Fresh model run" : "Recorded model run";
  if (result.request) $("#context-json").textContent = JSON.stringify(result.request, null, 2);
  const citations = n("div", { class: "citation-list", "aria-label": "Supporting fact references" }, ...analysis.citations.map(id => {
    const fact = state.data.case.facts.find(f => f.id === id);
    return n("button", { class: "citation", title: fact ? `${fact.label}: ${display(fact.value)}` : id, click: () => cite(id) }, `${id} ↗`);
  }));
  const textarea = n("textarea", { class: "draft-text", readonly: true, "aria-label": "AI-generated seller reply draft", value: analysis.reply_draft });
  const noReplyNeeded = ["no_action", "await_review"].includes(analysis.action);
  const needsReview = Boolean(report.review?.flags.length) || report.scores.action_correct === false || report.scores.required_citation_recall === 0 || report.scores.output_sensitive_matches > 0;
  const copy = n("button", { class: "text-button", disabled: needsReview || noReplyNeeded, click: async () => {
    try { await navigator.clipboard.writeText(analysis.reply_draft); toast("Draft copied. Review it before sending."); }
    catch { textarea.focus(); textarea.select(); toast("Draft selected. Copy it with your keyboard."); }
  } }, noReplyNeeded ? "No reply needed now" : needsReview ? "Review flagged draft" : "Copy ↗");
  const details = n("details", { class: "run-details" }, n("summary", {}, "Run provenance & verification"), n("p", {}, `Model: ${result.model.model} · ${result.model.location}`), n("p", {}, `Model manifest digest: ${result.model.digest || "Unavailable"}`), n("p", {}, result.model.identity_basis || "Provider-reported model identity."), n("p", {}, `Prompt: ${result.prompt_version} · Policy: ${report.projection.policy_version}`), n("p", {}, `Canonical JSON request SHA-256: ${result.request_sha256}`), n("p", {}, `Time: ${(result.duration_ms / 1000).toFixed(1)}s · Tokens: ${result.tokens.input ?? "?"} in / ${result.tokens.output ?? "?"} out`), n("p", {}, result.hash_encoding || "SHA-256 of the canonical JSON request record; authentication headers excluded."), n("p", {}, "These hashes do not attest to model behavior or prove deletion."));
  const children = [n("div", { class: "run-origin" }, n("span", { class: "tiny-dot" }), `${source} · ${formatDate(report.created_at)}`), n("div", { class: "recommendation" }, actionNames[analysis.action]), n("p", { class: "answer-rationale" }, analysis.rationale), citations];
  const flags = [...(report.review?.flags || [])];
  if (report.scores.action_correct === false) flags.push("The model’s action differs from this synthetic fixture’s reference label.");
  if (report.scores.required_citation_recall === 0) flags.push("None of this fixture’s decisive reference facts were cited. Valid fact IDs alone do not establish grounding.");
  if (report.scores.output_sensitive_matches > 0) flags.push(`Exact protected-value matches in this synthetic output: ${report.scores.output_sensitive_matches}.`);
  if (flags.length) children.push(n("details", { class: "validation-note" }, n("summary", {}, `Review checks · ${flags.length} to inspect`), n("ul", {}, ...flags.map(flag => n("li", {}, flag)))));
  children.push(n("div", { class: "draft-heading" }, n("span", { class: "mini-label" }, "SUGGESTED REPLY"), copy), textarea);
  if (analysis.missing_evidence.length) children.push(n("div", { class: "evidence-title" }, "Evidence to check"), n("ul", { class: "evidence-list" }, ...analysis.missing_evidence.map(e => n("li", {}, evidenceNames[e] || e))));
  children.push(n("div", { class: "answer-actions" }, n("button", { class: "button secondary", click: () => download(report, `minimera-${report.case_id}-${report.mode}.json`) }, "Export evidence ↓"), n("button", { class: "text-button fresh-run", disabled: state.busy || !state.health?.model.ready, click: () => runAnalysis(true) }, state.health?.model.ready ? "Run fresh ↻" : "Fresh inference offline")), details);
  $("#answer-content").replaceChildren(...children);
  syncFreshButtons();
}

async function loadCase(id) {
  notice("");
  $("#comparison").hidden = true;
  const data = await api(`/api/cases/${encodeURIComponent(id)}`);
  state.data = data;
  if (!data.projections[state.mode]) state.mode = "purpose";
  $("#case-story").textContent = data.case.story;
  const live = data.case.source.kind !== "synthetic";
  $("#case-origin").textContent = live ? "PayPal sandbox observation" : "Synthetic case";
  $("#case-origin").className = live ? "green-pill" : "neutral-pill";
  $("#case-split").textContent = live ? `Read ${formatDate(data.case.source.observed_at)}` : data.case.split === "heldout" ? "Held-out reporting set" : "Development set";
  $("#refresh-paypal").hidden = !live || !state.health?.paypal.configured;
  $("#source-footer").textContent = live ? "Normalized business facts. No customer profiles forwarded." : "Synthetic identifiers for safe testing.";
  $("#compare").disabled = live;
  renderContext();
}
async function runAnalysis(fresh = false) {
  if (state.busy || !state.data) return;
  setBusy(true); notice(""); renderLoading(fresh ? "Running a fresh model analysis…" : "Preparing the model analysis…");
  try {
    const report = await api("/api/analyze", { case_id: state.data.case.id, mode: state.mode, fresh });
    state.reports.set(`${report.case_id}:${report.mode}`, report);
    renderAnswer(report);
  } catch (error) {
    const previous = state.reports.get(`${state.data.case.id}:${state.mode}`);
    if (previous) renderAnswer(previous); else renderEmpty();
    notice(error.message);
  }
  finally { setBusy(false); if (state.data.case.source.kind !== "synthetic") $("#compare").disabled = true; await refreshHealth(); }
}

async function compare() {
  if (state.busy || !state.data || state.data.case.source.kind !== "synthetic") return;
  setBusy(true); notice(""); $("#comparison").hidden = false;
  const grid = $("#comparison-grid");
  grid.replaceChildren(n("p", { class: "evaluation-description", role: "status" }, "Comparing full, masked, and purpose-specific inputs sequentially…"));
  try {
    const reports = [];
    for (const mode of ["full", "masked", "purpose"]) {
      try {
        const report = await api("/api/analyze", { case_id: state.data.case.id, mode, fresh: false });
        reports.push(report); state.reports.set(`${report.case_id}:${report.mode}`, report);
      } catch (error) {
        reports.push({ mode, error, projection: state.data.projections[mode] });
      }
    }
    grid.replaceChildren(...reports.map(report => {
      const metrics = report.projection.metrics;
      if (report.error) {
        return n("article", { class: "compare-card compare-failed", "data-comparison-mode": report.mode },
          n("h3", {}, modeNames[report.mode]),
          n("div", { class: "run-origin" }, report.error.code === "RECORDED_MODEL_OUTPUT_FAILED" ? "Recorded validation failure" : "Analysis unavailable"),
          n("div", { class: "compare-stats" }, n("div", {}, n("strong", {}, String(metrics.sent_fields)), n("small", {}, "fields selected"))),
          n("div", { class: "recommendation" }, "No accepted model output"),
          n("p", {}, report.error.message),
          n("button", { class: "button secondary", click: () => { state.mode = report.mode; renderContext(); $("#workspace-view").scrollIntoView({ behavior: "smooth" }); } }, "Inspect this context ↗"),
          n("a", { class: "text-button", href: "#evaluation" }, "View the benchmark →"));
      }
      const analysis = report.result.analysis;
      const card = n("article", { class: `compare-card ${report.mode === "purpose" ? "featured" : ""}` }, n("h3", {}, modeNames[report.mode]), n("div", { class: "run-origin" }, report.delivery === "fresh" ? "Fresh model run" : "Recorded model run"), n("div", { class: "compare-stats" }, n("div", {}, n("strong", {}, String(metrics.sent_fields)), n("small", {}, "fields sent")), n("div", {}, n("strong", {}, String(metrics.sensitive_fields_disclosed)), n("small", {}, "unrelated values sent"))), n("div", { class: "recommendation" }, actionNames[analysis.action]), n("p", {}, analysis.rationale));
      if (report.scores.action_correct !== undefined) card.append(n("span", { class: report.scores.action_correct ? "green-pill" : "amber-pill" }, report.scores.action_correct ? "Matches reference action" : "Differs from reference action"));
      card.append(n("p", {}, `Missing-evidence agreement: ${report.scores.missing_f1 === undefined ? "Not labelled" : percent(report.scores.missing_f1)}`), n("button", { class: "button secondary", click: () => { state.mode = report.mode; renderContext(); $("#workspace-view").scrollIntoView({ behavior: "smooth" }); } }, "Inspect this run ↗"));
      return card;
    }));
    const selected = state.reports.get(`${state.data.case.id}:${state.mode}`);
    if (selected) renderAnswer(selected); else renderEmpty();
    $("#comparison").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { grid.replaceChildren(n("p", { class: "compare-warning" }, error.message)); }
  finally { setBusy(false); await refreshHealth(); }
}

async function refreshHealth() {
  try {
    state.health = await api("/api/health");
    syncFreshButtons();
    const health = state.health;
    const text = health.paypal.last_refresh_error ? "PayPal refresh needs attention" : health.paypal.observation_available ? (health.paypal.configured ? "PayPal sandbox connected" : "PayPal sandbox observation") : "Synthetic evaluation workspace";
    $("#connection").replaceChildren(n("span", { class: `tiny-dot${health.paypal.last_refresh_error ? " amber" : ""}` }), text);
    $("#resource-state").textContent = health.memory.available_mib == null ? "One model request at a time" : `${(health.memory.available_mib / 1024).toFixed(1)} GiB RAM available · one request at a time`;
  } catch { $("#connection").textContent = "Connection unavailable"; }
}

function renderEvaluation() {
  const report = state.benchmark;
  if (!report || report.status === "not_run") {
    $("#evaluation-content").replaceChildren(n("div", { class: "panel method-card" }, n("h2", {}, "No benchmark results yet."), n("p", {}, "The interface never substitutes invented scores. Run the evaluation command in the repository to record actual model outputs.")));
    $("#benchmark-status").textContent = "Not run"; $("#download-benchmark").hidden = true; return;
  }
  $("#download-benchmark").hidden = false;
  $("#benchmark-status").textContent = `${report.status === "complete" ? "Completed" : report.status} · ${report.runs.length}/90 runs`;
  const rows = report.summary.filter(s => s.split === state.split);
  const purpose = rows.find(r => r.mode === "purpose");
  const baseline = rows.find(r => r.mode === "full");
  if (!purpose || !baseline) {
    $("#evaluation-content").replaceChildren(n("div", { class: "panel method-card" }, n("h2", {}, "This partition has not finished yet."), n("p", {}, "Completed runs remain available in the exported report. Select the development partition to inspect current progress."))); return;
  }
  const metric = (title, value, description) => n("article", { class: "evaluation-card" }, n("span", { class: "mini-label" }, title), n("div", { class: "metric-value" }, value), n("p", {}, description));
  const cards = n("div", { class: "evaluation-cards" }, metric("UNRELATED FIELDS SENT", `${baseline.mean_sensitive_fields_sent} → ${purpose.mean_sensitive_fields_sent}`, "Average input fields outside this task: full context → Minimera."), metric("MINIMERA ACTION ACCURACY", `${purpose.action_correct}/${purpose.attempts}`, `Compared with ${baseline.action_correct}/${baseline.attempts} for full context on the same fixtures.`), metric("GENERATION VALIDITY", `${purpose.valid_outputs}/${purpose.attempts}`, "Minimera outputs that passed schema and fact-ID validation."));
  const table = n("table", {}, n("thead", {}, n("tr", {}, ...["Context mode", "Unrelated fields sent", "Selected data size", "Action accuracy", "Missing evidence F1", "Valid outputs"].map(x => n("th", { scope: "col" }, x)))));
  const tbody = n("tbody");
  for (const row of rows) tbody.append(n("tr", { class: row.mode === "purpose" ? "selected" : "" }, n("td", {}, modeNames[row.mode]), n("td", {}, String(row.mean_sensitive_fields_sent), n("small", {}, "average field values")), n("td", {}, `${row.mean_context_bytes.toLocaleString()} B`, n("small", {}, "policy projection")), n("td", {}, `${row.action_correct}/${row.attempts} · ${percent(row.action_accuracy)}`, n("progress", { max: "100", value: row.action_accuracy * 100, "aria-label": `${modeNames[row.mode]} action accuracy` })), n("td", {}, percent(row.missing_f1)), n("td", {}, `${row.valid_outputs}/${row.attempts}`)));
  table.append(tbody);
  const reused = report.workflow_check?.protocol?.partition?.reporting_set_reused === false
    ? " The reporting variants were frozen before model evaluation and were not used to tune this prompt. They are developer-authored, not independently adjudicated or blinded."
    : report.experiment_id ? " This experiment reuses the fixed reporting fixtures; they are not a new unseen test set." : "";
  const description = n("p", { class: "evaluation-description" }, `Model: ${report.model}. Fixed prompt ${report.prompt_version}; fixed policy ${report.policy_version}. Each mode receives the same task and output schema. Only the context changes. This is a controlled demonstration, not an estimate of real-world dispute accuracy.${reused}`);
  const workflow = report.workflow_check ? n("div", { class: "method-note" }, n("strong", {}, report.workflow_check.passes_fixture_gates ? "Fixed fixture checks passed. " : "Workflow needs improvement. "), report.workflow_check.interpretation, n("p", {}, "Project thresholds: 90% held-out action accuracy, 80% missing-evidence F1, no action regression, all candidate generations valid, and no unrelated fields sent. These are engineering choices, not regulatory standards.")) : null;
  const title = n("div", { class: "section-title" }, n("h2", {}, "Inspect every result"), n("span", { class: "neutral-pill" }, "Minimera · selected partition"));
  const runTable = n("table", { class: "run-table" }, n("thead", {}, n("tr", {}, ...["Case", "Reference action", "Model action", "Evidence agreement", "Result"].map(x => n("th", { scope: "col" }, x)))));
  const body = n("tbody");
  for (const run of report.runs.filter(r => r.mode === "purpose" && (state.split === "all" || r.split === state.split))) {
    body.append(n("tr", {}, n("td", {}, n("button", { click: async () => { location.hash = "workspace"; $("#case-select").value = run.case_id; await loadCase(run.case_id); await runAnalysis(false); } }, run.case_id)), n("td", {}, actionNames[run.reference_label?.action] || "See report"), n("td", {}, run.status === "ok" ? actionNames[run.result.analysis.action] : run.error), n("td", {}, run.status === "ok" ? percent(run.scores.missing_f1) : "—"), n("td", { class: run.scores?.action_correct ? "pass-text" : "fail-text" }, run.scores?.action_correct ? "Match" : "Review")));
  }
  runTable.append(body);
  $("#evaluation-content").replaceChildren(cards, n("div", { class: "table-wrap" }, table), description, ...(workflow ? [workflow] : []), title, n("div", { class: "table-wrap" }, runTable));
}
async function showView() {
  const requested = location.hash.slice(1);
  const view = ["workspace", "evaluation", "method"].includes(requested) ? requested : "workspace";
  for (const name of ["workspace", "evaluation", "method"]) $(`#${name}-view`).hidden = name !== view;
  $$("[data-view]").forEach(a => a.classList.toggle("active", a.dataset.view === view));
  $("#breadcrumb-current").textContent = { workspace: "Case workspace", evaluation: "Evaluation", method: "How it works" }[view];
  if (view === "evaluation") {
    try { state.benchmark = await api("/api/evaluation"); renderEvaluation(); }
    catch (error) { $("#evaluation-content").replaceChildren(n("p", { class: "notice" }, error.message)); }
  }
}

async function init() {
  $$("[data-mode]").forEach(b => b.addEventListener("click", () => { state.mode = b.dataset.mode; notice(""); renderContext(); }));
  $$("[data-context-tab]").forEach(b => b.addEventListener("click", () => { state.tab = b.dataset.contextTab; renderContextTab(); }));
  $$("[data-split]").forEach(b => b.addEventListener("click", () => { state.split = b.dataset.split; $$("[data-split]").forEach(x => x.setAttribute("aria-pressed", x === b)); renderEvaluation(); }));
  $("#analyze").addEventListener("click", () => runAnalysis(false));
  $("#compare").addEventListener("click", compare);
  $("#close-comparison").addEventListener("click", () => { $("#comparison").hidden = true; });
  $("#case-select").addEventListener("change", async e => { try { await loadCase(e.target.value); } catch (error) { notice(error.message); } });
  $("#refresh-paypal").addEventListener("click", async () => {
    setBusy(true); notice("");
    try { await api("/api/paypal/refresh", {}); await loadCase("paypal-sandbox"); notice("PayPal sandbox read refreshed. Its current state and timestamp are shown above.", true); }
    catch (error) { notice(error.message); }
    finally { setBusy(false); $("#compare").disabled = true; await refreshHealth(); }
  });
  window.addEventListener("hashchange", showView);
  try {
    const [catalog] = await Promise.all([api("/api/cases"), refreshHealth()]);
    const select = $("#case-select"); select.replaceChildren();
    for (const [split, label] of [["live", "PayPal sandbox"], ["development", "Development cases"], ["heldout", "Held-out cases"]]) {
      const group = n("optgroup", { label });
      for (const c of catalog.cases.filter(c => c.split === split)) group.append(n("option", { value: c.id }, `${c.id === "paypal-sandbox" ? "PayPal" : c.id} · ${c.label}`));
      if (group.children.length) select.append(group);
    }
    select.value = catalog.cases.some(c => c.id === "NTK-003") ? "NTK-003" : catalog.cases[0].id;
    await loadCase(select.value); await showView();
  } catch (error) { notice(error.message); $("#analyze").disabled = true; }
}
init();
