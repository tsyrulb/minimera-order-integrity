// The portable hosted adapter. Policy parity is checked against the Python core.
let liveCase = SEED;
let lastRefresh = 0;
let inferenceBusy = false;
const recentRequests = new Map();
const allowed = new Set(ALLOWED_KEYS);
const modes = new Set(["full", "masked", "purpose"]);
export function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
  return JSON.stringify(value);
}
async function digest(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value)));
  return [...new Uint8Array(bytes)].map(x => x.toString(16).padStart(2, "0")).join("");
}
export async function projectCase(current, mode) {
  if (!modes.has(mode)) throw new Error("MODE_INVALID");
  if (mode !== "purpose" && current.source.kind !== "synthetic") throw new Error("SYNTHETIC_ONLY");
  const facts = [], ledger = [];
  for (const original of current.facts) {
    const fact = { ...original };
    const included = allowed.has(fact.key) && fact.sensitivity === "task";
    let decision = "retain", reason = "Included in this experimental baseline.";
    if (mode === "purpose" && !included) { decision = "exclude"; reason = "Outside the declared item-not-received purpose."; }
    else if (mode === "masked" && fact.sensitivity === "personal") { fact.value = "[MASKED]"; decision = "mask"; reason = "Known personal field; value replaced locally."; }
    else if (mode === "purpose") reason = "Allowlisted business fact needed to review the dispute.";
    if (decision !== "exclude") facts.push({ id: fact.id, key: fact.key, value: fact.value, source: fact.source });
    ledger.push({ id: fact.id, key: fact.key, decision, reason });
  }
  const payload = { purpose: PURPOSE, facts };
  const wire = canonical(payload);
  const sensitive = current.facts.filter(f => ["personal", "commercial", "untrusted"].includes(f.sensitivity));
  const rawIds = new Set(ledger.filter(d => d.decision === "retain").map(d => d.id));
  const disclosed = sensitive.filter(f => rawIds.has(f.id)).map(f => f.id);
  const taskIds = current.facts.filter(f => f.sensitivity === "task").map(f => f.id);
  const retainedIds = new Set(facts.map(f => f.id));
  const modelWire = PROMPT_VERSION === "inr-assistant/2.1.0"
    ? canonical({ purpose: payload.purpose, facts: facts.map(f => ({ id: f.id, key: f.key, value: f.value, record_origin: f.source })) })
    : wire;
  const body = structuredClone(REQUEST_TEMPLATE);
  if (body.operation === "Converse") body.body.messages[0].content[0].text = modelWire;
  else if (body.input) body.input[1].content = modelWire;
  else body.messages[1].content = modelWire;
  return { mode, policy_version: POLICY_VERSION, payload, context_sha256: await digest(payload), ledger,
    metrics: { source_fields: current.facts.length, sent_fields: facts.length,
      excluded_fields: ledger.filter(d => d.decision === "exclude").length,
      masked_fields: ledger.filter(d => d.decision === "mask").length,
      sensitive_fields_disclosed: disclosed.length, sensitive_field_ids: disclosed, sensitive_fields_total: sensitive.length,
      personal_value_matches_in_input: sensitive.filter(f => f.sensitivity === "personal" && typeof f.value === "string" && f.value.length >= 6 && wire.includes(f.value)).map(f => f.id),
      task_fields_retained: taskIds.filter(id => retainedIds.has(id)).length, task_fields_total: taskIds.length,
      context_bytes: new TextEncoder().encode(wire).length }, model_request: body };
}
function publicCase(current) { const { expected, ...rest } = current; return rest; }
function allCases() { return liveCase ? [...DATASET.cases, liveCase] : DATASET.cases; }
function error(code, message, status = 503) { return json({ error: { code, message } }, status); }
const security = { "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "permissions-policy": "camera=(), microphone=(), geolocation=()" };
function json(value, status = 200, extra = {}) { return new Response(JSON.stringify(value), { status, headers: { ...security, "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra } }); }
function review(current, analysis) {
  const values = Object.fromEntries(current.facts.filter(f => f.sensitivity === "task").map(f => [f.key, f.value]));
  const reply = analysis.reply_draft.toLowerCase(), flags = [];
  if (["RESOLVED", "CLOSED"].includes(values.case_status) && analysis.action !== "no_action") flags.push("The case is already resolved; the model proposes a new seller task.");
  if (["WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW"].includes(values.case_status) && analysis.action !== "await_review") flags.push("The case is waiting for another party or review; the model proposes a new seller task.");
  if (/(?:provide|send|share|submit)[^.\n]{0,100}(?:tracking|proof of delivery|shipment evidence)/.test(reply)) flags.push("The draft asks the buyer for shipment evidence the seller should gather.");
  if (/paypal.?s (?:guidelines|polic)|seller protection|guarantee.{0,30}(?:refund|win)/.test(reply)) flags.push("The draft refers to a policy or outcome not established by the supplied facts.");
  if (/(?:within the next|within \d+ (?:day|hour)|by tomorrow)/.test(reply)) flags.push("The draft introduces a response timeframe not grounded in a cited deadline.");
  if (values.refund_status !== "COMPLETED" && /(?:refund has been|we have refunded|refund is (?:completed|processed)|refund was (?:completed|processed))/.test(reply)) flags.push("Refund wording needs review: the case has no verified completed refund.");
  if (analysis.action === "prepare_delivery_evidence" && !(values.tracking_status === "DELIVERED" && values.tracking_source === "carrier" && values.destination_match === true && values.proof_of_delivery_available === true)) flags.push("The recommendation lacks the workflow's required carrier delivery facts.");
  if (analysis.action === "await_review" && values.case_status === "WAITING_FOR_SELLER_RESPONSE") flags.push("PayPal is waiting for the seller; the recommendation incorrectly waits for another party.");
  return { version: "inr-draft-checks/1.0.2", flags, draft_status: flags.length ? "needs_review" : "unapproved", human_review_required: true, scope: "Pattern and explicit precondition checks only; passing is not a guarantee of factual correctness." };
}
function findRun(current, mode, projection) {
  const candidates = [...BENCHMARK.runs, ...(typeof EXTRA_RUNS === "undefined" ? [] : EXTRA_RUNS)];
  return candidates.find(r => r.status === "ok" && r.case_id === current.id && r.mode === mode && r.projection.context_sha256 === projection.context_sha256 && canonical(r.result.request) === canonical(projection.model_request));
}
function sandboxConfigured(env) { return ["PAYPAL_SANDBOX_CLIENT_ID", "PAYPAL_SANDBOX_CLIENT_SECRET", "NTK_PAYPAL_ORDER_ID", "NTK_PAYPAL_CAPTURE_ID", "NTK_PAYPAL_DISPUTE_ID"].every(k => Boolean(env[k])); }
async function boundedJSON(url, init = {}) {
  const response = await fetch(url, { ...init, redirect: "error", signal: AbortSignal.timeout(40000) });
  if (!response.ok) throw new Error("UPSTREAM_FAILURE");
  const reader = response.body.getReader(), chunks = []; let total = 0;
  while (true) { const { done, value } = await reader.read(); if (done) break; total += value.length; if (total > 2000000) { await reader.cancel(); throw new Error("RESPONSE_LIMIT"); } chunks.push(value); }
  const combined = new Uint8Array(total); let offset = 0;
  for (const chunk of chunks) { combined.set(chunk, offset); offset += chunk.length; }
  return JSON.parse(new TextDecoder().decode(combined));
}
const enumValue = value => typeof value === "string" && /^[A-Z][A-Z0-9_]{0,79}$/.test(value) ? value : null;
async function refreshSandbox(env) {
  if (!sandboxConfigured(env)) return error("PAYPAL_NOT_CONFIGURED", "This deployment has a recorded sandbox observation. A merchant can configure a read-only live connection.");
  if (Date.now() - lastRefresh < 30000) return error("REFRESH_COOLDOWN", "Wait 30 seconds before refreshing PayPal again.", 429);
  lastRefresh = Date.now();
  const [orderId, captureId, disputeId] = [env.NTK_PAYPAL_ORDER_ID, env.NTK_PAYPAL_CAPTURE_ID, env.NTK_PAYPAL_DISPUTE_ID];
  if (![orderId, captureId, disputeId].every(id => /^[A-Z0-9-]{1,80}$/.test(id))) return error("PAYPAL_CONFIG", "Sandbox resource configuration is invalid.");
  try {
    const token = await boundedJSON("https://api-m.sandbox.paypal.com/v1/oauth2/token", { method: "POST", headers: { Authorization: "Basic " + btoa(env.PAYPAL_SANDBOX_CLIENT_ID + ":" + env.PAYPAL_SANDBOX_CLIENT_SECRET), "Content-Type": "application/x-www-form-urlencoded" }, body: "grant_type=client_credentials" });
    if (typeof token.access_token !== "string" || /\s/.test(token.access_token)) throw new Error("TOKEN_INVALID");
    const headers = { Authorization: "Bearer " + token.access_token };
    const order = await boundedJSON("https://api-m.sandbox.paypal.com/v2/checkout/orders/" + orderId, { headers });
    const dispute = await boundedJSON("https://api-m.sandbox.paypal.com/v1/customer/disputes/" + disputeId, { headers });
    const units = order.purchase_units || [];
    const captures = units.flatMap(u => u.payments?.captures || []).filter(c => c.id === captureId);
    const linked = dispute.disputed_transactions?.filter(t => t.seller_transaction_id === captureId) || [];
    if (order.id !== orderId || dispute.dispute_id !== disputeId || units.length !== 1 || units[0].reference_id !== "need-to-know-sandbox" || captures.length !== 1 || linked.length !== 1 || captures[0].amount?.value !== "1.00" || captures[0].amount?.currency_code !== "USD" || dispute.dispute_amount?.value !== "1.00" || dispute.dispute_amount?.currency_code !== "USD") throw new Error("LINK_FAILED");
    const fingerprint = (await digest([orderId, captureId, disputeId])).slice(0, 16);
    const previous = fingerprint === SEED?.source.resource_fingerprint && SEED.facts.some(f => f.key === "payment_previously_completed" && f.value === true);
    const dueRaw = dispute.seller_response_due_date;
    const due = typeof dueRaw === "string" && dueRaw.length <= 35 && !Number.isNaN(Date.parse(dueRaw)) ? new Date(dueRaw).toISOString().replace(/\.(\d{3})Z$/, (_, ms) => ms === "000" ? "+00:00" : "." + ms + "000+00:00") : null;
    const rows = [
      ["case_status", "Case status", enumValue(dispute.status), "paypal"], ["reason", "Reason", enumValue(dispute.reason), "paypal"],
      ["stage", "Stage", enumValue(dispute.dispute_life_cycle_stage), "paypal"], ["amount", "Disputed amount", "1.00", "paypal"],
      ["currency", "Currency", "USD", "paypal"], ["payment_status", "Current capture status", enumValue(captures[0].status), "paypal"],
      ["payment_previously_completed", "Completion observed before dispute", previous ? true : null, "merchant"], ["verified_capture_link", "Capture linked to dispute", true, "paypal"],
      ["refund_status", "Confirmed refund status", null, "paypal"], ["tracking_status", "Carrier tracking status", null, "carrier"],
      ["tracking_source", "Tracking source", "none", "merchant"], ["tracking_number_available", "Tracking available", null, "merchant"],
      ["proof_of_delivery_available", "Delivery proof available", null, "merchant"], ["destination_match", "Delivery destination matches", null, "merchant"],
      ["goods_type", "Goods type", "PHYSICAL", "merchant"], ["respond_by", "Seller response deadline", due, "paypal"],
      ["deadline_passed", "Response deadline passed", due ? Date.parse(due) < Date.now() : null, "merchant"]
    ];
    liveCase = { id: "paypal-sandbox", label: "Live PayPal sandbox dispute", split: "live", story: "A real read of our synthetic USD 1.00 sandbox dispute. No goods were shipped. Carrier facts are unavailable, not assumed false.",
      source: { kind: "paypal-sandbox", label: "PayPal sandbox · live read", observed_at: new Date().toISOString(), capture_link_verified: true, resource_fingerprint: fingerprint,
        completion_basis: previous ? "Unsigned local observation from before the dispute" : "Not established by a prior record", scope: "PayPal business fields only; no buyer profiles, messages or attachments forwarded." },
      facts: rows.map(([key, label, value, source], i) => ({ id: "F" + String(i + 1).padStart(2, "0"), key, label, value, source, sensitivity: "task" })) };
    return json({ case: publicCase(liveCase) });
  } catch { return error("PAYPAL_READ_FAILED", "PayPal sandbox could not be read. The recorded observation remains labelled with its timestamp."); }
}
async function freshAnalysis(current, mode, projection, env) {
  if (REQUEST_TEMPLATE.operation === "Converse") return error("BEDROCK_REPLAY_ONLY", "This portable demo replays recorded Bedrock results. Run the Python server with your AWS credential chain for fresh inference.");
  if (!env.NTK_OPENAI_API_KEY || env.NTK_ENABLE_PUBLIC_FRESH !== "true") return error("MODEL_UNAVAILABLE", "This public preview replays real model runs. Fresh inference needs an operator-configured cloud model; the repository also supports local Ollama.");
  if (inferenceBusy) return error("MODEL_BUSY", "Another analysis is running. Please retry after it finishes.", 429);
  inferenceBusy = true;
  try {
    const started = Date.now();
    const body = { model: env.NTK_CLOUD_MODEL || "gpt-4.1-mini-2025-04-14", input: [{ role: "system", content: REQUEST_TEMPLATE.messages[0].content }, { role: "user", content: canonical(projection.payload) }], temperature: 0, max_output_tokens: 512, store: false, text: { format: { type: "json_schema", name: "dispute_analysis", schema: ANALYSIS_SCHEMA, strict: true } } };
    const upstream = await boundedJSON("https://api.openai.com/v1/responses", { method: "POST", headers: { Authorization: "Bearer " + env.NTK_OPENAI_API_KEY, "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (upstream.status !== "completed") throw new Error("INCOMPLETE");
    const analysis = JSON.parse((upstream.output || []).flatMap(x => x.content || []).filter(c => c.type === "output_text").map(c => c.text).join(""));
    const fields = ["action", "missing_evidence", "citations", "rationale", "reply_draft"];
    if (Object.keys(analysis).length !== fields.length || fields.some(k => !(k in analysis)) || !ANALYSIS_SCHEMA.properties.action.enum.includes(analysis.action) || !Array.isArray(analysis.citations) || analysis.citations.length < 1 || analysis.citations.length > 4 || !analysis.citations.every(id => projection.payload.facts.some(f => f.id === id)) || !Array.isArray(analysis.missing_evidence) || !analysis.missing_evidence.every(e => ANALYSIS_SCHEMA.properties.missing_evidence.items.enum.includes(e)) || typeof analysis.rationale !== "string" || analysis.rationale.length < 10 || analysis.rationale.length > 700 || typeof analysis.reply_draft !== "string" || analysis.reply_draft.length < 10 || analysis.reply_draft.length > 900) throw new Error("VALIDATION_FAILED");
    const scores = { citation_ids_valid: true, output_sensitive_field_ids: [], output_sensitive_matches: 0 };
    if (current.expected) {
      const wanted = new Set(current.expected.missing_evidence), got = new Set(analysis.missing_evidence);
      const shared = [...wanted].filter(x => got.has(x)).length;
      const precision = got.size ? shared / got.size : wanted.size ? 0 : 1, recall = wanted.size ? shared / wanted.size : 1;
      Object.assign(scores, { action_correct: analysis.action === current.expected.action, missing_exact: canonical([...wanted].sort()) === canonical([...got].sort()), missing_precision: precision, missing_recall: recall, missing_f1: precision + recall ? 2 * precision * recall / (precision + recall) : 0, required_citation_recall: current.expected.required_citations.filter(id => analysis.citations.includes(id)).length / current.expected.required_citations.length });
    }
    scores.output_sensitive_field_ids = current.facts.filter(f => ["personal", "commercial"].includes(f.sensitivity) && typeof f.value === "string" && f.value.length >= 5 && canonical(analysis).toLowerCase().includes(f.value.toLowerCase())).map(f => f.id);
    scores.output_sensitive_matches = scores.output_sensitive_field_ids.length;
    const result = { analysis, model: { model: body.model, digest: null, location: "OpenAI API", identity_basis: "Provider model snapshot ID; no cryptographic model digest available" }, prompt_version: PROMPT_VERSION, request_sha256: await digest(body), request: body, settings: { temperature: 0, max_output_tokens: 512, store: false }, tokens: { input: upstream.usage?.input_tokens, output: upstream.usage?.output_tokens }, duration_ms: Date.now() - started, memory_after: null };
    return json({ schema_version: "ntk-evidence/1.0.0", status: "ok", report_id: await digest({ request: result.request_sha256, at: Date.now() }), case_id: current.id, case_label: current.label, split: current.split, mode, source: current.source, created_at: new Date().toISOString(), dataset_sha256: DATASET_HASH, projection, result, scores, review: review(current, analysis), delivery: "fresh", ...(current.expected ? { reference_label: current.expected } : {}), limitations: ["Hashes identify payloads; they are not signatures or proof of provider behavior.", "Fixed synthetic labels and narrow checks do not establish general quality, anonymity or legal compliance.", "This is a draft. No evidence is submitted and no money is moved."] });
  } catch { return error("MODEL_OUTPUT_FAILED", "The cloud model did not return a valid response with in-context fact references. No draft was accepted.", 502); }
  finally { inferenceBusy = false; }
}

export default {
  async fetch(request, env = {}) {
    const url = new URL(request.url), path = url.pathname;
    try {
      if (request.method === "GET" && ASSETS[path]) return new Response(ASSETS[path].body, { headers: { ...security, "content-type": ASSETS[path].type, "cache-control": "no-cache" } });
      if (request.method === "GET" && path === "/api/health") return json({ status: "ok", model: { ready: Boolean(REQUEST_TEMPLATE.operation !== "Converse" && env.NTK_OPENAI_API_KEY && env.NTK_ENABLE_PUBLIC_FRESH === "true"), model: REQUEST_TEMPLATE.modelId || env.NTK_CLOUD_MODEL || REQUEST_TEMPLATE.model, digest: null, location: REQUEST_TEMPLATE.operation === "Converse" ? "Amazon Bedrock · recorded results" : "hosted; recorded baseline available" }, memory: { available_mib: null }, paypal: { configured: sandboxConfigured(env), observation_available: Boolean(liveCase), last_refresh_error: null }, policy_version: POLICY_VERSION, prompt_version: PROMPT_VERSION, dataset_sha256: DATASET_HASH, settings: OPTIONS });
      if (request.method === "GET" && path === "/api/cases") return json({ cases: allCases().map(c => { const { facts, ...rest } = publicCase(c); return rest; }), modes: MODES, purpose: PURPOSE });
      if (request.method === "GET" && path.startsWith("/api/cases/")) {
        const current = allCases().find(c => c.id === path.slice(11));
        if (!current) return error("CASE_NOT_FOUND", "Choose one of the predefined demo cases.", 404);
        const selected = current.source.kind === "synthetic" ? [...modes] : ["purpose"], projections = {};
        for (const mode of selected) projections[mode] = await projectCase(current, mode);
        return json({ case: publicCase(current), projections, recorded_modes: selected.filter(m => findRun(current, m, projections[m])) });
      }
      if (request.method === "GET" && path === "/api/evaluation") return json(BENCHMARK);
      if (request.method === "GET" && path === "/api/evaluation/download") return json(BENCHMARK, 200, { "content-disposition": 'attachment; filename="minimera-benchmark.json"' });
      if (request.method === "GET" && path === "/api/methodology") return new Response(METHODOLOGY, { headers: { ...security, "content-type": "text/plain; charset=utf-8" } });
      if (request.method !== "POST") return error("NOT_FOUND", "Not found.", 404);
      if (request.headers.get("origin") && request.headers.get("origin") !== url.origin) return error("ORIGIN_REFUSED", "Use this app from its own page.", 403);
      if (path !== "/api/analyze" && path !== "/api/paypal/refresh") return error("NOT_FOUND", "Not found.", 404);
      const reader = request.body?.getReader(); let raw = "", size = 0;
      if (reader) { const decoder = new TextDecoder(); while (true) { const { done, value } = await reader.read(); if (done) break; size += value.length; if (size > 2048) { await reader.cancel(); return error("BODY_TOO_LARGE", "Choose a predefined demo case.", 413); } raw += decoder.decode(value, { stream: true }); } raw += decoder.decode(); }
      let body; try { body = JSON.parse(raw || "{}"); } catch { return error("INVALID_JSON", "Choose a predefined demo case.", 400); }
      if (path === "/api/paypal/refresh") return await refreshSandbox(env);
      if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).some(k => !["case_id", "mode", "fresh"].includes(k)) || typeof body.case_id !== "string" || (body.mode !== undefined && !modes.has(body.mode)) || (body.fresh !== undefined && typeof body.fresh !== "boolean")) return error("INVALID_REQUEST", "Use a predefined case and context mode.", 422);
      const current = allCases().find(c => c.id === body.case_id), mode = body.mode || "purpose";
      if (!current) return error("CASE_NOT_FOUND", "Choose one of the available demo cases.", 404);
      if (current.source.kind !== "synthetic" && mode !== "purpose") return error("SYNTHETIC_ONLY", "Baseline comparisons use synthetic cases only.", 400);
      const projection = await projectCase(current, mode);
      if (!body.fresh) {
        const run = findRun(current, mode, projection);
        if (run) return json({ ...run, review: review(current, run.result.analysis), delivery: "recorded" });
        const failed = BENCHMARK.runs.find(r => r.status === "error" && r.case_id === current.id && r.mode === mode && r.projection.context_sha256 === projection.context_sha256 && r.result?.request && canonical(r.result.request) === canonical(projection.model_request));
        if (failed) return error("RECORDED_MODEL_OUTPUT_FAILED", "This recorded generation failed validation. Its original response is in the exported benchmark; no new generation was requested.", 502);
      }
      const now = Date.now(), ip = request.headers.get("cf-connecting-ip") || "shared";
      if (recentRequests.size > 1000) recentRequests.clear();
      const recent = (recentRequests.get(ip) || []).filter(t => t > now - 60000);
      if (recent.length >= 2) return error("RATE_LIMIT", "Wait a minute before another fresh generation.", 429);
      recentRequests.set(ip, [...recent, now]);
      return await freshAnalysis(current, mode, projection, env);
    } catch { return error("REQUEST_FAILED", "The request could not be completed. Please retry.", 500); }
  }
};
