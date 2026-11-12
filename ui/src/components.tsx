import { Icon } from "./Icon";
import { money } from "./types";
import type { Item } from "./types";

export function Brand() {
  return (
    <a className="brand" href="/" aria-label="Minimera home">
      <img
        className="brand-wordmark"
        src="/brand/wordmark.svg"
        width="179"
        height="40"
        alt=""
      />
      <img
        className="brand-mark"
        src="/brand/mark.svg"
        width="44"
        height="40"
        alt=""
      />
    </a>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <span className={`badge ${tone}`}>
      <span className="badge-dot" />
      {children}
    </span>
  );
}
export function Product({
  item,
  removed = false,
}: {
  item: Item;
  removed?: boolean;
}) {
  return (
    <div className={`product ${removed ? "removed" : ""}`}>
      <div className={`product-art ${item.sku === "POUCH" ? "pouch" : "tote"}`}>
        <svg viewBox="0 0 64 72" fill="none" aria-hidden="true">
          {item.sku === "POUCH" ? (
            <>
              <path d="M9 23h46l3 31H6l3-31Z" fill="#9aab94" stroke="#61775f" />
              <path d="M9 23h46M10 28h44" stroke="#435b45" strokeWidth="2" />
              <path d="M47 23v9" stroke="#435b45" strokeWidth="2" />
              <rect x="28" y="37" width="11" height="7" rx="1" fill="#e7eadf" />
            </>
          ) : (
            <>
              <path
                d="M13 24h38l4 38H9l4-38Z"
                fill="#e2dac6"
                stroke="#b2a58c"
              />
              <path
                d="M22 30V18a10 10 0 0 1 20 0v12"
                stroke="#8b8068"
                strokeWidth="3"
              />
              <path
                d="m13 25 5 33h29l4-33M18 58l-8 3M47 58l7 3"
                stroke="#c0b398"
              />
              <rect x="26" y="37" width="12" height="9" rx="1" fill="#f7f4ec" />
              <path d="M29 40h6M29 43h4" stroke="#9b8e75" />
            </>
          )}
        </svg>
      </div>
      <div>
        <strong>{item.name}</strong>
        <small>
          {item.sku === "TOTE" ? "Canvas · Natural" : "Canvas · Olive"}{" "}
          <span>× {item.quantity}</span>
        </small>
      </div>
      <b>{money(item.cents * item.quantity)}</b>
      {removed && <span className="removed-label">Removed</span>}
    </div>
  );
}
export function Address({
  destination,
  compact = false,
}: {
  destination: string;
  compact?: boolean;
}) {
  return (
    <div className={`address ${compact ? "compact" : ""}`}>
      <Icon name="pin" size={17} />
      <div>
        <strong>
          {destination === "office" ? "Office · Boston" : "Home · New York"}
        </strong>
        {!compact && (
          <span>
            {destination === "office"
              ? "456 Demo Avenue, Boston, MA 02108"
              : "123 Test Street, New York, NY 10001"}
          </span>
        )}
      </div>
    </div>
  );
}
