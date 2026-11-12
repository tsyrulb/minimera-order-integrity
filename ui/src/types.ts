export type Item = {
  sku: string;
  name: string;
  cents: number;
  quantity: number;
};
export type Payment = {
  order_id: string;
  capture_id: string | null;
  status: string;
  capture_status: string | null;
  cents: number;
  destination: string;
  verified_at: string;
  source: string;
  protection_status: string | null;
};
export type Plan = {
  route: string;
  summary: string;
  steps: string[];
  fact_ids: string[];
  customer_message: string;
};
export type Advice = {
  source: string;
  model: string | null;
  plan: Plan | null;
  request_hash: string;
  policy_agrees: boolean | null;
  prompt_version: string;
};
export type Change = {
  id: string;
  destination: string;
  items: Item[];
  remove_pouch: boolean;
  route: string;
  state: string;
  facts: { id: string; label: string; value: string; source: string }[];
  advice: Advice | null;
  snapshot_hash: string;
  approved_hash: string | null;
  approval_expires: number | null;
  created_at: string;
  explanation: string;
  replacement: Payment | null;
  refund: {
    refund_id: string;
    status: string;
    cents: number;
    verified_at: string;
  } | null;
};
export type Order = {
  id: string;
  revision: number;
  items: Item[];
  destination: string;
  fulfillment: string;
  payment: Payment | null;
};
export type Workspace = {
  id: string;
  revision: number;
  mode: "simulation" | "sandbox";
  scenario: string;
  order: Order;
  fulfillment_order: Order | null;
  change: Change | null;
  events: {
    sequence: number;
    at: string;
    actor: string;
    action: string;
    detail: string;
    hash: string;
  }[];
};
export type View = {
  workspace: Workspace;
  csrf: string;
  buyer_url: string;
  destinations: Record<string, Record<string, string>>;
  model_context: unknown;
};
export type BuyerView = {
  revision: number;
  mode: Workspace["mode"];
  order: Order;
  change:
    | (Pick<Change, "destination" | "items" | "state" | "explanation"> & {
        cents: number;
        refund_status: string | null;
        replacement_status: string | null;
      })
    | null;
};
export type Status = { sandbox_enabled: boolean; fresh_ai_enabled: boolean };
export const money = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
export const total = (items: Item[]) =>
  items.reduce((sum, item) => sum + item.cents * item.quantity, 0);
export const pretty = (text: string) =>
  text.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
export const fulfillment = (ws: Workspace) =>
  ws.fulfillment_order?.fulfillment || ws.order.fulfillment;

export const labels: Record<string, string> = {
  review: "Needs approval",
  approved: "Waiting for buyer",
  awaiting_buyer: "Waiting for buyer",
  processing: "Verifying payments",
  pending: "Refund pending",
  complete: "Payments verified",
  blocked: "Automatic change blocked",
  stale: "Approval invalidated",
  indeterminate: "Reconciliation required",
};
