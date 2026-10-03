# 2026-10-03 compare-preflight follow-up review

This V5-only record binds the targeted deployment, two later Python-only provider runs, and root’s independent review of their final answers. It keeps the earlier run artifacts intact. The code source remains `9c077413105a9ec3236416f21b83b4fae18753bb`.

## Targeted deployment

Root’s public deployment receipts report that the API and Worker images were updated while the four named volumes, protected containers, and frontend image were preserved. The application health check passed; the metrics-epoch initializer and migration-version check each exited successfully as separate checks. The accepted image binding is recorded separately from the runtime snapshot. The source-map receipt checked 141 paths against 140 prior paths, with no mismatches.

This focused deployment did not repeat the clean-start checks, a full-stack teardown/restart, or the separate T-33/T-34 gates. Keep the earlier S14 receipts as evidence for those scopes.

| Receipt | SHA-256 | Evidence |
|---|---|---|
| [Runtime snapshot](compare-preflight-runtime-after-review.json) | `6e325c93f0e6362340e2686f204b8978487b9c7200df33f3e363975f5c047776` | `namedVolumesPreserved`, `acceptedImagesMatch`, `applicationHealthy`, `metricsInitializerExitedZero`, `migrationExitedZero`, and `otherContainersUnchanged` are true; `frontendImageChanged` is false. |
| [Accepted image receipt](compare-preflight-compose-accepted-images.json) | `f908f8f99035e66c3bb2dedc719cbab9efe6ff9eff401a9239a9565f88f2d35b` | Accepted API and Worker image identities. |
| [Source-map receipt](compare-preflight-host-source-map.json) | `b6b11c02ab5bb3474bd9eab258edf8e27b3baf4b078d5bad943cb5f629dcd9e7` | 141 checked, 0 mismatches, status `passed`. |

These checks establish the targeted deployment state. They do not establish model-answer correctness or migration acceptance.

## Fresh provider-run machine results

Both runs are independent Python-only scopes from the fixed run source. Their machine status is `review-required`; the row counts are run bookkeeping, not answer acceptance. The JSON and JSONL files are byte-preserved copies of the public source artifacts.

| Scope | Rows / turns | Row status counts | Model calls | Machine status |
|---|---:|---|---:|---|
| Classification (`classification-20261003092425Z`) | 18 / 21 | 6 `passed`, 12 `review-required`, 0 `failed` | 69 | `review-required` |
| Affected effects (`affected-python-20261003092425Z`) | 36 / 36 | 0 `passed`, 36 `review-required`, 0 `failed` | 120 | `review-required` |

The classification run reports a stable runtime fingerprint. The affected-effects run also reports a stable runtime fingerprint. Their combined 57 turns are the scope reviewed in the root answer-review receipt; the runs remain separate and are not a new 120-row / 60-pair Java/Python matrix.

| Run artifact | SHA-256 |
|---|---|
| [Classification JSON](classification-20261003092425Z.json) | `60714e3228070f1b26e93cb65f97d6e3b94e2a4c5c569e070dc9aac449ec4bda` |
| [Classification JSONL](classification-20261003092425Z.jsonl) | `04512bb25cfe181e4f0441b2339cfd682459256d2987a921b97b96e0bf8514db` |
| [Affected-effects JSON](affected-python-20261003092425Z.json) | `587a3e78c88752b4d7d94097dd9aa07462a2254e3dd9ce7e3dbecfc88bf5d4eb` |
| [Affected-effects JSONL](affected-python-20261003092425Z.jsonl) | `af9b497fa5b555051850f37f8eed7daab9a9b55d91d273b90f7e35047db2668a` |

## Independent answer review

The root receipt binds all 57 turns, their answer hashes and locators, raw run status, and provider usage. It independently matched usage for 189 provider calls and verified the recorded execution checks. Across six compare reviews, each two-page result joined to the full result; none executed migration SQL.

The turn dispositions are 29 supported, 13 factual-claim failures, 1 task failure, and 14 wording-only turns. The 14 wording-only turns are not failures. The receipt contains 15 accepted findings: 14 failure findings and 1 wording finding. The failure findings include unsupported claims about unknown schema facts and an incomplete final workflow report. Root did not accept the final answers or the full migration: both `acceptedFinalAnswers` and `fullMigrationAccepted` are false. Findings remain open for repair and new evidence.

The answer-review receipt is a separate human review of the frozen proposal, not another machine run result. Its source is `9c077413105a9ec3236416f21b83b4fae18753bb`; proposal SHA-256 is `5d6f5233eba2f2ef29d95e5afeda6332b416da40fdc12d79022b996d33ba1f11` (`.git/acceptance/s15-preflight-real-effect-answer-proposal-20261003.json`), with `rootPass=false`. The public review receipt is [root-final-answer-review-20261003.json](root-final-answer-review-20261003.json), SHA-256 `f37594496d277ef3269e674881992b554ba60464decd2beb23664ed70a949159`.

Deployment checks, machine row statuses, and human answer findings are separate evidence. Passing deployment or execution checks and zero machine `failed` rows do not close the 14 answer failure findings or establish full migration acceptance.
