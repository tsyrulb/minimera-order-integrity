import { Icon } from "./Icon";
import { amounts, paymentStatus } from "./presentation";
import { fulfillment, money } from "./types";
import type { Workspace } from "./types";

export function Outcome({ ws }: { ws: Workspace }) {
  const change = ws.change;
  if (!change) return null;
  const stopped = change.state === "stale" || change.state === "blocked";
  const verified =
    change.state === "complete" &&
    change.refund?.status === "COMPLETED" &&
    change.replacement?.capture_status === "COMPLETED";
  if (!stopped && !verified) return null;
  const warehouseChanged =
    change.state === "stale" &&
    !!change.approved_hash &&
    ws.events.some((event) => event.action === "external_state_changed");
  const values = amounts(ws);
  return (
    <section
      className={`outcome ${stopped ? "outcome-stopped" : "outcome-verified"}`}
      aria-labelledby="outcome-title"
    >
      <div className="outcome-heading">
        <span className="outcome-icon">
          <Icon name={stopped ? "shield" : "check"} size={23} />
        </span>
        <div>
          <p className="eyebrow">
            {stopped
              ? "Payment execution blocked"
              : "Payment outcomes verified"}
          </p>
          <h2 id="outcome-title">
            {warehouseChanged
              ? "Warehouse changed after approval."
              : stopped
                ? "This order cannot continue automatically."
                : fulfillment(ws) === "released"
                  ? "The corrected order now matches the payment."
                  : "Both payment checks passed. Release stays with you."}
          </h2>
          <p className="outcome-description">
            {stopped
              ? "The current order state does not authorize this payment plan. Inspect the saved evidence before continuing."
              : "The original refund and separate replacement capture were independently checked. Customer totals exclude processing fees."}
          </p>
        </div>
      </div>
      <dl className="outcome-facts">
        <div>
          <dt>Original refund</dt>
          <dd>
            <span>
              {verified
                ? money(values.original)
                : change.refund
                  ? paymentStatus(change.refund.status)
                  : "Not sent"}
            </span>
            {verified && <small>Verified completed</small>}
          </dd>
        </div>
        <div>
          <dt>Replacement capture</dt>
          <dd>
            <span>
              {verified
                ? money(values.replacement)
                : change.replacement
                  ? paymentStatus(
                      change.replacement.capture_status ||
                        change.replacement.status,
                    )
                  : "Not captured"}
            </span>
            {verified && <small>Verified completed</small>}
          </dd>
        </div>
        <div>
          <dt>{verified ? "Difference to the customer" : "Warehouse state"}</dt>
          <dd>
            <span>
              {verified
                ? money(values.difference)
                : fulfillment(ws) === "shipped"
                  ? "Already shipped"
                  : "Held for review"}
            </span>
            {verified && <small>Difference between order totals</small>}
          </dd>
        </div>
      </dl>
    </section>
  );
}
