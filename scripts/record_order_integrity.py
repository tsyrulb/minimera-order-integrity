"""Explicitly record bounded Bedrock reviews for synthetic Order Integrity contexts."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ntk.config import Settings
from ntk.dataset import ROOT
from ntk.integrity.contracts import ChangeRequest, NewWorkspace
from ntk.integrity.model import Analyst
from ntk.integrity.policy import fingerprint
from ntk.integrity.service import IntegrityService
from ntk.integrity.store import Store
from ntk.storage import atomic_json


async def record() -> None:
    config = Settings.from_env()
    directory = ROOT / "reports" / "order-integrity-v1"
    store = Store(config.runtime_dir / "order-integrity-v1")
    analyst = Analyst(
        store,
        directory / "recordings",
        fresh=True,
        region=config.model.aws_region,
        profile=config.model.aws_profile,
    )
    service = IntegrityService(store, analyst)
    outcomes = []
    for scenario in ("address_change", "already_shipped"):
        for destination, remove in (
            ("office", True),
            ("office", False),
            ("home", True),
            ("home", False),
        ):
            # These are model-only fixtures; they cause no PayPal writes.
            workspace = await service.create(NewWorkspace(scenario=scenario))
            workspace = await service.request_change(
                workspace.id, ChangeRequest(destination=destination, remove_pouch=remove)
            )
            change = service.get_change(workspace)
            for origin in ("simulator", "paypal_sandbox"):
                fixture = change.model_copy(deep=True)
                fixture.facts[0].source = origin
                answer = await analyst.review(fixture)
                outcomes.append(
                    {
                        "scenario": scenario,
                        "destination_changed": destination == "office",
                        "remove_item": remove,
                        "payment_fact_origin": origin,
                        "expected_route": fixture.route,
                        "observed_route": answer.plan.route if answer.plan else None,
                        "policy_agrees": answer.policy_agrees,
                        "request_hash": answer.request_hash,
                        "delivery": answer.source,
                    }
                )
                print(
                    f"{scenario} / address={destination} / remove={remove} / {origin}: {answer.source}, policy_agrees={answer.policy_agrees}",
                    flush=True,
                )
    atomic_json(
        directory / "model-fixtures.json",
        {
            "schema": "order-integrity-model-fixtures/1.0.0",
            "synthetic": True,
            "independent_evaluation": False,
            "description": "Developer-authored functional fixtures, not a blinded benchmark or production performance estimate. paypal_sandbox denotes the expected fact-origin label in these model-only fixtures, not a live payment observation.",
            "fixtures": outcomes,
            "hash": fingerprint(outcomes),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enable-bedrock",
        action="store_true",
        required=True,
        help="Explicitly allow provider calls, up to the persisted 30-attempt experiment limit.",
    )
    parser.parse_args()
    asyncio.run(record())


if __name__ == "__main__":
    main()
