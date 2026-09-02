# Billing extension example

This is an example of a domain-specific extension distilled from the source project. Load it only for billing/subscription work.

- Money conservation and rounding invariants.
- Payment/cancellation/refund ledger consistency.
- Provider status mapping and unknown-status handling.
- Webhook duplicate delivery, ordering, reconciliation, and replay.
- Coupling between subscription state and payment state.
- Recovery after provider-side cancellation or ambiguous provider responses.
