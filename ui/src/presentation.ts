import { fulfillment, total } from "./types";
import type { Advice, Workspace } from "./types";

export type Tone = "neutral" | "success" | "warning" | "danger";

export function workflow(ws: Workspace): {
  title: string;
  summary: string;
  tone: Tone;
  step: number;
} {
  const change = ws.change;
  if (!ws.order.payment)
    return {
      title: "Collect the test payment",
      summary:
        "Make a Sandbox test payment, then explore a post-purchase change.",
      tone: "neutral",
      step: 0,
    };
  if (!change)
    return {
      title: "Order details",
      summary:
        "Try a customer request to change the destination and remove one item.",
      tone: "neutral",
      step: 0,
    };
  if (change.route === "no_change")
    return {
      title: "Order unchanged",
      summary:
        "The requested destination and items match the original order. No payment operation is needed.",
      tone: "neutral",
      step: 1,
    };
  if (change.state === "blocked")
    return {
      title: "Order already shipped",
      summary: change.explanation,
      tone: "danger",
      step: 1,
    };
  if (change.state === "stale")
    return {
      title: "Approval no longer valid",
      summary:
        "The saved approval no longer matches the current order. Payment execution is blocked.",
      tone: "danger",
      step: 2,
    };
  if (
    change.state === "indeterminate" &&
    change.refund?.status === "UNVERIFIED"
  )
    return {
      title: "Verify the saved refund",
      summary:
        "The refund ID is saved. Recheck it before capturing the approved replacement; the refund will not be sent again.",
      tone: "warning",
      step: 4,
    };
  if (change.state === "indeterminate")
    return {
      title: "Payment outcome unconfirmed",
      summary:
        "A payment operation has an unconfirmed result. Inspect the known IDs before any further action.",
      tone: "danger",
      step: 4,
    };
  if (change.state === "pending")
    return {
      title: "Waiting for the refund",
      summary:
        "Original refund pending. Replacement capture withheld. Fulfillment stays paused.",
      tone: "warning",
      step: 4,
    };
  if (change.state === "processing")
    return {
      title: "Verifying payment outcomes",
      summary:
        "Refund and replacement capture are verified separately. The warehouse stays paused.",
      tone: "warning",
      step: 4,
    };
  if (change.state === "complete")
    return {
      title:
        fulfillment(ws) === "released"
          ? "Order change completed"
          : "Ready to release",
      summary:
        fulfillment(ws) === "released"
          ? "The corrected address and items are in the synthetic warehouse queue."
          : "Original refund and replacement capture are verified. Review the corrected order before release.",
      tone: "success",
      step: 5,
    };
  if (change.state === "approved" || change.state === "awaiting_buyer")
    return {
      title: "Waiting for buyer approval",
      summary:
        "The buyer reviews the new destination and amount before either payment leg runs.",
      tone: "neutral",
      step: 3,
    };
  return {
    title: "Review order change",
    summary:
      "The request differs from the paid PayPal order. Review a separate refund and replacement payment.",
    tone: "warning",
    step: 2,
  };
}

export function adviceLabel(advice: Advice | null | undefined): string {
  return advice?.source === "recorded_bedrock"
    ? "Recorded Bedrock response"
    : advice?.source === "bedrock"
      ? "Fresh Bedrock response"
      : "AI review unavailable";
}

export function requestLabel(ws: Workspace): string {
  const address = ws.change?.destination !== ws.order.destination;
  const removal = ws.change?.remove_pouch;
  if (!ws.change) return "No request yet";
  return address && removal
    ? "New address · one item removed"
    : address
      ? "New shipping address"
      : removal
        ? "One item removed"
        : "No change requested";
}

export function requestText(ws: Workspace): string {
  if (!ws.change)
    return "Send it to my office, and remove the travel pouch. I only need the tote.";
  return `${ws.change.destination !== ws.order.destination ? "Please send it to my office in Boston." : "Please keep my original home address."} ${ws.change.remove_pouch ? "Remove the travel pouch; I only need the tote." : "Keep both items in the order."}`;
}

export function paymentStatus(status: string | null | undefined): string {
  const states: Record<string, string> = {
    COMPLETED: "Completed",
    REFUNDED: "Refunded",
    PARTIALLY_REFUNDED: "Partially refunded",
    PENDING: "Pending",
    APPROVED: "Buyer approved",
    CREATED: "Created",
    DECLINED: "Declined",
    UNVERIFIED: "Not yet verified",
  };
  return status
    ? states[status] || status.replaceAll("_", " ").toLowerCase()
    : "Not started";
}

export function amounts(ws: Workspace): {
  original: number;
  replacement: number;
  difference: number;
} {
  const original = total(ws.order.items);
  const replacement = ws.change
    ? total(ws.change.items)
    : ws.order.items[0].cents;
  return { original, replacement, difference: original - replacement };
}

export function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
