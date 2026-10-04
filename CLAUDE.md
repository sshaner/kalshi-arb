# CLAUDE.md — Kalshi ↔ Polymarket US Arb Scanner

Cross-venue arbitrage scanner for **Kalshi** and **Polymarket US** (`gateway.polymarket.us`, the CFTC-regulated US venue — *not* international Polymarket), managed entirely from an **iOS app** (TestFlight). Mode is **alert + paper trading only**: no trading keys, no real orders.

An arb exists when the same binary outcome is priced on both venues and `YES ask (one venue) + NO ask (other) + fees < $1`. The real risk is the two venues resolving differently, so every pair is human-approved and divergent settlements are tracked.

## Layout

| Path | What |
|---|---|
| `server/arb/` | Python 3.12 asyncio service: discovery, price, and settlement loops + FastAPI for the app, one process |
| `server/tests/` | pytest (fees, engine, matcher, venue parsing from fixtures, API) |
| `app/ArbScanner/` | .NET 10 MAUI app (XAML + CommunityToolkit.Mvvm). iOS ships; the Android TFM exists **only** so shared code compiles on Windows |
| `app/ArbScanner.Core/` | net10.0 library: API models + **all teaching content** (`Learning/Glossary.cs`, `HelpText.cs` tutorial/screen intros/setting help, `Explainer.cs` plain-English walkthroughs built from real numbers) |
| `app/ArbScanner.Core.Tests/` | xUnit; runs in the iOS workflow before the build (never locally) |
| `.github/workflows/ios-release.yml` | macOS runner → signed IPA → TestFlight (adapted from MusicColab's) |
| `deploy/` | systemd unit, nginx vhost, `root_setup.sh` (one-time, sudo), `deploy.sh` |
| `tools/` | one-shot `apple_setup.py` (App Store Connect API) and `github_setup.py` (repo + Actions secrets); own `.venv` |

## Running / deploying — never locally

Per the workspace rule, nothing runs on the Windows machine except static checks. The server runs on shnr.org (`sshaner@10.0.0.187`) at `/projects/kalshi-arb`, systemd unit `kalshi-arb`, served at `https://arb.shnr.org` (Cloudflare wildcard DNS → nginx with the Cloudflare origin cert → `127.0.0.1:8095`).

```bash
bash deploy/deploy.sh                       # copies server/, pip installs, runs pytest on the server, restarts
ssh sshaner@10.0.0.187 'sudo -n journalctl -u kalshi-arb -n 100 --no-pager'
```
`root_setup.sh` installs a sudoers drop-in so `sshaner` can restart/inspect **only** this unit without a password. Server `.env` (`server/.env.example`) holds `API_TOKEN` and the APNs key settings.

Static checks on Windows: `python -m py_compile` for the server; `dotnet build app/ArbScanner -f net10.0-android` (and `-f net10.0-ios` compiles the managed assembly on Windows too, which type-checks `AppDelegate`). Real iOS builds happen only on the GitHub macOS runner.

## Venue API facts (verified against live responses, 2026-10)

- **Kalshi** public `https://api.elections.kalshi.com/trade-api/v2`, no auth. Prices are `*_dollars` strings. Orderbook (`/markets/{t}/orderbook` → `orderbook_fp`) is **bids only**: YES ask = 1 − best NO bid. Batch quotes: `/markets?tickers=a,b,…` (≤100). Per-series `fee_multiplier` comes from `/series` (one call returns all ~15k). Discovery uses `/events?status=open&with_nested_markets=true`; multivariate (`mve_collection_ticker`) markets are skipped. Rate limit is tight: 429s above ~15 req/s unauthenticated → `KALSHI_RPS=10` token bucket.
- **Polymarket US** public `https://gateway.polymarket.us/v1`, no auth. `/events?active=true&closed=false&limit=200&offset=N` (~68k markets). Book `/markets/{slug}/book` → `marketData.bids/offers` for the **long (YES) side**; NO ask = 1 − best YES bid. Batch quotes: repeated `?slug=a&slug=b`. Settlement: `/markets/{slug}/settlement` (404 until settled). `/markets/{slug}` itself errors — don't use it. Taker fee θ=0.0695·C·p·(1−p).
- **Polymarket US quirks the matcher depends on**:
  - Head-to-head games are **one** market: side descriptions are names (not Yes/No/Over/Under/±line) → YES = first team, NO = second team (`alt_title`). A Kalshi market on the second team is an **inverted** pair.
  - Yes/No markets (futures, soccer "(Reg. Time)") *also* carry `team` objects on both sides — don't use team presence to detect head-to-head.
  - **Spread markets whose long side is `+N`** (slug `…-pos-…`) have a title naming the *other* side ("USC wins by over 5.5" where YES = Washington +5.5) → `flipped=True`, orientation inverted.

## Matcher (`server/arb/matcher.py`)

~124k Kalshi × ~68k PM markets, so it blocks on rare tokens + date window, then hard-filters: same numeric lines (outcome *and* event title), same qualifiers (period, method, finalists, exact, …), same prop kind (spread vs game total vs team total), same head-to-head matchup, compatible outcome entity (with "distinguisher" words: Texas ≠ Texas Tech, Florida ≠ South Florida). Drops pairs whose top-of-book gap is implausible (est. cost < 0.75). Produces ~5.5k suggestions per full pass, ~20–40 s. Suggestions are reviewed in the app (sorted: small visible gaps first); `/api/candidates/approve-bulk?min_score=` exists but still lets through some false pairs — check opportunities' rules before trusting them.

## Price loop

Bulk top-of-book for all active pairs each cycle; full order books only for pairs whose top-of-book hedged cost is < $1 or that have a live opportunity. ~4k pairs ≈ 30–40 s/cycle at 10 rps. Opportunities walk both ask ladders (fees per level, conservative ceil), respect `paper_max_stake`, and open one paper position per new opportunity.

## Credentials (never print them)

- App API token: `C:\Dev\.claude-long-term-memory\.tokens\kalshi-arb-api` and server `.env`.
- Kalshi / Polymarket API keys: `.passwords\kalshi`, `.passwords\polymarket` — **unused** in alert/paper mode; only needed for authenticated rate limits or live trading.
- Apple: shared distribution cert in `C:\Dev\.Apple\` (password `.passwordspple` — **not** `apple-ios-distribution-p12`, which doesn't open it), ASC API key per MusicColab's `CLAUDE.md`. APNs auth key `AuthKey_VJMKA689W2.p8` (team-scoped, created 2026-10-03) in `C:\Dev\.Apple\` and on the server as `/projects/kalshi-arb/apns_key.p8`. Team ID `V3X94XMM36`, bundle `org.shnr.arbscanner`, ASC app id `6818922367`, profile name `Arb Scanner App Store`, internal TestFlight group `Internal`.
- GitHub token `.tokens\github-kalshi-arb` can set Actions secrets and re-run workflows but **cannot push** (403) — pushes go through the normal git credential helper.

## CI gotcha

`dotnet workload install maui` grabs the newest iOS workload, which can require an Xcode the `macos-26` runner doesn't have (iOS SDK 27.0 needs Xcode 27; image had 26.6). The workflow selects Xcode 27 if present, otherwise installs from a rollback file pinned to the iOS 26.5 workload. Update the pins when the runner image gets Xcode 27.

## Learning mode (in-app teaching)

One phone-side switch (`Services/LearningMode.Current`, persisted in `Preferences`, toggled by the "Help" toolbar item on every tab or in Settings) shows/hides every teaching element: per-screen `HelpCard` intros (dismissible, "Reset tips" restores), `InfoButton` ⓘ → glossary entry, `HintLabel`s, `SettingHelpView`s, inline `ExplanationView`s, and Review's "Explain this pair". The 7-card `TutorialPage` shows once (`TutorialSeen`) and is replayable from Settings. All text lives in `ArbScanner.Core/Learning` — edit content there, and keep `Explainer` fee constants in sync with `server/arb/fees.py`. The server supplies `match_details` (why a pair was matched/oriented) and opportunity `k_top_size`/`p_top_size`/`days_to_close` for the explanations.

## Deal rating + Review filters

`server/arb/rating.py`: rating = 1 + 9 × confidence × money (confidence = match quality/orientation/dates/rule-sensitive types/implausible gap; money = after-fee profit per contract at top of book). Each discovery pass re-rates every pending candidate in a child process (`_rate_in_process`) and **auto-rejects** pending pairs that no longer pass the current matcher rules (`matcher.still_compatible`, status `auto_rejected`). `/api/candidates` takes `min_rating, kind, orientation, has_gap, closes_within_days, q, sort, offset`; `/api/candidates/count` returns matching/total/by_rating. Opportunities get a rating at request time and in push titles ("9/10 Excellent arb: …"). Review ratings use last-scan prices (≤30 min old); a 10 is never "risk-free" — app copy must keep saying so. App: `ReviewFilter` (Core, persisted in Preferences), quick chips + `FilterPage`, debounced search, 50-per-page infinite scroll.
