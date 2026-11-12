import { Icon } from "./Icon";
import { Badge } from "./components";
import { pretty } from "./types";
import type { View } from "./types";

export function Evidence({ view }: { view: View }) {
  const ws = view.workspace;
  return (
    <>
      <section className="card evidence-header">
        <span className="metric-icon mint">
          <Icon name="document" size={24} />
        </span>
        <div>
          <h2>Order history</h2>
          <p>
            The request, approvals and verified outcomes, in order. Export the
            normalized records for inspection.
          </p>
        </div>
        <a className="button" href="/api/integrity/evidence" download>
          <Icon name="down" size={16} />
          Download evidence
        </a>
      </section>
      <section className="card evidence-list">
        {ws.events.map((e) => (
          <div className="evidence-event" key={e.sequence}>
            <span className="event-index">
              {String(e.sequence).padStart(2, "0")}
            </span>
            <div>
              <div className="event-title">
                <h3>{pretty(e.action)}</h3>
                <Badge>{pretty(e.actor)}</Badge>
              </div>
              <p>{e.detail}</p>
              <small>
                {new Date(e.at).toLocaleString()} ·{" "}
                <code title={e.hash}>{e.hash.slice(0, 20)}…</code>
              </small>
            </div>
          </div>
        ))}
      </section>
      {ws.change && (
        <section className="card provider-evidence">
          <h3>Payment observations</h3>
          <div className="observation-grid">
            {[
              [
                "Original capture",
                ws.order.payment?.capture_id,
                ws.order.payment?.capture_status,
              ],
              [
                "Original refund",
                ws.change.refund?.refund_id,
                ws.change.refund?.status,
              ],
              [
                "Replacement capture",
                ws.change.replacement?.capture_id,
                ws.change.replacement?.capture_status,
              ],
            ].map(([label, id, state]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{state || "Not observed"}</strong>
                <code>{id || "No provider ID yet"}</code>
              </div>
            ))}
          </div>
          <p className="caption">
            Source:{" "}
            {ws.mode === "simulation"
              ? "durable local payment simulator"
              : "PayPal Sandbox read-back"}
            . A local hash chain is not an external attestation or an immutable
            ledger.
          </p>
        </section>
      )}
    </>
  );
}
