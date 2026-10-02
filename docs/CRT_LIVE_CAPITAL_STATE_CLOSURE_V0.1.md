# CRT Live Capital State Closure V0.1

Current broker facts take precedence over the historical private capital snapshot
for the observed account. USER_CONFIRMED remains the authority for reserves,
roles, plans and capital intent; it is not a label for broker holdings or cash.
Neither source grants trading authority. Formal strategy, Commander, production
approval and external action locks are unchanged.

## Existing interfaces

`broker_capital_observation.capture_ibkr_capital` uses the official IBKR Socket
API and the existing TWS at 127.0.0.1:7496. It requests positions, account summary,
all open orders and account updates using a nonzero client. It requires a single
account, matching account callbacks, accountReady, completed responses, and
matching position/portfolio quantities and costs. No order submission,
cancellation, binding or what-if request exists. USD stock positions are the
supported initial scope; unsupported position scope fails closed.

The connected official IBKR interface can provide independent observations in
the engineering chat. It is not a configured standalone local runtime client.
Retained independent observations keep their source, retrieval clock and scope;
they are never relabeled as a fresh local Socket connection or merged merely
because values agree. A connected observation cannot declare automatic local
refresh. The Socket collector is available on demand; no scheduler is added.

The daily runner accepts `--observe-broker-capital` or a retained
`--broker-capital-observation` file, plus `--user-capital-intent`. These optional
inputs reuse private context, Evidence Pack, plan drift, GPT Handoff and outbox.
The existing profile loader also discovers `broker-capital-observation.json` and
`capital-intent.json` beside the private profile, so retained current capital is
available to existing callers without rewriting the historical ledger. Loading
these files never refreshes their source clocks or opens a broker connection;
the daily pack rechecks their freshness at its own evaluation clock.
Account/order identifiers are kept only in callback memory. An allowlist precedes
proof hashing and export; raw responses, credentials and private paths do not
enter the broker observation or minimized bridge.

## Source and time qualification

Proofs retain their capture start/end and sanitized content hash. Runtime intake
and bridge construction validate scope and hash, reject future/reversed clocks
and snapshots spanning over 30 seconds, and label observations older than five
minutes STALE. Missing/incomplete sources are BLOCKED/PARTIAL for capital facts;
there is no fallback that presents historical holdings as current. These states
do not veto unrelated investment analysis. Values retain their scope and state.

SettledCash is optional for general capital analysis. Its absence is an explicit
settlement-dependent execution limitation. CashBalance, TotalCashValue and
AvailableFunds are separately named facts, not additive amounts; BASE is never
added to USD and BuyingPower is never cash. Unknown settlement-date semantics
are not silently aliased. Actual execution requires a fresh, independently
authorized check of amounts, settlement, fees and financing.

## Reconciliation

The original USER_CONFIRMED file and its internal STRC equality check remain
intact. The in-memory current projection sets both holdings and `strc.shares`
from broker quantity; historical STRC quantity and date remain explicitly
historical. Cost basis is quantity times broker average cost, not market value.
Any retained cash-goal arithmetic labels its rate/goal as historical inputs.

A separately supplied USER_CONFIRMED intent requires a confirmation clock,
nonnegative `reserved_usd`, and `plan_policy=CANCEL_ALL_NO_REPLACEMENT` for this
dispatch. It clears historical plans without adding their budgets to cash or
creating replacements. Roles are included only when separately confirmed;
missing roles and trade authorization remain visible limitations. No old
reserve, plan, role or execution approval is automatically inherited.

For completed USD source data, analysis budget is:

`max(0, min(cash - remaining buy-limit commitments, AvailableFunds) - reserved)`.

This avoids subtracting commitments again from AvailableFunds, which may already
reflect them. Filled quantities are not charged again. Remaining sell orders
reduce available position quantity and never create cash proceeds. Unresolved
fill alignment or non-limit buy occupancy blocks a precise budget, while the
observed holdings/cash remain available for analysis. Fees and financing still
require an execution check. A missing reserve confirmation also withholds the
budget; a cancelled plan is never counted as money.
The existing portfolio amount calculation also treats observed broker cash as
gross cash, with the user reserve inside that balance; it never adds the reserve
again. Historical profiles retain their separate available/reserved convention.

The minimized bridge carries current holdings/costs, separate funds, both source
clocks, proof hash, cancelled-plan semantics, historical STRC comparison,
analysis budget, remaining orders and execution limitations inside its existing
`capital_state` section. The 16,384-byte ceiling and transport authority remain
unchanged; oversized decision-critical context still fails closed.
