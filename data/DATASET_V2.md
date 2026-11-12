# Synthetic reporting variants v2

The immutable snapshot is `cases-v2.json`, version `ntk-fixtures/2.0.0`, created on 2026-11-05. The JSON records its creation time before any model calls on its new reporting variants. Original `cases.json`, `PROTOCOL.json` and all earlier observations remain unchanged.

## Development and reporting

The 20 original development cases are copied without changes. Their action and missing-evidence labels were checked against a separately executable, explicit project routing rubric. All 20 agreed. See `reports/development-label-audit-20261105.json`. Citation choices need not be unique; that audit checks action and missing-evidence sets, not identical wording or fact selections.

Ten new reporting variants use IDs NTK-031 through NTK-040. They vary amounts, currencies, state precedence and combinations of refund, deadline and delivery facts. Their fact IDs and order are permuted, so a model cannot rely on the development set's fixed F-number-to-key mapping. The representation and context policy are otherwise the same in all three modes. Original reporting cases NTK-021 through NTK-030 are absent from this snapshot.

The routing prompt is selected using development outputs only. The new reporting variants are evaluated after that selection, with a fixed prompt, model, schema, policy and generation settings across modes. The protocol records all planned request hashes before generation. Mode order rotates, failures remain in the denominators and the original quality gates are retained.

## What the references mean

These cases and reference labels are developer authored with AI assistance. The creator knows their content. They are not independently collected, human-adjudicated or blinded. They are newly constructed variants of known routing rules, not evidence of generalization to unrelated merchant data. Programmatic consistency with a rubric does not establish that the rubric is the correct policy for a real merchant.

`ntk/reference.py` is an evaluation-only oracle for this project rubric. It is never called by inference, context projection or report delivery and never replaces a model response. New reference actions and missing-evidence lists are calculated before model generation. Neither the references, case story nor case label is included in the model request.

The priority order is: closed case; waiting on another party; critical blocker or unsupported goods; incomplete/unverified refund; complete carrier delivery evidence; otherwise gather the principal outstanding shipment evidence. Unsupported goods require manual review without inventing a missing shipping document. A `MERCHANT_CLAIMED` refund needs confirmation. A `COMPLETED` refund whose amount is smaller than the disputed amount still needs reconciliation. This is an internal synthetic routing convention, not PayPal policy, legal advice or a prediction of dispute outcome.

Human review of the rubric and labels is still needed before making claims about real merchant usefulness. The sample size remains small. Report development and reporting scores separately; a passed project gate is not certification, anonymity or a production-readiness guarantee.

## Frozen reporting coverage

| Case | Boundary being exercised |
| --- | --- |
| NTK-031 | Closed state overrides payment, deadline and refund issues. |
| NTK-032 | Buyer-response state overrides delivery mismatch and pending refund. |
| NTK-033 | An unknown capture link blocks refund/shipment triage. |
| NTK-034 | An unknown response window blocks otherwise complete delivery evidence. |
| NTK-035 | Contradictory delivery evidence takes precedence over a pending refund. |
| NTK-036 | A merchant-claimed refund needs confirmation despite available delivery evidence. |
| NTK-037 | A completed partial refund is not a full repayment. |
| NTK-038 | Complete carrier-backed delivery evidence supports preparation. |
| NTK-039 | A delivery document with unknown destination needs a destination check. |
| NTK-040 | An in-transit carrier record is not delivered evidence. |
