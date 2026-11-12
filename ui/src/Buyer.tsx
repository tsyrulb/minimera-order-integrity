import { useEffect, useState } from "react";
import { Icon } from "./Icon";
import { api } from "./api";
import { Badge, Product, Address } from "./components";
import { labels, money, total } from "./types";
import { paymentStatus } from "./presentation";
import type { BuyerView } from "./types";
export function Buyer() {
  const token = window.location.pathname.startsWith("/buyer/")
    ? window.location.pathname.slice(7)
    : sessionStorage.getItem("minimera_buyer") || "";
  const [data, setData] = useState<BuyerView | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("Opening your order"),
    [connectionLost, setConnectionLost] = useState(false),
    [notice, setNotice] = useState(""),
    [remove, setRemove] = useState(true),
    [destination, setDestination] = useState("office");
  const headers = { "X-Minimera-Buyer": token };
  const refresh = async () => {
    const next = await api<BuyerView>("/buyer", { headers });
    setData((previous) =>
      previous && previous.revision > next.revision ? previous : next,
    );
    setConnectionLost(false);
  };
  useEffect(() => {
    if (token) sessionStorage.setItem("minimera_buyer", token);
    let active = true;
    (async () => {
      try {
        const query = new URLSearchParams(window.location.search);
        if (query.get("cancelled")) {
          setNotice(
            "Checkout was cancelled. Review the saved order state below or return to the merchant.",
          );
          history.replaceState({}, "", "/buyer/" + token);
        }
        if (
          window.location.pathname === "/return" &&
          query.get("checkout") &&
          !query.get("cancelled")
        ) {
          setBusy("Verifying your payment");
          await api("/buyer/complete", {
            method: "POST",
            headers,
            body: JSON.stringify({
              checkout_id: query.get("checkout"),
              state: query.get("state"),
            }),
          });
          history.replaceState({}, "", "/buyer/" + token);
        }
        await refresh();
      } catch (e) {
        if (active)
          setError(
            e instanceof Error ? e.message : "Unable to open this order.",
          );
        await refresh().catch(() => {
          if (active) setConnectionLost(true);
        });
      } finally {
        if (active) setBusy("");
      }
    })();
    const timer = window.setInterval(
      () => refresh().catch(() => setConnectionLost(true)),
      3000,
    );
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [token]);
  const run = async (label: string, action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(label);
    setError("");
    try {
      await action();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to continue.");
      await refresh().catch(() => setConnectionLost(true));
    } finally {
      setBusy("");
    }
  };
  const checkout = (purpose: string) =>
    run("Opening secure checkout", async () => {
      sessionStorage.setItem("minimera_buyer", token);
      const result = await api<{
        checkout_id: string;
        state: string;
        approval_url: string;
        mode: string;
      }>("/buyer/checkout/" + purpose, { method: "POST", headers });
      if (result.mode === "simulation") {
        await api("/buyer/complete", {
          method: "POST",
          headers,
          body: JSON.stringify({
            checkout_id: result.checkout_id,
            state: result.state,
          }),
        });
      } else {
        window.location.assign(result.approval_url);
      }
    });
  return (
    <div className="buyer-app">
      <header className="buyer-top">
        <div className="northline-brand">
          NORTHLINE<span>GOODS</span>
        </div>
        <Badge>
          {!data
            ? "Opening order"
            : data.mode === "sandbox"
              ? "PayPal Sandbox · test funds"
              : "Local payment simulation"}
        </Badge>
      </header>
      <main className="buyer-main">
        <a className="back-link" href="/">
          ← Return to merchant demo
        </a>
        <h1>Review your order</h1>
        <p className="page-subtitle">
          Review a change to order #{data?.order.id || "NL-1042"}.
        </p>
        {error && (
          <div className="notice error" role="alert">
            <Icon name="alert" />
            {error}
          </div>
        )}
        {notice && (
          <div className="checkout-notice" role="status">
            <Icon name="document" size={18} />
            <span>{notice}</span>
          </div>
        )}
        {connectionLost && (
          <div className="notice warning" role="status">
            <Icon name="clock" size={18} />
            <span>Connection interrupted. Showing the last saved order.</span>
            <button
              className="text-button"
              onClick={() => run("Reconnecting", refresh)}
            >
              Reconnect
            </button>
          </div>
        )}
        {busy && (
          <div className="busy-strip" role="status">
            <span className="spinner" />
            {busy}…
          </div>
        )}
        {data && (
          <div className="buyer-columns">
            <section className="card buyer-order">
              <div className="panel-heading">
                <h2>Order details</h2>
                <Badge
                  tone={
                    data.change?.state === "complete" ? "success" : "neutral"
                  }
                >
                  {data.change?.state === "complete"
                    ? "Replacement paid"
                    : data.change?.refund_status === "COMPLETED"
                      ? "Original refunded"
                      : data.order.payment?.capture_status === "COMPLETED"
                        ? "Paid"
                        : data.order.payment
                          ? paymentStatus(data.order.payment.capture_status)
                          : "Awaiting payment"}
                </Badge>
              </div>
              {(data.change?.state === "complete"
                ? data.change.items
                : data.order.items
              ).map((i) => (
                <Product key={i.sku} item={i} />
              ))}
              <Address
                destination={
                  data.change?.state === "complete"
                    ? data.change.destination
                    : data.order.destination
                }
              />
              <div className="buyer-total">
                <span>Order total</span>
                <strong>
                  {money(
                    total(
                      data.change?.state === "complete"
                        ? data.change.items
                        : data.order.items,
                    ),
                  )}
                </strong>
              </div>
              <p className="caption">
                All names, items and addresses in this demo are synthetic. No
                goods will be shipped.
              </p>
            </section>
            <section className="card buyer-change">
              {!data.order.payment ? (
                <>
                  <span className="metric-icon lavender">
                    <Icon name="lock" size={24} />
                  </span>
                  <h2>Start with a test payment.</h2>
                  <p>
                    This creates the original paid order so you can try a
                    post-purchase change. Continue on PayPal Sandbox using a
                    test buyer account.
                  </p>
                  <button
                    className="button paypal-button"
                    disabled={!!busy}
                    onClick={() => checkout("original")}
                  >
                    Pay {money(total(data.order.items))} with PayPal Sandbox{" "}
                    <Icon name="external" size={16} />
                  </button>
                  <small>Sandbox test money only.</small>
                </>
              ) : !data.change ? (
                <>
                  <h2>What would you like to change?</h2>
                  <label className="field-label" htmlFor="destination">
                    Send my order to
                  </label>
                  <select
                    id="destination"
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                  >
                    <option value="office">
                      My office in Boston · Test address
                    </option>
                    <option value="home">
                      My home in New York · Original address
                    </option>
                  </select>
                  <label className="checkbox-field">
                    <input
                      type="checkbox"
                      checked={remove}
                      onChange={(e) => setRemove(e.target.checked)}
                    />
                    <span>
                      Remove the travel pouch
                      <small>Keep the weekender tote.</small>
                    </span>
                  </label>
                  <div className="buyer-callout">
                    <Icon name="shield" size={19} />
                    <p>
                      We’ll review the request before changing your payment.
                      Your order will pause while we check it.
                    </p>
                  </div>
                  <button
                    className="button primary"
                    disabled={!!busy}
                    onClick={() =>
                      run("Sending your request", () =>
                        api("/buyer/change", {
                          method: "POST",
                          headers,
                          body: JSON.stringify({
                            destination,
                            remove_pouch: remove,
                          }),
                        }),
                      )
                    }
                  >
                    Request this change <Icon name="arrow" size={17} />
                  </button>
                </>
              ) : ["approved", "awaiting_buyer"].includes(data.change.state) ? (
                <>
                  <Badge>Merchant approved this plan</Badge>
                  <h2>Let’s confirm the new order.</h2>
                  <Address destination={data.change.destination} />
                  <div className="buyer-money">
                    <span>
                      Original refund
                      <strong>{money(total(data.order.items))}</strong>
                    </span>
                    <span>
                      New payment<strong>{money(data.change.cents)}</strong>
                    </span>
                    <span>
                      You receive back
                      <strong>
                        {money(total(data.order.items) - data.change.cents)}
                      </strong>
                    </span>
                  </div>
                  <p>
                    You’ll approve a separate replacement payment. We verify
                    your original refund before capturing the new payment. Your
                    bank may take longer to make the refund available.
                  </p>
                  <button
                    className={`button ${data.mode === "sandbox" ? "paypal-button" : "primary"}`}
                    disabled={!!busy}
                    onClick={() => checkout("replacement")}
                  >
                    {data.mode === "sandbox"
                      ? "Approve with PayPal Sandbox"
                      : "Approve replacement · Simulation"}
                    <Icon name="arrow" size={16} />
                  </button>
                  <small>
                    If either payment cannot be verified, your order stays
                    paused.
                  </small>
                </>
              ) : data.change.state === "complete" ? (
                <>
                  <div className="success-circle">
                    <Icon name="check" size={32} />
                  </div>
                  <h2>Your change is confirmed.</h2>
                  <p>
                    The original refund and new payment have both been verified.
                    Your corrected order is with the shop for fulfillment.
                  </p>
                  <div className="buyer-money">
                    <span>
                      Refund<strong>{data.change.refund_status}</strong>
                    </span>
                    <span>
                      Replacement payment
                      <strong>{data.change.replacement_status}</strong>
                    </span>
                  </div>
                  <a className="button primary" href="/">
                    Review the merchant result <Icon name="arrow" size={17} />
                  </a>
                </>
              ) : (
                <>
                  <span className="metric-icon sand">
                    <Icon name="clock" size={24} />
                  </span>
                  <h2>
                    {data.change.state === "review"
                      ? "Your request is with the shop."
                      : labels[data.change.state] ||
                        "We’re checking your request."}
                  </h2>
                  <p>{data.change.explanation}</p>
                  <a className="button" href="/">
                    Continue in the merchant demo{" "}
                    <Icon name="arrow" size={17} />
                  </a>
                </>
              )}
            </section>
          </div>
        )}
        {!data && !busy && (
          <p className="caption">
            Open an authorized buyer link from the merchant workspace.
          </p>
        )}
      </main>
      <footer className="buyer-footer">
        <Icon name="shield" size={15} />
        Order changes coordinated by <strong>Minimera</strong>
        <span>·</span>Payment approvals stay with PayPal
      </footer>
    </div>
  );
}
