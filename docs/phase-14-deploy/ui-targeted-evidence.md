# Targeted T01 UI evidence

These runs cover only the S13 UI states added or changed for database types, credential validation, and trial access. They do not repeat the unchanged 36-image matrix.

The captured UI source fingerprint is `e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b`; the original source fingerprint is `1ab3826f0a0e472425145e0c037870be6a48fd5250f9a66d4d06b04b145266db`. The candidate was captured from accepted frontend commit `62c19bb`; `git diff --stat 62c19bb..93175f9 -- frontend` is empty, so this frontend source matches the accepted source HEAD used for the S14 snapshot. Browser: Chrome `154.0.8037.97`; Node `v24.12.0`; pnpm lockfile SHA-256 `b0802398f7998fc842d9790eff57efe0fd82efe139a6b6aece6405f0d72c5513`; viewport `1440×1000`; locale English. Original and candidate used the same in-process HTTP fixture and installed locked dependency tree. None of these runs exercised FastAPI or a live database.

| Scenario | Browser assertion and observed difference | Changed pixels |
| --- | --- | ---: |
| `database-type-selector` | The candidate opens the create-form selector and asserts all ten options in order; the original has no selector. Neither side sends a create POST. The screenshot is taken after the exact login-success toast has detached. | 4.38% |
| `database-mongo-pair-validation` | The candidate selects MongoDB (port `27017`), fills only username, and submits. The paired-credential message remains visible, the dialog and username remain, and no POST is sent. The original shows its required-fields warning and closes the dialog. | 78.28% |
| `trial-status-error` | Both apps receive the same first status response with `trialEnabled: null`. The candidate displays a retryable status warning and hides upload/compare; clicking retry causes a second status GET, clears the warning, and restores the non-trial upload entry. The original has no retry warning and exposes upload. | 3.03% |
| `trial-chat-read-only` | Both apps first finish the same mock trial-status GET and render the trial banner. The original upload control is visible; the candidate hides upload; comparison is hidden on both. | 0.10% |

The accepted-run process evidence is: selector runner PID `11512`, original Vite `4260@1797`, candidate Vite `19288@1813`; Mongo runner `16852`, original Vite `11664@11313`, candidate Vite `11888@11321`; status-error runner `22180`, original Vite `12604@9097`, candidate Vite `10920@3717`; trial-chat runner `11868`, original Vite `19024@4817`, candidate Vite `12848@4829`. All four processes exited when their test run finished.

The Mongo screenshot reflects the candidate's `@before-ok` Promise result retaining the modal on validation failure. The selected-type screenshot verifies all ten dropdown options through the DOM assertion; the dropdown scroll area only displays its first entries in the captured viewport. The trial screenshots preserve the source behavior: `ChatPage.vue` gates `FileUploader` and comparison on `trialStore.isReady && !isTrial`.

## Accepted target screenshots and hashes

Artifact root: `C:\Users\22126\AppData\Local\Temp\sqlchat-s14-delivery-e5a94ceb8e2a4da2819af02a3f9c271a\artifacts\ui-targeted`.

| Scenario / run | Report SHA-256 | Original PNG SHA-256 | Candidate PNG SHA-256 |
| --- | --- | --- | --- |
| `database-type-selector` / `346f0d79-3557-4040-94c9-c3c186d0ed58` | `A775E501CCACF436229351B62A87AFF806AEEE12A95C677D7BA9E25341F7238B` | `87ECBF4108CB552FB83B2B387E324B2344A7D58EFED08B815110A1B46D4EDED0` | `648951CDB2A8510BB61C18F0FA9203E151E6598D85CAB7216AAD3321FAEF8034` |
| `database-mongo-pair-validation` / `011a5fdb-af4f-4b49-b38f-7c7d6bf52b25` | `3BEE3A888F227BED8C093C58E5A3E1B2DEB31D9615688A12C3EB976D4B48F13F` | `10A23EA3A0003E69377C2BD8A38AB0CA30C26645E88C2A26EC54AF875C8359D1` | `3DFFB34703539D4C876528FED3C0DC09F262A10BFA672E47C1CCF6F9F1EF264D` |
| `trial-status-error` / `5ec0ddca-1983-477b-85f6-e02dfcef3bbf` | `5EF99E7BBF25B21FE603F69ACE0AABB171C5D05ACED3CC5D618C469994CE4C0E` | `1723A2E9F668A25DE060277E3FFC3AE13D8BFF666110CB93BA0D84DBDEAF6704` | `4D3D339434209D68FCED72556D19794334B45723529F0A4E5BA74BC82E079B6C` |
| `trial-chat-read-only` / `f09ac982-7aa1-48fe-ba02-f7f1eff6ddf4` | `BEA5C4610F264F9852C930BC8400B88266D6A3A60A4D4752832A834938842F5F` | `5A289AC2AB24C025630D5D45CED16AF3F54264B683A579766952F19A279DC7EC` | `8D5ED234489D9D27DA7F0637540735EC2A405996DC034CFED7146C308B75CF10` |

Each accepted run directory contains `report.json`, `original/<scenario>.png`, and `candidate/<scenario>.png`. The JSON records the exact click/assertion sequence, both source fingerprints, mock API evidence, and visual difference. Every scenario passed with zero skipped cases and no page errors.

## Preserved superseded attempts

- `16df00bd-4974-4b33-899f-b416be6cbdb8` passed the selector assertions, but both screenshots still showed the transient “Logged in successfully” notification. It is retained; the accepted rerun waits for that exact notification to detach before opening the database form.
- `b3268148-e416-44f2-a5f0-a2d9bdca65ea` stopped on a harness copy mismatch: it expected “Please fill in all fields.” The original `DbConfigPage.vue` calls the localized `admin.dbConfig.fillAllFields` warning, whose English text is “Please fill in all required fields.” The corrected test uses that exact source-backed copy, then asserts the original legacy dialog-close behavior. No UI source was changed for this correction. The failure report is `targeted-failure-report.json`; SHA-256 `FC340FC7EC481E3EC30829A2882586AC1556843CA4E16195135B22342FAB2A1B`. This run produced no screenshot.
- `55337064-252b-41ee-a78a-7488420c3a2a` captured the trial-status error with `fullPage: true`, which yielded a 1000px original and 1041px candidate image. It is retained as superseded. The accepted rerun captures both at the same 1440×1000 viewport; it does not weaken the trial or retry assertions.

The original source tree was copied read-only with `.env`, `.git`, `node_modules`, `dist`, and credential-like files excluded. The Vite fixture explicitly denies `.git` and uses a unique temporary cache directory for each app/run. Artifacts are outside the candidate source tree and contain no live credentials.
