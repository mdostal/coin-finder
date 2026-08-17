# Design Discussion: UI Visual Design Options

## 0. Prelude

**Prior decision (this session, superseded by this plan):** an ad-hoc UI
redesign pass was already implemented and merged to `main` directly (warm
brass/gold palette, Fraunces serif headings, card-based Findings, real coin
icons, truncated-path display, light/dark toggle) without going through
`/plugin-hive:plan`. The user explicitly flagged this as the wrong process:
*"I'm not a fan of the default claude outputs, i am consistently pleased with
how it is when using the /plugin-hive -- it is why I specifically say plan
then execute -- it is to USE THE PLUGINS"* and *"i hate it when any of the
claude agents wing it -- i get subpar results 90 some odd percent of the
time."* This plan treats the existing merged work as **one candidate**, not
the answer, and produces genuinely independent alternatives to compare it
against.

## 1. Goal

Produce multiple genuinely distinct visual design directions for
coin-finder's local web UI, reviewed against the app's real goals, narrowed
to one winning direction with the user's sign-off -- not a single ad-hoc
restyle decided solo.

## 2. Current state

coin-finder is a local Flask app (dark-mode-only before this session) used to
recover old/forgotten cryptocurrency wallets: scan drives, check balances,
crawl transaction graphs, unlock wallets, manage a password vault. Before
this session's ad-hoc pass, styling was effectively unstyled-default: system
fonts only, a generic teal accent, dense HTML tables with a checkbox column
and a wall of always-visible per-row buttons.

Real, repeated complaints from the user this session (verbatim, across
several messages): "boy does this look like shit"; "the auto unlock is way
hidden... you must not have gotten through the proposals cause i never saw a
proposed UI fix"; and, when styling was addressed but not restructured:
"theming wasn't the real issue -- we need file icons for wallets, the name,
description, etc just much cleaner and things able to be viewed and fired and
actioned ON rather than a bunch of long lists of text with checkboxes."

## 3. Real constraints (from this project's north star + this session)

- **Audience:** the user themselves, plus other crypto hobbyists running this
  locally to rediscover old wallets. Single-user, local-only, no hosting/auth
  concerns.
- **Stakes:** genuinely high for the user right now -- described this session
  as possibly their only source of income in the near term, with real
  confirmed finds (0.3 BTC + partials) already recovered. The UI is not
  decorative; it needs to make a real find impossible to miss and make acting
  on a finding (unlock, graph, archive) fast, not buried.
- **Content shape:** the flagship page (Findings) is a list of
  coin+address+balance+source+status rows, growing over a multi-day,
  multi-session crawl. Deeply nested source paths (a drive within a drive
  within a backup, "3 computers deep") are common and must stay legible.
- **Never-touch invariant:** the app must never be restyled in a way that
  requires touching the real running installed app to verify -- all
  verification happens against an isolated dev server, per this project's
  standing safety rule.
- **Offline-first / secrets discipline:** unaffected by visual design, but
  any interaction redesign (e.g. how Reveal/unlock results are surfaced)
  must preserve the existing once-only-secret-display invariants.

## 4. Proposed approach

Three independent design-proposal passes, each briefed identically (this
document + the real Findings-page data shape) but each committing hard to
one distinct creative direction, with **no visibility into each other's work
or into the already-merged session-1 pass** -- genuine independence, not one
author simulating three opinions. Each produces a real, self-contained HTML
mockup of the Findings page using real sample data (multiple coins, a
confirmed non-zero balance, a deeply nested source path, a watched entry) so
the comparison is concrete, not abstract palette swatches.

A review pass then evaluates all three (plus the already-merged pass as a
fourth reference point) against section 3's real constraints, and the user
makes the final call.

## 5. User review (resolved)

All three options were built (by three independent agents, blind to each
other and to the session-1 pass), published as artifacts, and reviewed
live by the user. Verbatim reaction: "man... all of these are SO MUCH
NICER!!" All three held up under direct inspection (not just the
proposing agent's own report) -- option C had real, verified bugs (Actions
column overflowing the viewport, mid-string path truncation instead of
end-anchored, more visible encoding mangling) that were caught and
disclosed before the user picked, consistent with this project's
trust-but-verify discipline.

**Winning synthesis -- not a single option, a deliberate hybrid:**

- **Structure/majority styling: Option A** (archival/vault) -- vertical
  coin-name tabs down the card's left edge (card-catalog style), the
  wax-seal "CONFIRMED FIND" treatment for a real non-zero balance, warm
  paper/brass palette as the default.
- **Path metadata wording: Option B's phrasing** -- the "LOGGED
  {date} · SESSION {n} · DRIVE "{name}" ({size})" line and the "Chain of
  custody — source path" label, which the user called out by name as
  something they specifically liked.
- **Path visualization: Option C's expandable tree** -- `└─` connector
  tree, collapsed by default (B's always-expanded version "takes up too
  much real-estate" per direct user feedback), click to expand.
- **Filtering: Option C's coin tabs** (All / BTC / LTC / OKCash / ...)
  **+ Option B's search field.**
- **Real coin icons** (already built this session, `web/static/coin-icons/`)
  restored into option A's vertical tabs -- none of the three mockup
  agents had access to that existing asset, so all three fell back to
  text/initials there.
- **Theme mechanism:** not full structural swapping between A/B/C (three
  parallel template systems is real, ongoing maintenance weight for
  little payoff) -- one unified layout (the hybrid above) with a
  **Settings page offering multiple named color palettes** to swap
  between (e.g. Archival/warm-brass, a cooler Docket-tinted palette, an
  amber Terminal-tinted palette), using the same CSS-custom-property
  token-swap mechanism the existing dark/light toggle already proved out,
  just extended from 2 states to N named presets.
- **Group actions on Findings:** Watch and Try-unlock added to the
  existing bulk-select flow (Graph and Check-fork-coins already run in
  bulk from a prior epic this session).

## 5b. Traceability gap (flagged, not silently dropped)

The user also asked, in the same message, for related-account discovery
to specifically surface **which of the user's own known wallets** touched
a candidate address that holds coinage -- "there is a chance you know
what it is or may still have access to that other one as well." The
existing `confidence-scored-related-accounts` epic (shipped earlier this
session) already factors multi-crawl overlap into its confidence score
(`cross_run_count` bonus) but does not surface the actual list of which
known findings/wallets a candidate was co-spent/output-linked with. That
readable "touched by: wallet X, wallet Y" surface is a real, distinct
enhancement to `web/crawl_runs.py`'s confidence scoring + the related
-accounts template, not a Findings-page styling concern. **Out of scope
for this UI epic** -- tracked as a follow-on rather than dropped.

## 6. Scale assessment

**Medium.** Multi-file (style system + every template that renders
findings, a new settings route/page/persistence, JS for the
expand/collapse tree, bulk-action wiring) -- already touched ~9 files in
the session-1 pass and this hybrid adds a real settings subsystem on top.
Not multi-system/long-horizon; no H/V slicing needed beyond the story
breakdown below.
