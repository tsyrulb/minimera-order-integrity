import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { Outcome } from "./Outcome";
import { Address, Badge, Product } from "./components";
import {
  adviceLabel,
  amounts,
  paymentStatus,
  requestLabel,
  requestText,
  timeLabel,
  workflow,
} from "./presentation";
import { fulfillment, money, pretty } from "./types";
import type { View, Workspace } from "./types";
import "./order-scene.css";

export function SourceComparison({
  ws,
  compact = false,
}: {
  ws: Workspace;
  compact?: boolean;
}) {
  const change = ws.change;
  const corrected =
    change?.state === "complete" &&
    change.replacement?.capture_status === "COMPLETED";
  const payment = corrected ? change.replacement : ws.order.payment;
  const destination = change?.destination || "office";
  const mismatch = !!change && payment?.destination !== destination;
  const shipment = fulfillment(ws);
  const warehouseDestination =
    ws.fulfillment_order?.destination || ws.order.destination;
  return (
    <div
      className={`systems-grid ${compact ? "compact-systems" : ""}`}
      role="group"
      aria-label="Request, payment and fulfillment comparison"
    >
      <section className="system-card request-source">
        <div className="system-heading">
          <span className="system-symbol">
            <Icon name="user" size={18} />
          </span>
          <span>Customer request</span>
          <span className="source-kind">Synthetic</span>
        </div>
        <strong className="system-value">
          {destination === "office" ? "Office · Boston" : "Home · New York"}
        </strong>
        <p>
          {change
            ? `${change.items.reduce((n, item) => n + item.quantity, 0)} item(s) · ${money(change.items.reduce((n, item) => n + item.cents * item.quantity, 0))}`
            : "Example: new address, one less item"}
        </p>
        <div className="system-footer">
          <span className="tiny-avatar">JD</span>
          <span>Jamie · order owner</span>
        </div>
      </section>
      <span
        className={`source-link ${mismatch ? "different" : ""}`}
        role="img"
        aria-label={
          mismatch
            ? "Shipping destinations differ"
            : "Compare request and payment"
        }
      >
        <Icon name={mismatch ? "alert" : "arrow"} size={15} />
      </span>
      <section
        className={`system-card payment-source ${mismatch ? "has-mismatch" : ""}`}
      >
        <div className="system-heading">
          <span className="paypal-symbol" aria-hidden="true">
            P
          </span>
          <span>
            {corrected
              ? "PayPal replacement"
              : payment
                ? "PayPal paid order"
                : "PayPal order"}
          </span>
          <span className="source-kind">
            {ws.mode === "sandbox" ? "Sandbox" : "Simulator"}
          </span>
        </div>
        <strong className="system-value">
          {payment
            ? payment.destination === "office"
              ? "Office · Boston"
              : "Home · New York"
            : "Payment not started"}
        </strong>
        <p>
          {payment
            ? `${money(payment.cents)} · ${paymentStatus(payment.capture_status || payment.status)}`
            : "Buyer approval is required"}
        </p>
        <div className="system-footer">
          {payment ? (
            <>
              <Icon name="clock" size={13} />
              <span title={payment.verified_at}>
                Observed {timeLabel(payment.verified_at)}
              </span>
            </>
          ) : (
            <>
              <Icon name="lock" size={13} />
              <span>PayPal approval stays with the buyer</span>
            </>
          )}
        </div>
      </section>
      <span
        className="source-link"
        role="img"
        aria-label="Payment checks precede warehouse release"
      >
        <Icon name="arrow" size={15} />
      </span>
      <section
        className={`system-card warehouse-source ${shipment === "shipped" ? "shipment-sent" : ""}`}
      >
        <div className="system-heading">
          <span className="system-symbol">
            <Icon name="box" size={18} />
          </span>
          <span>Warehouse</span>
          <span className="source-kind">Simulator</span>
        </div>
        <strong className="system-value">
          {shipment === "on_hold"
            ? "On hold"
            : shipment === "ready"
              ? "Ready for review"
              : shipment === "released"
                ? "Corrected order queued"
                : shipment === "shipped"
                  ? "Already shipped"
                  : pretty(shipment)}
        </strong>
        <p>
          {shipment === "on_hold"
            ? "Waiting for approvals and payment checks"
            : shipment === "ready" || shipment === "released"
              ? `${warehouseDestination === "office" ? "Boston" : "New York"} · ${ws.fulfillment_order?.items.length || ws.order.items.length} item(s)`
              : shipment === "shipped"
                ? "Automatic changes are blocked"
                : "The order has not shipped"}
        </p>
        <div className="system-footer">
          <Icon
            name={
              shipment === "on_hold"
                ? "lock"
                : shipment === "shipped"
                  ? "alert"
                  : "check"
            }
            size={13}
          />
          <span>
            {ws.fulfillment_order?.id || ws.order.id} · version{" "}
            {ws.fulfillment_order?.revision || ws.order.revision}
          </span>
        </div>
      </section>
    </div>
  );
}

function Journey({ ws }: { ws: Workspace }) {
  const current = workflow(ws).step;
  const blocked =
    ["blocked", "stale", "indeterminate"].includes(ws.change?.state || "") &&
    ws.change?.route !== "no_change";
  return (
    <ol className="journey" aria-label="Order change progress">
      {["Request", "Review", "Merchant", "Buyer", "Verify & release"].map(
        (label, i) => {
          const done =
            i < current - 1 ||
            (current === 5 && fulfillment(ws) === "released");
          const active = i === Math.max(0, current - 1);
          return (
            <li
              key={label}
              className={
                done
                  ? "done"
                  : active
                    ? `current ${blocked ? "stopped" : ""}`
                    : ""
              }
              aria-current={active ? "step" : undefined}
            >
              <span>
                {done ? (
                  <Icon name="check" size={12} />
                ) : (
                  String(i + 1).padStart(2, "0")
                )}
              </span>
              <b>{label}</b>
            </li>
          );
        },
      )}
    </ol>
  );
}

export function StateComparison({ ws }: { ws: Workspace }) {
  const change = ws.change;
  if (!change) return null;
  const before = change.facts.find((f) => f.id === "F2")?.value || "unknown";
  const changed = before !== ws.order.fulfillment;
  return (
    <div className="state-comparison" role="status">
      <span className="state-comparison-icon">
        <Icon name="alert" size={22} />
      </span>
      <div>
        <strong>
          {change.state === "stale"
            ? "This approval belongs to an earlier state."
            : "The current order needs a human decision."}
        </strong>
        <div className="state-values">
          <span>
            At request: <b>{pretty(before)}</b>
          </span>
          <Icon name="arrow" size={14} />
          <span>
            Now: <b>{pretty(ws.order.fulfillment)}</b>
          </span>
        </div>
        <small>
          {changed
            ? "The request-time facts are preserved. The current warehouse state is checked separately."
            : change.explanation}
        </small>
        {change.approved_hash && (
          <code title={change.approved_hash}>
            Saved approval · {change.approved_hash.slice(0, 16)}…
          </code>
        )}
      </div>
    </div>
  );
}

function PaymentPlan({ ws }: { ws: Workspace }) {
  const values = amounts(ws);
  const change = ws.change;
  const refund = change?.refund?.status;
  const capture = change?.replacement?.capture_status;
  return (
    <div className="payment-plan" aria-label="Separate payment operations">
      <div
        className={`payment-leg ${refund === "COMPLETED" ? "verified" : ""}`}
      >
        <span className="leg-icon">1</span>
        <div>
          <span className="leg-label">Original refund</span>
          <strong>{money(values.original)}</strong>
          <small>
            {refund ? paymentStatus(refund) : "After the buyer approves"}
          </small>
        </div>
        {refund === "COMPLETED" && (
          <span className="leg-verified">
            <Icon name="check" size={14} />
            Verified
          </span>
        )}
      </div>
      <span className="payment-bridge" aria-hidden="true">
        <Icon name="arrow" size={18} />
      </span>
      <div
        className={`payment-leg ${capture === "COMPLETED" ? "verified" : ""}`}
      >
        <span className="leg-icon">2</span>
        <div>
          <span className="leg-label">Replacement payment</span>
          <strong>{money(values.replacement)}</strong>
          <small>
            {capture ? paymentStatus(capture) : "After the refund is verified"}
          </small>
        </div>
        {capture === "COMPLETED" && (
          <span className="leg-verified">
            <Icon name="check" size={14} />
            Verified
          </span>
        )}
      </div>
      <div className="customer-difference">
        <span>Back to the customer</span>
        <strong>{money(values.difference)}</strong>
        <small>Difference between order totals</small>
      </div>
    </div>
  );
}

function CustomerRequest({ ws }: { ws: Workspace }) {
  if (!ws.change) return null;
  return (
    <div className="customer-message">
      <span className="tiny-avatar">JD</span>
      <div>
        <span>
          Jamie <small>Test customer</small>
        </span>
        <p>{requestText(ws)}</p>
      </div>
    </div>
  );
}

export function AiReview({
  view,
  onContext,
  onAnalyze,
  busy,
}: {
  view: View;
  onContext: () => void;
  onAnalyze: () => void;
  busy: boolean;
}) {
  const change = view.workspace.change;
  const advice = change?.advice;
  const currentState =
    change &&
    ["stale", "pending", "indeterminate", "processing", "complete"].includes(
      change.state,
    );
  return (
    <section className="ai-review" aria-labelledby="ai-review-heading">
      <div className="ai-review-icon">
        <Icon name="document" size={19} />
      </div>
      <div className="ai-review-copy">
        <div className="ai-review-heading">
          <h3 id="ai-review-heading">
            {currentState ? "Current outcome" : "AI review"}
          </h3>
          <span className="ai-provenance">
            {currentState ? "Current workflow state" : adviceLabel(advice)}
          </span>
        </div>
        <p>
          {(currentState ? change.explanation : advice?.plan?.summary) ||
            "The analyst explains the request using scoped facts. Deterministic checks control payment execution."}
        </p>
        {advice?.policy_agrees === false && (
          <p className="model-disagreement">
            The model and policy disagree. The model does not authorize
            payments.
          </p>
        )}
        <div className="ai-review-links">
          <button className="text-button" onClick={onContext}>
            <Icon name="lock" size={13} />
            See the {change?.facts.length || 7} facts sent to the model
          </button>
          {change && !advice?.plan && (
            <button className="text-button" disabled={busy} onClick={onAnalyze}>
              Run AI review
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

export function OrderScene({
  view,
  primary,
  busy,
  onContext,
  onAnalyze,
  onDetails,
  onScenario,
  onWarehouseTest,
  onRecheck,
}: {
  view: View;
  primary: ReactNode;
  busy: string;
  onContext: () => void;
  onAnalyze: () => void;
  onDetails: () => void;
  onScenario: () => void;
  onWarehouseTest: () => void;
  onRecheck: () => void;
}) {
  const ws = view.workspace;
  const change = ws.change;
  const state = workflow(ws);
  const mismatch =
    !!change &&
    change.route === "replace_order" &&
    change.state !== "complete" &&
    ws.order.payment?.destination !== change.destination;
  const stopped =
    change?.state === "stale" ||
    (change?.state === "blocked" && change.route !== "no_change");
  const approved =
    change?.state === "approved" || change?.state === "awaiting_buyer";
  return (
    <>
      <section
        className={`order-scene tone-${state.tone}`}
        aria-label="Order change workspace"
      >
        <Outcome ws={ws} />
        <div className="scene-toolbar">
          <div>
            <span className="order-marker">
              <Icon name="box" size={17} />
            </span>
            <strong>{change ? "Requested changes" : "Original order"}</strong>
            <span className="scene-request">{requestLabel(ws)}</span>
          </div>
          <button className="text-button" onClick={onDetails}>
            Order details <Icon name="chevron" size={13} />
          </button>
        </div>
        <Journey ws={ws} />
        <div className="order-workbench">
          <div className="order-document">
            <div className="scene-body">
              <CustomerRequest ws={ws} />
              <div className="order-sources-main">
                <SourceComparison ws={ws} />
              </div>
              {stopped ? (
                <StateComparison ws={ws} />
              ) : (
                <div
                  className={`decision-line ${mismatch ? "mismatch" : state.tone === "success" ? "resolved" : ""}`}
                >
                  <span>
                    <Icon
                      name={
                        state.tone === "success"
                          ? "check"
                          : mismatch
                            ? "alert"
                            : "shield"
                      }
                      size={18}
                    />
                  </span>
                  <p>
                    <strong>
                      {state.tone === "success"
                        ? "The replacement matches the requested change."
                        : mismatch
                          ? "The paid order needs to be replaced."
                          : change?.route === "no_change"
                            ? "The request leaves the order unchanged."
                            : approved
                              ? "Merchant approval is saved. Buyer approval is still required."
                              : "Every change starts with a state check."}
                    </strong>
                    <span>
                      {state.tone === "success"
                        ? "Both payment operations have been independently checked."
                        : mismatch
                          ? "The new destination differs from the paid PayPal order. A full refund and a new payment keep the records aligned."
                          : state.summary}
                    </span>
                  </p>
                </div>
              )}
            </div>
            <div className="scene-explanation">
              <AiReview
                view={view}
                onContext={onContext}
                onAnalyze={onAnalyze}
                busy={!!busy}
              />
            </div>
          </div>
          <aside
            className={`decision-panel ${ws.mode === "simulation" && ws.scenario === "stale_approval" && !stopped ? "challenge-panel" : ""}`}
            aria-label="Payment plan and next action"
          >
            <div className="decision-panel-heading">
              <h2>
                {stopped
                  ? "Execution blocked"
                  : change?.route === "no_change"
                    ? "No payment change"
                    : "Payment plan"}
              </h2>
              <span>
                {stopped
                  ? "No payment operation sent"
                  : change?.route === "no_change"
                    ? "The current order is unchanged"
                    : "Refund first, replacement second"}
              </span>
            </div>
            {(!change || change.route === "replace_order") && (
              <PaymentPlan ws={ws} />
            )}
            <div className="scene-action">
              <div>
                <span className="action-eyebrow">
                  {change?.state === "review"
                    ? "Merchant approval"
                    : approved
                      ? "Buyer approval"
                      : change?.state === "complete"
                        ? "Fulfillment"
                        : stopped
                          ? "Manual review required"
                          : "Next step"}
                </span>
                <strong>
                  {change?.state === "review"
                    ? "Approve this order version."
                    : approved
                      ? "The buyer confirms the amount and address."
                      : change?.state === "complete"
                        ? fulfillment(ws) === "released"
                          ? "The corrected order is in the warehouse queue."
                          : "Review and release the corrected order."
                        : stopped
                          ? "Automatic payment execution is blocked."
                          : state.summary}
                </strong>
                <small>
                  {change?.state === "review"
                    ? "Valid for 30 minutes. The buyer must approve next."
                    : ws.mode === "simulation"
                      ? "Local payment simulation · no live money"
                      : "PayPal Sandbox · test funds only"}
                </small>
              </div>
              <div className="primary-action" aria-busy={!!busy}>
                {primary}
              </div>
              {ws.mode === "simulation" &&
                ws.scenario === "stale_approval" &&
                change &&
                ["review", "approved"].includes(change.state) && (
                  <div className="failure-experiment">
                    <span className="action-eyebrow">
                      Controlled simulation
                    </span>
                    <p>
                      {approved
                        ? "Now change the warehouse after this approval."
                        : "First approve the plan. Then change the warehouse."}
                    </p>
                    <button
                      className="boundary-button"
                      onClick={onWarehouseTest}
                      disabled={!!busy || !approved}
                    >
                      <Icon name="alert" size={15} />
                      What if the warehouse ships now?
                    </button>
                  </div>
                )}
            </div>
            {change?.route === "replace_order" && !stopped && (
              <p className="payment-sequence-note">
                <Icon name="lock" size={14} />
                Replacement capture waits for a verified refund.
              </p>
            )}
          </aside>
        </div>
      </section>
      <div className="scene-tools">
        <div>
          <Icon name="shield" size={15} />
          <span>Approval is bound to this version of the order.</span>
          {approved && (
            <button
              className="text-button"
              onClick={onRecheck}
              disabled={!!busy}
            >
              Recheck approval <Icon name="refresh" size={13} />
            </button>
          )}
        </div>
        <button className="text-button" onClick={onScenario}>
          Test a different scenario
        </button>
      </div>
    </>
  );
}

export function OrderDetails({ view }: { view: View }) {
  const ws = view.workspace;
  return (
    <div className="order-details-content">
      <div className="request-quote">
        <span className="tiny-avatar">JD</span>
        <div>
          <strong>Jamie · test customer</strong>
          <blockquote>“{requestText(ws)}”</blockquote>
        </div>
      </div>
      <div className="details-addresses">
        <div>
          <p className="eyebrow">ORIGINAL DESTINATION</p>
          <Address destination={ws.order.destination} />
        </div>
        <div>
          <p className="eyebrow">REQUESTED DESTINATION</p>
          <Address destination={ws.change?.destination || "office"} />
        </div>
      </div>
      <p className="eyebrow">ORIGINAL ORDER</p>
      <div className="product-list">
        {ws.order.items.map((item) => (
          <Product
            key={item.sku}
            item={item}
            removed={!!ws.change?.remove_pouch && item.sku === "POUCH"}
          />
        ))}
      </div>
      <p className="caption">
        All customer details are synthetic. Displayed amounts are gross customer
        amounts; processing fees and taxes are not calculated here.
      </p>
    </div>
  );
}

export function RecentActivity({
  view,
  onEvidence,
}: {
  view: View;
  onEvidence: () => void;
}) {
  return (
    <section className="recent-activity">
      <div className="panel-heading">
        <h2>Recent activity</h2>
        <button className="text-button" onClick={onEvidence}>
          Open evidence trail
        </button>
      </div>
      <ol>
        {view.workspace.events.slice(-4).map((e) => (
          <li key={e.sequence}>
            <span className="event-dot" />
            <div>
              <strong>{pretty(e.action)}</strong>
              <span>
                {pretty(e.actor)} · {timeLabel(e.at)}
              </span>
            </div>
            <Icon name="check" size={14} />
          </li>
        ))}
      </ol>
    </section>
  );
}
