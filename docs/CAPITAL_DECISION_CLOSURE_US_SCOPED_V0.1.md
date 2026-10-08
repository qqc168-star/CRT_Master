# Capital Decision Closure — US Securities Scoped

Construction base: `5519a613be9b829eb6518942494f68f2363dee92`.

## Pre-construction plan

Add one terminal, predominantly pure module, `capital_decision_closure.py`.
Keep Commander and its structured observation contract unchanged. Extend the
existing Responses adapter, transport worker and notification boundary with an
explicit versioned capital request. Reuse their durable send marker, response
storage, delivery lock and notification deduplication. Never execute trades.

The validator checks GPT-selected actions; it never selects or repairs a strategy.
Trade legs alone own quantity/capital arithmetic. A rotation buy remains dependent
until a new broker snapshot, settlement evidence and new judgment validate it.
The presenter renders only the validated object and checks current source lineage
again at presentation, independently of transport/notification deduplication.

Validation: deterministic acceptance matrix, integration with the existing worker
and notification path, synthetic offline provider responses, targeted tests,
full regression, registry, read-only scan, git status and diff check.
Real provider delivery and model semantic acceptance require separate approval.

## Source semantics investigated before implementation

IBKR's [account value keys](https://www.interactivebrokers.com/docs/tws-api/doc/account-portfolio-data/account-updates/account-value-keys)
distinguish securities, commodities and account totals. CashBalance is trade-date
cash and may include futures PNL. AvailableFunds-S is equity with loan value less
initial margin; it is not proof of unborrowed, settled dollars.
The [official account summary API](https://interactivebrokers.github.io/tws-api/classIBApi_1_1EClient.html)
defines SettledCash after trade-date purchases, commissions, taxes and fees.
Neither definition establishes a particular account's restrictions or proves
whether its AvailableFunds already includes every open order.

Current `broker_capital_observation.py` deliberately preserves an **analysis**
budget, with no settlement guarantee. It records USD funds, STK holdings and
remaining orders, but does not retain account/segment semantics, restricted cash,
other-currency borrowing, position restrictions or commission upper bounds.
Those missing proofs must not be silently treated as zero or inferred from
AvailableFunds. Cancellation requests are not disappearance of broker orders.

## Status

Offline Full-Decision Contract and existing transport wiring are complete.
`CRT_CAPITAL_FULL_DECISION_OFFLINE_V0.1` is restricted to injected offline
transport; the real sender rejects capital requests before credentials/network.
The original 16,384-byte Smoke Contract remains unchanged. No new production
capacity limit is approved. Structured capital output remains distinct from
Commander Observation and uses the existing deterministic validator.

The synthetic allocation valuation is derived from the same captured evidence
as the treasury valuation view. Unqualified valuation remains BLOCKED and cannot
support a capital increase, independently of the chosen reference label. Fees
and instrument references can supplement, but cannot replace, bridge or posture
investment evidence. Blocked trades cannot become successful delivery receipts
or notifications. Source seals detect mutation,
not authenticity; model judgment itself is not proven by these offline checks.

For the same event and shared state root, Smoke retains its original paths and
Capital uses the `CRT_CAPITAL_FULL_DECISION_OFFLINE_V0.1` subdirectory. Locks,
responses, receipts and recommendation artifacts use that namespace; notification
identities already include the receipt hash, and receipt lookup selects the
matching namespace. Both delivery orders and repeated delivery/presentation are
tested. Existing unnamespaced capital send records require reconciliation rather
than automatic migration/resend; they are preserved unchanged.

`WAIT + EVIDENCE_BLOCKED` with valid scope, attributed fresh evidence, instrument
qualification, explicit blocker reasons and no trade legs now yields
`VALIDATED_NON_TRADING_WAIT`. This permits only a notice saying not to trade and
to wait for evidence. Source validation failures remain BLOCKED. Unverified
BUY/SELL/ROTATE remain ineligible, including when mixed with a valid waiting
conclusion. Existing stored receipts are not rewritten automatically.

Initial acceptance: 96 targeted tests and 1,301 full offline regression tests
passed. Directed PR #133 repairs passed 106 affected tests and one full offline
regression of 1,307 tests. The prior test-directory isolation failure did not
recur. No capacity analysis was repeated for these repairs. Retained initial
measurement: complete synthetic request body 30,076 UTF-8 bytes; projection
23,964 bytes. The original
23,999-byte projection (SHA-256
`82024692e6ee53d84e407dbe1143c7750d95ea4933cf4d0ae7e5e7dc70f7d6d7`)
is retained only as the unqualified synthetic composition's capacity baseline.
Model tokens and cost: NOT_MEASURED. Model comprehension: NOT_YET_PROVEN.
Production remains NOT_APPROVED; external authority NONE; user capital
authority USER_ONLY; machine execution FORBIDDEN. No real model send or trade
was performed. This change is submitted for review, without merge/deployment.
