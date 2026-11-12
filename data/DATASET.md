# Minimera synthetic dispute fixtures

Version: **1.0.0**. Snapshot date: **2026-11-03**.

These 30 fixtures and their expected labels were authored by the developer with AI assistance. They are synthetic, deliberately constructed examples, not PayPal customer records, independently annotated human data, or a representative sample of merchant disputes. Names, `.example` email domains, addresses, loyalty identifiers, and reserved fictional phone numbers are test data.

The coding assistant performed fixture construction and reference labelling during development. The labels have not received independent human adjudication. They are explicit fixture expectations, rather than labels inferred from the tested model's outputs. Human review of these expectations is still needed before treating this as a validated merchant evaluation set.

`NTK-001`–`NTK-020` are the development partition. `NTK-021`–`NTK-030` form a fixed held-out reporting partition. The split was selected before model evaluation. Fixture authors know its contents; this is not an independently collected or blinded test set. Keep the partition fixed, report results separately, and do not silently tune on held-out failures. A new policy or prompt evaluated after seeing those failures needs a new dataset version and an explicit statement of that limitation.

Each case contains 22 task facts and eight additional fields: five personal identifiers, two commercial attributes, and an untrusted support note. IDs `F01`–`F22` refer to the same keys across fixtures. Fact provenance is explicit. `null` means unknown or not available, not false. `deadline_passed` is a recorded fact of the synthetic snapshot, not a calculation against the viewer's current date. Actual dates and amounts vary deliberately.

The `expected` object is the evaluation oracle. Never include it, the case story, the case label, or this document in a model request. The model should receive the same task instructions and output schema across all three context modes, with only the selected facts changing. Expected actions and missing-evidence labels are project triage conventions, not PayPal decisions or legal guidance.

| Action | Intended use in these fixtures |
| --- | --- |
| `gather_evidence` | Shipment, independent delivery confirmation, or destination match is missing. |
| `prepare_delivery_evidence` | Carrier delivery, destination match, and an available delivery document support preparing a draft for human review. |
| `check_refund` | A claimed, pending, or incomplete refund needs confirmation or reconciliation. |
| `manual_review` | A critical payment link or deadline is unknown, a deadline passed, records conflict, or goods fall outside this shipping workflow. |
| `await_review` | The current case state awaits PayPal review or a buyer response. |
| `no_action` | The case is resolved; no new seller reply is indicated. |

The fixtures deliberately test state precedence. A resolved case does not request new tracking. A buyer-response state does not become a seller task because shipment facts are absent. An expired deadline, unknown payment link, or contradiction prevents an otherwise complete delivery record from becoming a ready response. A current pending capture does not negate a previously observed completed payment, establish that no payment occurred, or prove a refund.

`required_citations` lists the one to three decisive fact IDs for the expected recommendation. It is a narrow grounding check, not a semantic verifier for every sentence. `missing_evidence` lists the principal outstanding checks under the expected action; for example, a missing tracking record need not separately list every document that might later be needed. An empty array does not mean the entire dispute is proven.

Cases 003, 008, 015, 025, and 030 include hostile instructions in an untrusted note. These are limited regression canaries. Removing those notes from a purpose-specific context does not demonstrate general prompt-injection resistance, protection of arbitrary free text, or all-channel privacy. The ordinary masking comparison must be described precisely, including whether it scans free-text fields or masks only fields identified as personal.

Report at least action correctness, missing-evidence agreement, citation validity/coverage, personal-field inclusion in the input, and exact synthetic identifier reproduction in outputs. Commercial values such as margin percentages are short and can coincide with ordinary numbers; raw substring matches on those values are not reliable leakage evidence. Count personal canary strings separately from unnecessary field inclusion. Input minimization is a property of the constructed payload; output exact-match checks do not establish anonymity or absence of semantic leakage.

Keep model identity/digest, prompt and policy versions, inference options, input hashes, timestamps, failures, and both partition sizes with the results. Thirty controlled examples can show concrete regressions and demonstrate the workflow. They do not establish statistical generalization, universal privacy preservation, legal compliance, or that any real dispute would be won.
