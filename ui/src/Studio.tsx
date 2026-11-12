import { useEffect, useMemo, useRef, useState } from "react";
import { AgStudio, AgStudioProvider, createWidgets } from "ag-studio-react";
import type { AgWidgetDefinition } from "ag-studio-react";
import { AgStudioAiModule, createAiHarness, studioTheme } from "ag-studio";
import type {
  AgAiAgentRun,
  AgStudioProperties,
  AgStudioApi,
  AgReportState,
  AgDefaultRegistry,
  AgDefaultWidgetDefinition,
} from "ag-studio";
import { Icon } from "./Icon";
import { SourceComparison } from "./OrderScene";
import {
  adviceLabel,
  paymentStatus,
  requestLabel,
  workflow,
} from "./presentation";
import { api } from "./api";
import { fulfillment, money, pretty, total } from "./types";
import type { View } from "./types";

type Context = {
  view: View;
  onOpenCase: () => void;
  onOpenEvidence: () => void;
  onOpenContext: () => void;
};
function DecisionWidget({ context }: { context: Context }) {
  const { workspace: ws } = context.view;
  return (
    <div className="studio-decision">
      <p className="eyebrow">Current workflow state</p>
      <h3>{ws.change ? workflow(ws).title : "Ready for a customer request"}</h3>
      <p>
        {ws.change?.explanation ||
          "Open the order to explore a customer request and its payment consequences."}
      </p>
      <button className="button primary" onClick={context.onOpenCase}>
        Open order #{ws.order.id}
        <Icon name="arrow" size={16} />
      </button>
      <p className="caption">
        Approvals and payment execution stay in the merchant workflow.
      </p>
    </div>
  );
}
function ComparisonWidget({ context }: { context: Context }) {
  return (
    <div className="studio-comparison">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Order comparison</p>
          <h3>What needs to stay in sync?</h3>
        </div>
        <button className="text-button" onClick={context.onOpenEvidence}>
          Evidence
          <Icon name="arrow" size={14} />
        </button>
      </div>
      <SourceComparison ws={context.view.workspace} compact />
      <div className="studio-context-link">
        <Icon name="lock" size={15} />
        <span>{adviceLabel(context.view.workspace.change?.advice)}</span>
        <button className="text-button" onClick={context.onOpenContext}>
          Inspect model context
          <Icon name="arrow" size={13} />
        </button>
      </div>
    </div>
  );
}
const comparisonWidget: AgWidgetDefinition<"order-comparison"> = {
  id: "order-comparison",
  label: "Order & payment comparison",
  comp: ComparisonWidget,
  form: (params) => params.createDefaults({ dataMappingItems: [] }),
  defaultSize: { width: 750, height: 270 },
  minSize: { width: 320, height: 240 },
};
const decisionWidget: AgWidgetDefinition<"integrity-decision"> = {
  id: "integrity-decision",
  label: "Integrity decision",
  comp: DecisionWidget,
  form: (params) => params.createDefaults({ dataMappingItems: [] }),
  defaultSize: { width: 440, height: 300 },
  minSize: { width: 250, height: 180 },
};
interface Registry extends Omit<AgDefaultRegistry, "widgets"> {
  widgets: readonly (
    | AgDefaultWidgetDefinition
    | AgWidgetDefinition<"integrity-decision">
    | AgWidgetDefinition<"order-comparison">
  )[];
}
const widgets = createWidgets<Registry>({
  additionalTypes: [decisionWidget, comparisonWidget],
});
const theme = studioTheme.withParams({
  accentColor: "#6e32c9",
  backgroundColor: "#ffffff",
  foregroundColor: "#18181b",
  subtleTextColor: "#626269",
  borderColor: "#e3e3e7",
  borderRadius: 2,
  fontFamily: "IBM Plex Sans, sans-serif",
  fontSize: 13,
  gridHeaderBackgroundColor: "#fafafa",
  gridHeaderTextColor: "#626269",
  gridHeaderFontWeight: 500,
  gridWrapperBorderRadius: 2,
  studioPanelContainerBackgroundColor: "#fafafa",
  studioPanelContainerBorderRadius: 2,
  studioWidgetBorderRadius: 2,
  studioWidgetShadow: "none",
  studioAiPanelInputMessageBackgroundColor: "#f2ecfb",
});
const responsiveLayout: NonNullable<
  AgStudioProperties["responsiveLayoutBreakpoints"]
> = [
  {
    maxWidth: 650,
    layout: (candidates, { columns }) => {
      let row = 0;
      return candidates.map(({ layout }) => {
        const ySpan =
          layout.xSpan === columns ? 43 : Math.max(26, layout.ySpan);
        const next = {
          ...layout,
          xTrack: 0,
          yTrack: row,
          xSpan: columns,
          ySpan,
        };
        row += ySpan;
        return next;
      });
    },
  },
];

export default function Studio({
  view,
  onOpenCase,
  onOpenEvidence,
  onOpenContext,
}: {
  view: View;
  onOpenCase: () => void;
  onOpenEvidence: () => void;
  onOpenContext: () => void;
}) {
  const [edit, setEdit] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(window.innerWidth);
  const compact = viewportWidth <= 900;
  const [analystOpen, setAnalystOpen] = useState(false);
  const studioApi = useRef<AgStudioApi | null>(null);
  const studioFrame = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const frame = studioFrame.current;
    if (!frame) return;
    // Studio 3.1 creates this scroll container without a keyboard focus target.
    // Observe replacements when the chat panel or conversation is recreated.
    const enableConversationFocus = () => {
      for (const transcript of frame.querySelectorAll<HTMLElement>(
        ".ag-studio-ai-scroll-content",
      )) {
        transcript.tabIndex = 0;
        transcript.setAttribute("role", "region");
        transcript.setAttribute("aria-label", "Analyst conversation");
      }
    };
    enableConversationFocus();
    const observer = new MutationObserver(enableConversationFocus);
    observer.observe(frame, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const changed = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", changed);
    return () => window.removeEventListener("resize", changed);
  }, []);
  useEffect(() => {
    const current = studioApi.current;
    if (!current) return;
    const state = current.getState();
    current.setState({
      ...state,
      panels: {
        ...state.panels,
        ai: {
          ...state.panels?.ai,
          width: compact
            ? Math.max(220, Math.min(350, viewportWidth - 58))
            : 350,
        },
      },
    });
  }, [compact, viewportWidth, analystOpen, edit]);
  const latest = useRef(view);
  latest.current = view;
  const ws = view.workspace;
  const data = useMemo(
    () => ({
      sources: [
        {
          id: "orders",
          data: [
            {
              Order: ws.order.id,
              Request: requestLabel(ws),
              State: ws.change
                ? pretty(ws.change.state)
                : paymentStatus(ws.order.payment?.capture_status),
              Original: money(total(ws.order.items)),
              Replacement: ws.change ? money(total(ws.change.items)) : "—",
              Fulfillment: pretty(fulfillment(ws)),
              Source:
                ws.mode === "sandbox" ? "PayPal Sandbox" : "Local simulator",
            },
          ],
        },
        {
          id: "events",
          data: ws.events.map((e) => ({
            Step: e.sequence,
            Actor: pretty(e.actor),
            Action: pretty(e.action),
            Detail: e.detail,
            Time: new Date(e.at).toLocaleTimeString(),
          })),
        },
      ],
    }),
    [ws.revision],
  );
  const initialState = useMemo<AgReportState<Registry>>(
    () => ({
      pages: [
        {
          id: "integrity",
          name: "Order integrity",
          layout: { minWidth: 0, rowHeight: 16 },
          widgets: {
            comparison: { type: "order-comparison", dataMapping: {} },
            decision: { type: "integrity-decision", dataMapping: {} },
            trail: {
              type: "grid",
              format: {
                title: { text: "Order activity & observations", enabled: true },
              },
              dataMapping: {
                cols: [
                  { id: "events.Step" },
                  { id: "events.Actor" },
                  { id: "events.Action" },
                  { id: "events.Detail" },
                ],
              },
            },
          },
          widgetLayout: {
            comparison: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 18 },
            decision: { xTrack: 0, yTrack: 18, xSpan: 10, ySpan: 28 },
            trail: { xTrack: 10, yTrack: 18, xSpan: 14, ySpan: 28 },
          },
        },
      ],
      selectedPageId: "integrity",
      panels: {
        ai: {
          width: compact
            ? Math.max(220, Math.min(350, window.innerWidth - 58))
            : 350,
        },
      },
    }),
    [],
  );
  const ai = useMemo<NonNullable<AgStudioProperties["ai"]>>(
    () =>
      ({ api: studioApi }) => {
        const run: AgAiAgentRun = async function* (input, ctx) {
          const { threadId, runId } = input;
          yield { type: "RUN_STARTED", threadId, runId };
          try {
            const question =
              [...input.messages]
                .reverse()
                .find((m) => m.role === "user")
                ?.content.toLowerCase() || "";
            // Free text stays in the browser. Only an allowlisted intent reaches the server.
            const intent = /privacy|data|model|receive/.test(question)
              ? "privacy"
              : /next|step|now|do i/.test(question)
                ? "next_step"
                : "explain";
            const result = await api<{ answer: string; source: string }>(
              "/assistant",
              {
                method: "POST",
                headers: { "X-Minimera-CSRF": latest.current.csrf },
                body: JSON.stringify({ question: intent }),
                signal: ctx.signal,
              },
            );
            if (ctx.signal?.aborted) return;
            const messageId = crypto.randomUUID();
            yield { type: "TEXT_MESSAGE_START", messageId, role: "assistant" };
            yield {
              type: "TEXT_MESSAGE_CONTENT",
              messageId,
              delta:
                result.answer +
                "\n\nSource: " +
                pretty(result.source) +
                ". This analyst explains the current request; approvals stay in the merchant workflow.",
            };
            yield { type: "TEXT_MESSAGE_END", messageId };
            yield { type: "RUN_FINISHED", threadId, runId };
          } catch (error) {
            if (ctx.signal?.aborted) return;
            yield {
              type: "RUN_ERROR",
              message:
                error instanceof Error
                  ? error.message
                  : "The analyst is unavailable.",
            };
          }
        };
        // Studio 3.1 exposes a core API in the setup type, while the browser harness
        // requires its richer browser API. This component runs only in that browser.
        if (!("getState" in studioApi))
          throw new Error("The browser Studio API is required.");
        return createAiHarness(studioApi as AgStudioApi, () => ({
          agents: [
            {
              id: "minimera",
              name: "Integrity analyst",
              description:
                "Explains the current change, model data exposure and next workflow step. No payment capability.",
              run,
            },
          ],
          primary: "minimera",
          promptStarters: [
            { label: "Explain this decision", prompt: "Explain this decision" },
            {
              label: "What data does the model receive?",
              prompt: "What data does the model receive?",
            },
            {
              label: "What is the next step?",
              prompt: "What is the next step?",
            },
          ],
        }));
      },
    [],
  );
  return (
    <>
      <section className="studio-intro">
        <div>
          <h2>Order sources and current state</h2>
          <p>
            Compare the request with the payment, inspect the event trail, or
            ask the analyst to explain the current plan.
          </p>
          <small>
            Ask about the decision, model context or next step. Approvals and
            payment execution stay in the order workflow.
          </small>
        </div>
        <div className="studio-intro-actions">
          {compact && (
            <button
              className="button"
              aria-expanded={analystOpen}
              onClick={() => {
                setAnalystOpen(!analystOpen);
                setEdit(false);
              }}
            >
              {analystOpen ? "Back to dashboard" : "Ask the analyst"}
              <Icon name="user" size={15} />
            </button>
          )}
          <button
            className="button"
            onClick={() => {
              setEdit(!edit);
              setAnalystOpen(false);
            }}
          >
            {edit ? "Finish arranging" : "Arrange dashboard"}
            <Icon name="grid" size={15} />
          </button>
        </div>
      </section>
      <div className="studio-frame" ref={studioFrame}>
        <AgStudioProvider
          modules={[AgStudioAiModule]}
          licenseKey={
            import.meta.env.VITE_AG_STUDIO_LICENSE_KEY?.trim() || undefined
          }
        >
          <AgStudio
            style={{ height: "100%", width: "100%" }}
            data={data}
            initialState={initialState}
            context={{ view, onOpenCase, onOpenEvidence, onOpenContext }}
            widgets={widgets}
            mode={!compact || edit || analystOpen ? "edit" : "view"}
            onApiReady={({ api }) => {
              if ("getState" in api) studioApi.current = api as AgStudioApi;
            }}
            responsiveLayoutBreakpoints={responsiveLayout}
            panels={{
              edit: {
                right: compact
                  ? analystOpen
                    ? ["ai"]
                    : edit
                      ? ["edit", "data"]
                      : []
                  : edit
                    ? ["ai", "edit", "data"]
                    : ["ai"],
              },
              view: { right: [] },
            }}
            theme={theme}
            ai={ai}
          />
        </AgStudioProvider>
      </div>
    </>
  );
}
