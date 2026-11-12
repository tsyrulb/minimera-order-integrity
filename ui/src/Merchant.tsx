import { lazy, Suspense, useEffect, useState } from "react";
import { Brand, Badge } from "./components";
import { Context } from "./Context";
import { Dialog } from "./Dialog";
import { Evidence } from "./Evidence";
import { Icon } from "./Icon";
import { OrderDetails, OrderScene, RecentActivity } from "./OrderScene";
import { workflow } from "./presentation";
import { ScenarioCards, Welcome } from "./Scenarios";
import { StudioBoundary } from "./StudioBoundary";
import { fulfillment } from "./types";
import { useWorkspace } from "./useWorkspace";

const Studio = lazy(() => import("./Studio"));
type Page = "review" | "studio" | "evidence";
const currentPage = (): Page =>
  window.location.hash === "#studio"
    ? "studio"
    : window.location.hash === "#evidence"
      ? "evidence"
      : "review";

export function Merchant() {
  const data = useWorkspace();
  const {
    view,
    status,
    busy,
    error,
    loaded,
    connectionLost,
    refresh,
    post,
    run,
    start,
    requestChange,
  } = data;
  const [page, setPage] = useState<Page>(currentPage);
  const [dialog, setDialog] = useState<
    "scenarios" | "context" | "details" | null
  >(null);
  useEffect(() => {
    const update = () => setPage(currentPage());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const navigate = (next: Page) => {
    window.location.hash = next;
    setPage(next);
  };
  const begin = (scenario: string, mode = "simulation") =>
    start(scenario, mode, () => {
      navigate("review");
      setDialog(null);
    });
  const ws = view?.workspace;
  const change = ws?.change;
  const state = ws ? workflow(ws) : null;
  const primary = () => {
    if (!ws || !view) return null;
    if (!ws.order.payment)
      return (
        <a className="button primary" href={view.buyer_url}>
          Make the Sandbox test payment
          <Icon name="external" size={17} />
        </a>
      );
    if (!change)
      return (
        <button
          className="button primary"
          onClick={requestChange}
          disabled={!!busy}
        >
          Try the customer request
          <Icon name="arrow" size={17} />
        </button>
      );
    if (change.state === "review")
      return (
        <button
          className="button primary"
          disabled={!!busy}
          onClick={() =>
            run("Rechecking the order and saving approval", () =>
              post("/approve", { snapshot_hash: change.snapshot_hash }),
            )
          }
        >
          <Icon name="check" size={17} />
          Approve this plan
        </button>
      );
    if (["approved", "awaiting_buyer"].includes(change.state))
      return (
        <a className="button primary" href={view.buyer_url}>
          Continue as buyer
          <Icon name="arrow" size={17} />
        </a>
      );
    if (change.state === "complete" && fulfillment(ws) === "ready")
      return (
        <button
          className="button primary"
          disabled={!!busy}
          onClick={() =>
            run("Verifying before warehouse release", () => post("/release"))
          }
        >
          Release corrected order
          <Icon name="arrow" size={17} />
        </button>
      );
    if (
      change.state === "pending" ||
      (change.state === "indeterminate" &&
        change.refund?.status === "UNVERIFIED")
    )
      return (
        <button
          className="button primary"
          disabled={!!busy}
          onClick={() =>
            run("Verifying the known refund and approved plan", () =>
              post("/resume"),
            )
          }
        >
          <Icon name="refresh" size={17} />
          {change.state === "pending"
            ? "Check refund status"
            : "Verify refund and continue"}
        </button>
      );
    if (change.state === "processing")
      return (
        <button className="button primary" disabled>
          <span className="spinner" />
          Verifying payment outcomes
        </button>
      );
    if (change.state === "indeterminate")
      return (
        <button className="button primary" onClick={() => navigate("evidence")}>
          Inspect known payment IDs
          <Icon name="document" size={17} />
        </button>
      );
    return (
      <button className="button primary" onClick={() => setDialog("scenarios")}>
        Try another scenario
        <Icon name="arrow" size={17} />
      </button>
    );
  };
  const testWarehouse = () =>
    run("Checking a changed warehouse state", async () => {
      await post("/simulate-warehouse-change");
      await post("/recheck");
    });
  const recheck = () =>
    run("Checking the current order and approval", () => post("/recheck"));

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to order workspace
      </a>
      <aside className="sidebar">
        <Brand />
        <div className="workspace-switch">
          <span className="store-avatar">N</span>
          <div>
            <strong>Northline Goods</strong>
            <small>Demo merchant</small>
          </div>
        </div>
        <p className="nav-heading">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {(
            [
              ["review", "shield", "Order integrity"],
              ["studio", "grid", "Operations studio"],
              ["evidence", "document", "Evidence trail"],
            ] as const
          ).map(([id, icon, label]) => (
            <a
              key={id}
              className={`nav-item ${page === id ? "active" : ""}`}
              href={`#${id}`}
              aria-label={label}
              aria-current={page === id ? "page" : undefined}
            >
              <Icon name={icon} size={19} />
              <span>{label}</span>
              {id === "review" && change?.state === "review" && (
                <b className="nav-count">1</b>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note">
            <Icon name="lock" size={16} />
            <span>
              Demo environment<small>Synthetic customer data</small>
            </span>
          </div>
          <div className="profile">
            <span className="profile-avatar">NG</span>
            <div>
              <strong>Merchant workspace</strong>
              <small>Northline demo store</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Northline Goods</span>
            <Icon name="chevron" size={13} />
            <strong>
              {page === "studio"
                ? "Operations studio"
                : page === "evidence"
                  ? "Evidence trail"
                  : "Order integrity"}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="role-indicator">
              <Icon name="user" size={14} />
              Merchant view
            </span>
            <Badge>
              {ws?.mode === "sandbox"
                ? "PayPal Sandbox · test funds"
                : "Demo simulation"}
            </Badge>
          </div>
        </header>
        <main id="main-content" className="main-content">
          <div
            className={`page-heading ${!view && loaded ? "welcome-page-heading" : ""}`}
          >
            <div>
              <p className="eyebrow">
                {page === "studio"
                  ? "Operations"
                  : page === "evidence"
                    ? "Audit & traceability"
                    : view
                      ? `Order ${ws!.order.id}`
                      : "Minimera"}
              </p>
              <h1>
                {page === "studio"
                  ? "Operations studio"
                  : page === "evidence"
                    ? "Evidence trail"
                    : state?.title || "Order integrity"}
              </h1>
              {page !== "review" && (
                <p className="page-subtitle">
                  {page === "studio"
                    ? "Explore this order, its evidence and the reasoning behind the plan."
                    : "Follow the request, approvals and separately verified payment outcomes."}
                </p>
              )}
            </div>
            <div className="page-actions">
              {view && (
                <button
                  className="icon-button"
                  aria-label="Refresh workspace"
                  title="Refresh workspace"
                  disabled={!!busy}
                  onClick={() =>
                    run("Refreshing the current workspace", refresh)
                  }
                >
                  <Icon name="refresh" size={17} />
                </button>
              )}
              <button
                className="button small"
                aria-label="Explore scenarios"
                onClick={() => setDialog("scenarios")}
              >
                <Icon name="grid" size={16} />
                Explore scenarios
              </button>
            </div>
          </div>
          {error && (
            <div className="notice error" role="alert">
              <Icon name="alert" size={18} />
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={data.clearError}
              >
                <Icon name="close" size={17} />
              </button>
            </div>
          )}
          {connectionLost && (
            <div className="notice warning" role="status">
              <Icon name="clock" size={18} />
              <span>Connection interrupted. Showing the last saved state.</span>
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
          {!loaded ? (
            <div className="loading-state" role="status">
              <span className="spinner" />
              Opening your local workspace…
            </div>
          ) : !view ? (
            <Welcome
              start={begin}
              busy={busy}
              sandbox={status.sandbox_enabled}
            />
          ) : page === "studio" ? (
            <StudioBoundary>
              <Suspense
                fallback={
                  <div className="loading-state" role="status">
                    Opening the operations studio…
                  </div>
                }
              >
                <Studio
                  view={view}
                  onOpenCase={() => navigate("review")}
                  onOpenEvidence={() => navigate("evidence")}
                  onOpenContext={() => setDialog("context")}
                />
              </Suspense>
            </StudioBoundary>
          ) : page === "evidence" ? (
            <Evidence view={view} />
          ) : (
            <>
              <OrderScene
                view={view}
                primary={primary()}
                busy={busy}
                onContext={() => setDialog("context")}
                onAnalyze={() =>
                  run("Reviewing the minimized context", () => post("/analyze"))
                }
                onDetails={() => setDialog("details")}
                onScenario={() => setDialog("scenarios")}
                onWarehouseTest={testWarehouse}
                onRecheck={recheck}
              />
              <RecentActivity
                view={view}
                onEvidence={() => navigate("evidence")}
              />
              <p className="scope-note">
                <Icon name="document" size={14} />
                <span>
                  PayPal determines Seller Protection eligibility. This workflow
                  checks order consistency.{" "}
                  <a
                    href="https://www.paypal.com/il/legalhub/paypal/seller-protection"
                    target="_blank"
                    rel="noreferrer"
                  >
                    See the full terms ↗
                  </a>
                </span>
              </p>
            </>
          )}
        </main>
        <footer className="page-footer">
          <span>Minimera · Order Integrity</span>
          <span>Local demo with synthetic customer data</span>
        </footer>
      </div>
      {dialog && (
        <Dialog
          onClose={() => setDialog(null)}
          labelledBy="dialog-title"
          className={dialog === "scenarios" ? "scenario-modal" : "detail-modal"}
        >
          <button
            className="icon-button modal-close"
            aria-label="Close dialog"
            onClick={() => setDialog(null)}
          >
            <Icon name="close" />
          </button>
          <div className="dialog-heading">
            <p className="eyebrow">
              {dialog === "scenarios"
                ? "Interactive demo"
                : dialog === "context"
                  ? "Model context"
                  : "Order details"}
            </p>
            <h2 id="dialog-title">
              {dialog === "scenarios"
                ? "Choose a scenario"
                : dialog === "context"
                  ? "What the model receives"
                  : `The request behind order #${ws?.order.id || "NL-1042"}`}
            </h2>
            {dialog === "scenarios" && (
              <p>
                Choose an interactive example. Each starts a separate workspace
                and preserves earlier evidence.
              </p>
            )}
          </div>
          {dialog === "scenarios" ? (
            <>
              <ScenarioCards start={begin} busy={busy} />
              {status.sandbox_enabled && (
                <button
                  className="button sandbox-start"
                  disabled={!!busy}
                  onClick={() => begin("address_change", "sandbox")}
                >
                  Use PayPal Sandbox · $1.00 test order
                  <Icon name="external" size={16} />
                </button>
              )}
            </>
          ) : view ? (
            dialog === "context" ? (
              <Context view={view} />
            ) : (
              <OrderDetails view={view} />
            )
          ) : null}
        </Dialog>
      )}
    </div>
  );
}
