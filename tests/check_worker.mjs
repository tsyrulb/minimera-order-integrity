import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

// The generated Worker has no relative imports. Loading its source as ESM
// keeps this check independent of the ignored hosting checkout/package.json.
const sourceUrl = "data:text/javascript;base64," + readFileSync(new URL("../site/worker/index.js", import.meta.url)).toString("base64");
const { default: worker, projectCase } = await import(sourceUrl);

const source = "import json,sys; from ntk.config import ModelSettings; from ntk.dataset import ROOT,load_dataset; from ntk.policy import project; from ntk.model_requests import request_body; from ntk.recorded import recorded_model,recorded_dataset; e=sys.argv[1]; p=json.loads((ROOT/'reports'/'experiments'/e/'protocol.json').read_text()) if e else {}; d,_=load_dataset(recorded_dataset(p)); config=recorded_model(p) if e else ModelSettings(); print(json.dumps([{'case':c,'mode':m,'expected':project(c,m),'request':request_body(project(c,m),config)} for c in d['cases'] for m in ['full','masked','purpose']]))";
let generated;
try { generated = execFileSync(process.env.NTK_TEST_PYTHON || "python3", ["-c", source, process.argv[2] || ""], { encoding: "utf8", maxBuffer: 4000000 }); }
catch { throw new Error("Vector generation could not start. Run this local parity check with subprocess access; fixture contents are not printed."); }
const vectors = JSON.parse(generated);
for (const vector of vectors) {
  const result = await projectCase(vector.case, vector.mode);
  assert.deepEqual(result.model_request, vector.request, `${vector.case.id}/${vector.mode} request`);
  delete result.model_request;
  assert.deepEqual(result, vector.expected, `${vector.case.id}/${vector.mode}`);
}
const call = (path, body, headers = {}) => worker.fetch(new Request("https://example.test" + path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) }));
const response = await call("/api/cases/NTK-001");
assert.equal(response.status, 200);
const current = await response.json();
assert.equal(current.case.expected, undefined);
assert.equal(current.projections.purpose.metrics.sensitive_fields_disclosed, 0);
assert.equal((await call("/api/analyze", { case_id: "NTK-001", provider_url: "http://169.254.169.254" })).status, 422);
assert.equal((await call("/api/analyze", { case_id: "NTK-001" }, { Origin: "https://unrelated.example" })).status, 403);
assert.equal((await call("/api/paypal/refund", {})).status, 404);
assert.equal((await call("/api/analyze", { case_id: "NTK-001", extra: "x".repeat(2200) })).status, 413);
const benchmark = await (await call("/api/evaluation")).json();
const valid = benchmark.runs.find(r => r.mode === "purpose" && r.status === "ok");
assert.ok(valid, "A recorded purpose result is required to test replay");
const result = await call("/api/analyze", { case_id: valid.case_id, mode: "purpose", fresh: false });
assert.equal(result.status, 200);
const run = await result.json();
assert.equal(run.delivery, "recorded");
assert.equal(run.review.human_review_required, true);
if (process.argv[2] === "gpt-oss120b-routing-v21-20261105") {
  const paypal = await call("/api/analyze", { case_id: "paypal-sandbox", mode: "purpose", fresh: false });
  assert.equal(paypal.status, 200);
  assert.equal((await paypal.json()).delivery, "recorded");
  assert.equal((await call("/api/analyze", { case_id: "paypal-sandbox", mode: "full" })).status, 400);
  const failed = await call("/api/analyze", { case_id: "NTK-039", mode: "full", fresh: false });
  assert.equal(failed.status, 502);
  assert.equal((await failed.json()).error.code, "RECORDED_MODEL_OUTPUT_FAILED");
}
console.log("PASS: 90 Python/Worker projections and hashes; hosted request bounds, origins, oracle exclusion and recorded-run provenance.");
