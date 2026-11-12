import { Icon } from "./Icon";

export function ScenarioCards({
  start,
  busy,
}: {
  start: (scenario: string) => unknown;
  busy: string;
}) {
  return (
    <div className="scenario-cards">
      {[
        [
          "address_change",
          "shield",
          "A safe change",
          "Change the address and remove an item. Verify the refund and replacement.",
        ],
        [
          "already_shipped",
          "box",
          "Already shipped",
          "See why a dispatched order needs manual review.",
        ],
        [
          "stale_approval",
          "clock",
          "The order changed",
          "Approve a plan, then let the warehouse ship. Watch payment execution stop.",
        ],
      ].map(([id, icon, title, body]) => (
        <button
          key={id}
          disabled={!!busy}
          className="scenario-card"
          aria-label={`Start scenario: ${title}`}
          onClick={() => start(id)}
        >
          <span className="scenario-icon">
            <Icon name={icon} size={21} />
          </span>
          <span className="scenario-copy">
            <strong>{title}</strong>
            <span>{body}</span>
          </span>
          <Icon name="chevron" size={17} />
        </button>
      ))}
    </div>
  );
}

export function Welcome({
  start,
  busy,
  sandbox,
}: {
  start: (scenario: string, mode?: string) => unknown;
  busy: string;
  sandbox: boolean;
}) {
  return (
    <section className="welcome" aria-label="Minimera interactive demo">
      <div className="welcome-hero">
        <div className="welcome-inner">
          <p className="welcome-kicker">After checkout. Before shipment.</p>
          <h1>
            The order changed.
            <br />
            The payment didn’t.
          </h1>
          <p>
            The customer asks for Boston. The paid PayPal order still says New
            York. Hold fulfillment, approve the exact change and verify the
            refund and replacement payment.
          </p>
          <button
            className="button primary"
            disabled={!!busy}
            onClick={() => start("address_change")}
          >
            Explore a safe change <Icon name="arrow" size={18} />
          </button>
          <button
            className="text-button welcome-failure-link"
            disabled={!!busy}
            onClick={() => start("stale_approval")}
          >
            Test an outdated approval <Icon name="arrow" size={15} />
          </button>
          <span className="welcome-caption">
            Interactive simulation. No account or API keys needed.
          </span>
        </div>
        <div className="welcome-example" aria-label="Example order change">
          <div className="sample-order-header">
            <span>Northline Goods</span>
            <strong>Order NL-1042</strong>
          </div>
          <div className="sample-request">
            <span className="tiny-avatar">JD</span>
            <p>
              “Send it to my office instead.
              <br />
              And remove the travel pouch.”
            </p>
          </div>
          <div className="sample-change-row">
            <span>Customer request</span>
            <strong>Boston · 1 item</strong>
            <b>$84.00</b>
          </div>
          <div className="sample-change-row">
            <span>Paid PayPal order</span>
            <strong>New York · 2 items</strong>
            <b>$120.00</b>
          </div>
          <div className="sample-order-bottom">
            <span>
              <Icon name="lock" size={15} /> Shipment on hold
            </span>
            <span>Request and payment differ</span>
          </div>
        </div>
      </div>
      <div className="welcome-scenarios-heading">
        <h2>Try a different outcome</h2>
        <span>Each scenario has its own workspace.</span>
      </div>
      <ScenarioCards start={start} busy={busy} />
      {sandbox && (
        <button
          className="text-button sandbox-link"
          disabled={!!busy}
          onClick={() => start("address_change", "sandbox")}
        >
          Run a $1.00 PayPal Sandbox order <Icon name="external" size={14} />
        </button>
      )}
      <div className="welcome-scope">
        <Icon name="shield" size={17} />
        <p>
          Payment actions follow deterministic checks. AI reviews seven scoped
          facts; merchant and buyer approvals stay separate.
        </p>
      </div>
    </section>
  );
}
