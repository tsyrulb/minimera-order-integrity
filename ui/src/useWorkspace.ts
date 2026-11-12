import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Status, View } from "./types";

export function useWorkspace() {
  const [view, setView] = useState<View | null>(null);
  const [status, setStatus] = useState<Status>({
    sandbox_enabled: false,
    fresh_ai_enabled: false,
  });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [connectionLost, setConnectionLost] = useState(false);
  const current = useRef<View | null>(null);
  const running = useRef(false);
  const publish = useCallback((next: View) => {
    const previous = current.current;
    if (
      previous?.workspace.id === next.workspace.id &&
      previous.workspace.revision > next.workspace.revision
    ) {
      setConnectionLost(false);
      return previous;
    }
    current.current = next;
    setView(next);
    setConnectionLost(false);
    return next;
  }, []);
  const refresh = useCallback(async () => {
    const expected = current.current?.workspace.id;
    const next = await api<View>("/workspace");
    if (
      expected &&
      current.current &&
      current.current.workspace.id !== expected
    )
      return current.current;
    return publish(next);
  }, [publish]);
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Status>("/status")
        .then((next) => {
          if (active) setStatus(next);
        })
        .catch(() => {
          if (active)
            setError(
              "The local server is unavailable. Reconnect and refresh this page.",
            );
        }),
      api<View>("/workspace")
        .then((next) => {
          if (active) publish(next);
        })
        .catch((error: unknown) => {
          if (
            active &&
            !(
              error instanceof ApiError &&
              error.status === 403 &&
              error.code === "SESSION_REQUIRED"
            )
          )
            setError(
              error instanceof Error
                ? error.message
                : "Unable to open the saved workspace. Refresh to reconnect.",
            );
        }),
    ]).finally(() => {
      if (active) setLoaded(true);
    });
    return () => {
      active = false;
    };
  }, [publish]);
  useEffect(() => {
    if (!view) return;
    const poll = () => refresh().catch(() => setConnectionLost(true));
    const interval = window.setInterval(poll, 3000);
    window.addEventListener("focus", poll);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", poll);
    };
  }, [!!view, refresh]);
  const run = async (label: string, action: () => Promise<unknown>) => {
    if (running.current) return;
    running.current = true;
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The operation could not complete.",
      );
      if (current.current) await refresh().catch(() => setConnectionLost(true));
    } finally {
      running.current = false;
      setBusy("");
    }
  };
  const post = async (path: string, body?: unknown) => {
    if (!current.current) throw new Error("Open a demo workspace first.");
    return publish(
      await api<View>(path, {
        method: "POST",
        headers: { "X-Minimera-CSRF": current.current.csrf },
        body: body ? JSON.stringify(body) : undefined,
      }),
    );
  };
  const submitRequest = async (next: View) => {
    const token = next.buyer_url.split("/").pop()!;
    await api("/buyer/change", {
      method: "POST",
      headers: { "X-Minimera-Buyer": token },
      body: JSON.stringify({ destination: "office", remove_pouch: true }),
    });
    await refresh();
    await post("/analyze");
  };
  const start = async (
    scenario: string,
    mode = "simulation",
    onStarted?: () => void,
  ) =>
    run("Preparing your example", async () => {
      const next = publish(
        await api<View>("/workspaces", {
          method: "POST",
          body: JSON.stringify({ scenario, mode }),
        }),
      );
      onStarted?.();
      if (mode === "simulation") await submitRequest(next);
    });
  const requestChange = () =>
    run("Reviewing the customer request", async () => {
      if (current.current) await submitRequest(current.current);
    });
  return {
    view,
    status,
    loaded,
    busy,
    error,
    connectionLost,
    refresh,
    run,
    post,
    start,
    requestChange,
    clearError: () => setError(""),
  };
}
