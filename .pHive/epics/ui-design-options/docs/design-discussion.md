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

## 5. Open questions for the user

1. Any of the three (or the existing merged pass) an immediate no?
2. Is single-page (Findings) enough to judge by, or do you want the winning
   direction mocked up on a second page type (e.g. the Scan page) before
   committing to implementation?
3. Keep the light/dark toggle regardless of which direction wins, or is that
   negotiable per-direction?

## 6. Scale assessment

**Medium.** Multi-file (style system + every template that renders findings
-- already touched ~9 files in the session-1 pass), but not
multi-system/long-horizon. No H/V slicing needed beyond "mockup and choose,
then implement the winner as its own story."
