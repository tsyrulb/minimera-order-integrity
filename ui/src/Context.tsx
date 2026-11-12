import { useState } from "react";
import { adviceLabel } from "./presentation";
import { Icon } from "./Icon";
import { pretty } from "./types";
import type { View } from "./types";

export function Context({ view }: { view: View }) {
  const [selected, setSelected] = useState<string | null>(null);
  const change = view.workspace.change;
  if (!change)
    return (
      <p className="caption">Create a request to inspect its model context.</p>
    );
  const advice = change.advice;
  return (
    <div className="context-content">
      <div className="context-summary">
        <span className="context-number">{change.facts.length}</span>
        <div>
          <strong>Facts included in this model request</strong>
          <p>
            Facts captured when the request arrived. The warehouse state may
            have changed since then.
          </p>
        </div>
      </div>
      <div
        className="context-table"
        role="list"
        aria-label="Exact model context facts"
      >
        {change.facts.map((f) => (
          <div
            className={`context-fact ${selected === f.id ? "selected" : ""}`}
            role="listitem"
            id={`fact-${f.id}`}
            key={f.id}
            tabIndex={-1}
          >
            <code>{f.id}</code>
            <div>
              <strong>{f.label}</strong>
              <span>{pretty(f.source)}</span>
            </div>
            <b>{f.value}</b>
          </div>
        ))}
      </div>
      <div className="excluded-data">
        <Icon name="lock" size={17} />
        <div>
          <strong>Kept outside this model context</strong>
          <p>Names · full addresses · messages · payment IDs · API secrets</p>
          <small>
            Minimera still processes the order details required for this
            workflow.
          </small>
        </div>
      </div>
      {advice?.plan && (
        <section className="full-ai-review">
          <div className="panel-heading">
            <h3>Why this path?</h3>
            <span className="ai-provenance">{adviceLabel(advice)}</span>
          </div>
          <p>{advice.plan.summary}</p>
          <div className="citations">
            {advice.plan.fact_ids.map((id) => (
              <button
                key={id}
                onClick={() => {
                  setSelected(id);
                  document
                    .getElementById(`fact-${id}`)
                    ?.focus({ preventScroll: false });
                }}
                aria-label={`Show cited fact ${id}`}
              >
                {id}
              </button>
            ))}
            <span>
              {advice.policy_agrees
                ? "Agrees with deterministic policy"
                : "Policy disagreement — model advice cannot authorize payments"}
            </span>
          </div>
          <ol>
            {advice.plan.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <details>
            <summary>Proposed customer message</summary>
            <blockquote>{advice.plan.customer_message}</blockquote>
          </details>
          <small>
            GPT-OSS 120B · AWS Bedrock ·{" "}
            {advice.prompt_version || "Versioned review"}
          </small>
        </section>
      )}
    </div>
  );
}
