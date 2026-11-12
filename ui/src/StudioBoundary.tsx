import { Component } from "react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

export class StudioBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="card studio-failure" role="alert">
        <Icon name="alert" size={24} />
        <h2>Operations studio could not load</h2>
        <p>
          Your saved order and approvals remain available. Reload to reconnect,
          or continue in Order integrity.
        </p>
        <div className="studio-recovery-actions">
          <button
            className="button primary"
            onClick={() => window.location.reload()}
          >
            Reload workspace
          </button>
          <a className="button" href="#review">
            Return to order
          </a>
        </div>
      </section>
    );
  }
}
