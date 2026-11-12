# Company source versions

Public company facts enter the existing daily runner through
`--issuer-ct-archive`. The same archive input is now available to
`build_evidence_pack(issuer_ct_archive=...)`. It is mutually exclusive with
normalized CT inputs. The archive reader rechecks original bytes, hashes,
issuer/CIK, accession, source URL, original clocks, exhibit links and any supplied
SEC submissions index. A supplied index is checked even when the document itself
contains its CIK. No new financial model or data provider is introduced.

The original archive is the retained source boundary: it must be acquired through
the authorized official-source capture process. A local content hash proves
integrity, not a SEC digital signature or immunity to an attacker replacing the
entire archive and its acquisition records. Arbitrary normalized metadata,
`VALIDATED`, correction flags and document names are not an archive admission.
The existing normalized research/calculation API does not establish source
authority or seed versions; official-source claims and issuers with a previously
verified version must pass the archive path before their protected fields can
participate in current analysis.

`issuer_fact_history.guard_company_source_versions()` reparses the archive and
stores the verified per-field versions in the existing ObservationStore's
immutable research-event table. No second database or persistent schema is
created. Updates use the existing SQLite transaction and append-only interface.
The recorded validation time is the actual local execution time. The database
and original archives remain trusted local evidence stores, not user-supplied
version assertions. Existing historical records are not rewritten. The daily
runner always requires archive verification, including normalized JSON input
without an official-looking URL; there is no CLI switch to disable it. The
internal pack/calculation API retains its existing normalized-research test use,
which cannot establish source versions. Archive and previously versioned issuers
are guarded regardless of that internal compatibility setting.

BTC holdings, diluted shares, cash and Reserve have independent effective dates,
original disclosure/first-seen/retrieval clocks, values and raw-source references.
ASST cash-and-equivalents maps only to its own source-defined cash field; Reserve
is never added to it. Reported facts can establish a source version without
certifying formal dilution scope, unrestricted cash or complete residual value.
MSTR date-only ADSO research without its required clocks cannot establish a
formal CT version.

A missing-input run retains version evidence but inserts no cached financial
values into CT. A later older archive is quarantined at the affected field, even
across process restart or an intervening run without CT inputs. A newer reported
snapshot also prevents CT from silently falling back to an older comparable
pair when the new snapshot is not eligible for that calculation. Other issuers
and BTC market observations continue independently.

Same-effective-date different values are blocked and retained as a conflict.
`correction_verified=true`, an amendment filename or a later publication alone
does not resolve it. This change does not invent an automatic SEC amendment
supersession policy: conflict resolution stays blocked pending source-qualified
correction review. A genuinely newer effective date can advance normally.

Current mNAV corporate components must match the reparsed source values, dates,
raw hashes and complete original dilution scope. A caller cannot use a real raw
hash to certify an invented COMPLETE dilution scope. The formal mNAV formula and
its existing validator are unchanged. Rejected historical observations remain
explicitly historical research in the sealed pack, outside current calculations.

Qualification is carried in `asset_facts.items` as `ISSUER_SOURCE_FRESHNESS`, with
claim-scoped blockers. The existing GPT bridge retains all company qualification
states, blocker codes and per-field dates. Original proofs are bound by the
enclosing Evidence Pack hash. Existing exact field/value references and their
decoder compact repeated health qualifications without dropping values. The
16 KiB ceiling is unchanged and still rejects oversized requests.

Acceptance uses the existing genuine 2026-10-05 fixtures plus genuine 2026-10-26
and 2026-11-09 SEC originals. The latter reports the 2026-11-06 snapshot; dates
are historical test cases, never fixed definitions of the latest company data.
Mutated raw vectors and market/capital handoff envelopes in tests are synthetic
and are not evidence of a real correction, current market or live model run.

Production, season, weights, mNAV semantics and user-only capital authority are
unchanged. No runtime, schedule, broker, provider, notification or trading action
is added by this change.
