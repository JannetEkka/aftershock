# Aftershock

**Did the news move the chain?** For someone deciding whether to hold NEAR for years, Aftershock tests every spike of news about NEAR against the chain's own daily records, compares it with ordinary days, and writes a thesis in which every sentence had to pass a check against the data.

Built at NEAR Hackathon, Investment Thesis track. Page: https://jannetekka.github.io/aftershock/ · Thesis: [THESIS.md](THESIS.md)

## What it found (measured, snapshot through 2026-11-11)

| Question | Result | Compared with |
|---|---|---|
| Of 74 news events, how many moved the price? | **8** (10.8%) | 5.1% of ordinary days pass the same test |
| How many moved usage (transactions, active accounts, new accounts, DEX volume or Intents volume)? | **10** (13.5%) | 16.5% of ordinary days get the same stamp |
| Transactions alone | **0 of 74** | about 3.7 expected by chance |
| Claims written by the Bull and Bear models, with the check on | **14 of 20 kept**; 0 removed by recomputation or form, 6 by the Examiner | with the check off, all 20 would have been printed |
| The same two models asked for a thesis with no data | **1 right, 15 wrong, 4 uncheckable** (right = within 10%; 0 within 1%) | our kept claims must be within 1% |

**What this changes for a long-term holder.** The usual thesis is a set of headlines with a bull story on top. Here the headlines were tested: NEAR's usage moved after news spikes no more often than it moves on ordinary days (13.5% against 16.5%), and price moved after 8 of 74. So a holder can stop reading headlines as evidence about usage, and look at the usage records themselves, which is what the thesis does. This is a result from our own run on public data; we have no measured baseline for how analysts do this by hand, and we do not claim one. It could be measured by giving analysts the same events and scoring their calls against the same band.

Limits, stated plainly: a news spike is a rough stand-in for an "influential event"; 49 of the 74 spikes were labelled as market-wide or generic price coverage rather than NEAR-specific news; events overlap; nearby days are not independent, so the odds quoted on the page are approximate; and the ordinary-day band is built from the whole history, where early years swing more.

## Do this, see that

You need Python 3.9 or later and git. Nothing to install, no keys, no network.

| Do | See |
|---|---|
| `git clone https://github.com/JannetEkka/aftershock && cd aftershock` | the code, the data snapshot in `data/`, the recorded model replies in `replies/` |
| `make replay` | the event-test table for 3, 7 and 14 days, then `RESULT`, `CLAIMS` and `AI ALONE` lines with the numbers above; `results.json`, `THESIS.md` and `docs/data.js` are rebuilt |
| `make verify` | the same, then `IDENTICAL: the replay rebuilt the committed results byte for byte.` |
| `make test` | 26 unit tests pass, including a made-up series with a planted +50% jump that must be stamped "moved" while a quiet day is not |
| `make serve`, then open http://localhost:8000 | the strip chart draws left to right and the stamps land; tap a pin, or a small mark after a thesis sentence |
| `make view` (needs Node 18+ and network) | what the testnet contract holds: the snapshot fingerprint, the run counts and the forecasts |

Optional, needs keys or network:

| Do | See |
|---|---|
| `NVIDIA_API_KEY=... make live` | all three sources are refetched and every model is called again. If a source fails or returns too few days it prints `STOPPED, nothing published: source '...'` and writes nothing |
| `make contract` (needs Rust with the `wasm32-unknown-unknown` target) | the contract's 6 tests pass and the wasm is built |
| `make settle` (needs the testnet key) | due forecasts are recomputed and recorded; forecasts not yet due are listed, and the contract itself refuses them |

## How it works

```
NearBlocks, DefiLlama, GDELT (free, no keys)
   └─ snapshot in data/ + SHA-256 fingerprints
        └─ event finder (code): news count above the 95th percentile of the previous 90 days, at least 3 articles
             ├─ labeller model: what was the news about?
             └─ event test (code): change from 28 days before to 7 after, for events and for every ordinary day
                  └─ Bull model and Bear model write claims as data; each sees the other's once and rebuts
                       ├─ recompute (code): every figure from the snapshot
                       ├─ Examiner (the other model family): does the wording say more than the figure and events show?
                       └─ decision rule (code): keep or remove, with the reason
                            └─ Judge model writes the thesis from kept claims only
                                 └─ final check (code): cut any sentence without a kept claim behind it and behind each number
NEAR testnet contract: snapshot fingerprint, run counts, forecasts with due dates, settlements
```

**Models describe, code decides.** A claim is kept only if (1) its form is valid, (2) every event id it cites exists, (3) its figure matches the recomputation within 1%, and (4) the Examiner says "supported". Every model reply is validated (required fields, allowed values), retried once with the error shown, and recorded in `replies/`, including the rejected ones.

- **Event** = a day when GDELT's count of articles mentioning "NEAR Protocol" is above the 95th percentile of the previous 90 days and at least 3; spikes within 3 days merge. Code picks them, not a model.
- **Moved** = the change is outside the middle 95% of the same change computed on ordinary days (days with no news event in their window). About 5% pass by luck, and that line is printed beside every result.
- **The usage stamp** looks at five measures at once, so its chance rate is not 5%. We measure it by stamping every ordinary day with the same rule: 16.5%.
- **Missing days** in an event's window make that measure "not tested" for that event, never "nothing".
- **Roles.** Two seats from different labs, all on build.nvidia.com free endpoints. Bear and labeller: NVIDIA's `nvidia/nemotron-3.5-lightning-30b-a3b`. Bull and Judge: a model from another lab; the free endpoints went up and down during the run, so that seat tries `z-ai/glm-5.3-flash`, `minimaxai/minimax-m3.1-flash`, `stepfun-ai/step-5-preview` in order, and each recording in `replies/` names the model that answered (GLM wrote the Bull's first round, MiniMax its rebuttal and the thesis). A claim's Examiner is always the other seat from its writer.

## Sensitivity: 3, 7 and 14 days after

| Measure | 3 days: moved / tested | 7 days: moved / tested | 14 days: moved / tested | Expected by chance (5%, 7 days) |
|---|---|---|---|---|
| price | 5 / 74 | 8 / 74 | 5 / 74 | 3.7 |
| transactions | 0 / 74 | 0 / 74 | 0 / 74 | 3.7 |
| active accounts | 5 / 74 | 4 / 74 | 4 / 74 | 3.7 |
| new accounts | 3 / 74 | 3 / 74 | 3 / 74 | 3.7 |
| DEX volume | 2 / 68 | 3 / 68 | 3 / 68 | 3.4 |
| Intents volume | 3 / 21 | 2 / 21 | 3 / 21 | 1.05 |
| Stamp: moved usage | 10 / 74 | 10 / 74 | 12 / 74 | 12.2 (measured: 16.5% of ordinary days) |
| Stamp: price only | 5 / 74 | 6 / 74 | 4 / 74 | 3.1 (measured: 4.2% of ordinary days) |

Odds of at least this many by luck, if events were ordinary days (approximate, days are not independent): price, 7 days: 3.4% (3 days: 32%, 14 days: 33%); usage stamp, 7 days: 80%. The price result at 7 days does not hold at 3 or 14 days, so we do not lean on it.

## NEAR's role

1. NEAR's mainnet history is the evidence (read-only public data).
2. A small Rust contract on **testnet**, [`aftershock-mwf5vao1.testnet`](https://testnet.nearblocks.io/address/aftershock-mwf5vao1.testnet), stores the snapshot fingerprint, the run's counts, and each forecast with its due date, posted before the outcome is known.

What the chain enforces: only the owner can record runs and forecasts; a posted forecast cannot be edited; nobody can settle a forecast before its due date (the contract checks the block time); each settlement stores who settled it and the fingerprint of the data used. What it cannot do: see mainnet data or check a forecast by itself. Someone runs `make settle`; the contract records the result. It is a public notebook with timestamps, not a referee.

- Contract and deployment: [aftershock-mwf5vao1.testnet](https://testnet.nearblocks.io/address/aftershock-mwf5vao1.testnet), [deploy transaction](https://testnet.nearblocks.io/txns/3X4oN3ySfKvou8Pkmfqy6LGXvhNm29wqgnMAkEu5MHxD)
- Run 0 recorded, fingerprint `fc8d31eb23262c506751abe40fe00f9ee796056d7b535a254df73948a4736e82`: [transaction](https://testnet.nearblocks.io/txns/3PehTnLaHFyr5rAxV3k57WA9eS2nowdWLzYxAVGnmCvP)
- Forecast 0 (bull), due 2026-12-11: Mean daily price over the 7 days ending 2026-12-11 will be above 4.0000. [transaction](https://testnet.nearblocks.io/txns/DCCD2g6rzk7HPNFcbp6zB2yEJPRYevS6HACKTTz5w6Mm)
- Forecast 1 (bull), due 2026-12-11: Mean daily Intents volume over the 7 days ending 2026-12-11 will be above 140000000. [transaction](https://testnet.nearblocks.io/txns/BcqWGQn3sQZczS3kuskJHVT1pEfQb6GGjGgNrWZ9x5En)
- Forecast 2 (bear), due 2026-12-11: Mean daily price over the 7 days ending 2026-12-11 will be below 3.0000. [transaction](https://testnet.nearblocks.io/txns/CBut7SCKPv2VR4et66BFxB9PvH49KnKBYg6wWAdST7kv)
- Forecast 3 (bear), due 2027-02-09: Mean daily active accounts over the 7 days ending 2027-02-09 will be below 50000. [transaction](https://testnet.nearblocks.io/txns/6AaGvDdBDaXtDjHYQBPhZh2Azxz9frCXmneDBt8pDpLG)
- Forecast 4 (test), due 2026-11-10: TEST of the settle step, not a real forecast: mean daily price over the 7 days ending 2026-11-10 will be above 1. [transaction](https://testnet.nearblocks.io/txns/DrLhT5YjxkuiB8qLbzxp3kxSn54cjq7pd24HEdb9WepH) · settled TRUE, observed 3.73475: [transaction](https://testnet.nearblocks.io/txns/CdEB6c93e8LqFQDnXduiWqppDqc1qUytZBfoiobazAHf)

No mainnet transactions, no NEAR Intents (we only read public figures about Intents volume), no money.

## Implemented and proposed

**Implemented:** the three fetchers with fingerprints; the event finder; the event test with the sensitivity table; labeller, Bull, Bear with one rebuttal round, recomputation, Examiner, decision rule, Judge and final check; the AI-alone score; the testnet contract with run record, forecasts and a settled test forecast; the page; replay with no keys and no network.

**Proposed, not built:** settling the real forecasts (they are not due yet); a second news source besides GDELT; filtering generic market coverage out of the event list before testing; a matched comparison that accounts for trends (the band is one distribution over the whole history); other chains.

## Earlier work and closest projects

- **Countersign** (ours, Mozilla Otari hackathon, 2026-11-12): one model writes, another checks, code decides, on 2019 Apple news. Aftershock reuses its keep-or-remove idea as the last step. New here: the event test against ordinary days, chain usage as the evidence, the Bull and Bear debate, and forecasts recorded on NEAR. No code was copied; this repo was written for this hackathon.
- [The Tie SigDev](https://thetie.io/solutions/news): paid news tagging with market reactions. Not open, no chance comparison, no checked thesis.
- [crypto-event-study](https://awesome.ecosyste.ms/api/v1/projects/github.com%2Fstudiofarzulla%2Fcrypto-event-study): academic event-study code for crypto prices; not chain usage, not NEAR.
- [CRE Fact-Checker](https://chain.link/hack-26/projects/cre-fact-checker): checks ETH price claims and stores verdicts on-chain; price claims only.
- [DYOR.bot](https://hackquest.io/projects/DYOR): labels claims verified, ambiguous or unresolved.
- [CryptoAnalystBench](https://arxiv.org/abs/2602.11304): shows AI crypto analysis fails in ways ordinary fact checks miss; the reason our check exists.

Event studies and claim checkers both exist. We found nothing that joins them for a chain's usage.

## Libraries and services

- Python 3 standard library only for the pipeline and tests (no packages to install).
- Rust with [near-sdk](https://github.com/near/near-sdk-rs) 5.30 for the contract; [near-api-js](https://github.com/near/near-api-js) 5.1 for the testnet scripts.
- Data: [NearBlocks](https://nearblocks.io) charts API, [DefiLlama](https://defillama.com) (TVL, DEX volume, stablecoins, NEAR Intents volume), [GDELT](https://www.gdeltproject.org) DOC API (article counts and headlines).
- Models: build.nvidia.com free endpoints.
- The page is plain HTML, CSS and JavaScript with no framework.

## Layout

`aftershock/` pipeline · `tests/` unit tests · `data/` snapshot and `manifest.json` fingerprints · `replies/` recorded model replies · `contract/` Rust contract · `chain/` testnet scripts and `onchain.json` (transaction links) · `docs/` the page · `results.json` everything the page shows · `THESIS.md` the thesis.

Not investment advice. MIT licence.
