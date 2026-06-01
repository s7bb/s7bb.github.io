# Secure GitHub Access for `latest.json` Push

**Status:** Draft (design)
**Date:** 2026-05-06
**Owner:** Martin Zehetmayer
**Related code:** `fetcher/src/s7bb_fetcher/pusher.py`, `docker-compose.yml`, `.env.example`

---

## 1. Problem Statement

The S7BB fetcher VM publishes `data/latest.json` to the GitHub repository every hour. It authenticates with a **SSH deploy key** mounted from the host (`SSH_DEPLOY_KEY_PATH`) into the Docker container. The key has **read+write** access on the repository.

The blast radius of a key compromise is much larger than the workload requires:

| Capability granted by current SSH deploy key | Required by workload? |
|---|---|
| Push to any branch (incl. `main`) | Only `main` |
| Modify any file in the repo | Only `data/latest.json` (and, in future, `data/archive/*.json`) |
| Force-push, delete branches, push tags | No |
| Trigger any GitHub Actions workflow on push | Only `build-site.yml` |
| Read all repo content over SSH | No (push-only would suffice) |

A stolen key would let an attacker:

- Replace `site/` source with a malicious bundle (XSS shipped to Baierbrunn residents on next Pages deploy).
- Force-push `main` to wipe history.
- Push tags that look like signed releases.
- Read private repo content (none today, but future-proofing).

The goal of this feature is to **shrink that blast radius to "append/replace `data/latest.json` on `main`"** while keeping the hourly automation hands-off.

---

## 2. Goals / Non-goals

### Goals
- Replace the broadly-scoped SSH deploy key with a credential whose authority is limited to the actual workload.
- Defense-in-depth: even if the credential leaks, GitHub-side rules should reject anything that is not a `data/latest.json` change on `main`.
- Short-lived or rotatable credentials, with a documented rotation procedure.
- Keep the fetcher container self-contained; do not add a service that requires a long-lived sidecar with elevated trust.
- No regression on availability of the hourly publish.

### Non-goals
- Re-architecting the data flow (e.g. moving fetching into GitHub Actions). The DB API key must stay off CI per `CLAUDE.md`.
- Signing commits / verifying signatures end-to-end. Out of scope; can be added later.
- Hardening the GitHub Pages site itself (CSP, SRI, etc.) - separate concern.
- Secret management infrastructure (Vault, Doppler, …). The credential lives in `.env` like all other secrets today.

---

## 3. Threat Model (short)

- **Adversary A - host compromise:** root on the VM. Outcome: any credential on disk is lost. Mitigation goal: reduce damage that can be done with the leaked credential.
- **Adversary B - container escape / supply chain:** code execution inside the fetcher container. Same outcome as A for credentials mounted into the container.
- **Adversary C - repo collaborator compromise:** out of scope here; controlled by GitHub account 2FA / org policy.

The design therefore assumes the credential **will** leak eventually. It optimises for **what an attacker can do with the leaked credential**, not for preventing the leak.

---

## 4. Options Considered

Three live candidates plus the status quo. Each entry lists how it scopes authority, its operational cost, and what it does *not* solve.

### Option 0 - Status quo: SSH deploy key (rejected)

- **Auth:** SSH key, repo-scoped, write-enabled.
- **Path/branch scope:** none. Anything goes.
- **Lifetime:** indefinite until revoked.
- **Cost:** zero (already deployed).
- **Why rejected:** scope is the problem statement.

### Option A - Fine-grained Personal Access Token (PAT)

GitHub fine-grained PATs are scoped per-repository and per-permission. Smallest viable scope: `Contents: Read and write` on this repo only.

- **Auth:** HTTPS push with `https://x-access-token:${PAT}@github.com/<owner>/<repo>.git`.
- **Path/branch scope:** none at the token layer; tightened via *push rulesets* (see §5).
- **Lifetime:** max 1 year, must be rotated. GitHub emails the owner before expiry.
- **Identity:** acts as the human user who created the PAT - commits authored by the bot identity in `.env` but pushes audit-logged under the human account.
- **Cost:** ~30 min to set up, recurring rotation work, drop the SSH stack from container/compose.
- **Pros:**
  - Simplest swap. One env var change, no JWT plumbing.
  - Removes openssh-client dependency from the Dockerfile, removes the host bind mount.
  - Permissions are per-repo and per-action; far better than SSH.
- **Cons:**
  - Bound to a human account; if that account is offboarded, automation breaks.
  - 1-year hard expiry → recurring manual work.
  - GitHub audit log shows the human, not the automation.

### Option B - GitHub App with installation token (recommended)

A purpose-built GitHub App installed on the repo. The fetcher exchanges an App private key (JWT) for short-lived installation access tokens (~1 hour TTL) at push time.

- **Auth:** HTTPS push with `https://x-access-token:${INSTALLATION_TOKEN}@github.com/...`.
- **Path/branch scope:** none at the token layer; tightened via push rulesets.
- **Lifetime of token:** ~60 minutes. Lifetime of the App private key: indefinite, but it never leaves the host and never appears in a push.
- **Identity:** acts as the App, e.g. `s7bb-bot[bot]`. No human dependency. Audit log is unambiguous.
- **Cost:** ~1–2 h initial setup (create App, install on repo, store private key, write tiny token-minting helper), small added code path in `pusher.py`.
- **Pros:**
  - Best long-term posture. No expiring secret to rotate on a calendar.
  - Decoupled from human accounts; survives team changes.
  - Token in any single push is valid for ≤1 h, sharply limiting the value of intercepting it in transit / from process memory.
  - Per-permission scope identical in granularity to fine-grained PATs (`contents:write` only).
- **Cons:**
  - Two secrets on the VM (App ID + private key) instead of one PAT, though the private key never travels.
  - Slightly more code: JWT signing (PyJWT) and token-exchange request, ~30 lines.

### Option C - Keep SSH deploy key, add GitHub push ruleset (defense-in-depth only)

Use GitHub *push rulesets* (Repo Settings → Rules → Rulesets) on `main` to:

- Require linear history (blocks force-push).
- Block branch deletion.
- Restrict allowed file paths on push to `data/latest.json` and `data/archive/**`.
- Restrict who can bypass: nobody.

- **Cost:** ~10 min in the GitHub UI. No code changes.
- **Why not on its own:** still leaves the credential overly powerful at the *auth* layer; if push rulesets are ever loosened or bypassed, the SSH key still allows everything. Best treated as an additive layer on top of A or B, not a replacement.

### Option D - VM does not push at all (rejected)

Move the publish to a GitHub Actions workflow triggered via `repository_dispatch`; VM only signals "new data available". Rejected because GitHub would then need a copy of `data/latest.json` to commit, and the only place it exists is the VM - so the VM still needs to upload it (back to the same auth problem) or GH would need to re-fetch from the DB API (forbidden by `CLAUDE.md`: API key must stay off CI).

---

## 5. Recommended Design

**Adopt Option B (GitHub App) as the primary credential. Layer Option C (push ruleset) on top as defense-in-depth.**

Rationale: B fixes the lifetime problem (no calendar rotation), the identity problem (no human dependency), and the scope problem (per-permission). C constrains the damage even if B's private key leaks, by making the *server side* refuse anything that is not the expected change.

If the team decides the App setup cost is not worth it right now, fall back to Option A (fine-grained PAT) - same push code path, just a different way to get the bearer token. The push ruleset (C) is independent of A vs B and should be applied either way.

---

## 6. Architecture

```
┌────────────────────────── VM (host) ──────────────────────────┐
│                                                               │
│   .env                                                        │
│     GITHUB_APP_ID=...                                         │
│     GITHUB_APP_INSTALLATION_ID=...                            │
│     GITHUB_APP_PRIVATE_KEY_PATH=/home/s7bb/.config/.../app.pem│
│                                                               │
│   ┌──────────── s7bb-fetcher container ─────────────┐         │
│   │                                                 │         │
│   │  service.py  ── hourly ──▶  pusher.py           │         │
│   │                              │                  │         │
│   │                              ▼                  │         │
│   │                     github_auth.py              │         │
│   │                       1. read .pem (RO mount)   │         │
│   │                       2. sign 10-min JWT        │         │
│   │                       3. POST /app/installations│         │
│   │                          /{id}/access_tokens    │         │
│   │                       4. return ~60-min token   │         │
│   │                              │                  │         │
│   │            GIT_ASKPASS=token ▼                  │         │
│   │                       git push https://...      │         │
│   └─────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                         GitHub repo, main branch
                         ── push ruleset enforces ──
                         • allowed paths: data/latest.json,
                                           data/archive/**
                         • linear history (no force-push)
                         • no branch delete
                         • no bypass
```

### 6.1 Components

| Component | Responsibility | Inputs | Outputs |
|---|---|---|---|
| `fetcher/src/s7bb_fetcher/github_auth.py` *(new)* | Mint short-lived installation tokens | `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY_PATH` | bearer token string + expiry |
| `fetcher/src/s7bb_fetcher/pusher.py` *(modified)* | Stage, commit, push `data/latest.json` | repo path, token from `github_auth` | push result |
| `docker-compose.yml` *(modified)* | Mount `.pem` read-only; remove SSH key mount | host paths from `.env` | container env |
| `.env.example` *(modified)* | Document new vars; mark SSH vars deprecated | - | - |
| GitHub App `s7bb-publisher` *(new, in GitHub UI)* | Provide identity + permissions | private key (downloaded once) | App ID, Installation ID |
| Repo push ruleset *(new, in GitHub UI)* | Server-side path/branch enforcement | - | rejects out-of-scope pushes |

### 6.2 Authentication flow

1. `pusher.py` calls `github_auth.installation_token()`.
2. `github_auth` reads the `.pem`, builds a JWT (issuer = App ID, exp = now + 9 min, alg = RS256).
3. POSTs to `https://api.github.com/app/installations/{installation_id}/access_tokens`.
4. Receives `{token, expires_at}`. Caches in-process until 60 s before expiry.
5. `pusher.py` sets `GIT_ASKPASS` to a tiny shell that prints the token; runs `git push https://x-access-token@github.com/<owner>/<repo>.git main`.
6. The token is never written to disk.

### 6.3 GitHub App permissions

- **Repository permissions → Contents: Read and write.**
- **All other permissions: No access.**
- **Subscribe to events:** none.
- **Where can this App be installed:** *Only on this account.*
- After creation: install on the `s7bb` repo only (not the whole org/user).

### 6.4 Push ruleset (`main` branch)

Repo Settings → Rules → Rulesets → New branch ruleset:

- **Target:** `main`.
- **Bypass list:** empty.
- **Restrict updates:** require linear history; block force pushes; block branch deletion.
- **Restrict file paths:** allow only `data/latest.json` and `data/archive/**`. Everything else on `main` must come through a PR (which the bot will not be able to open or merge - its scope is `Contents` only, not `Pull requests`).

Human contributors continue to push via PRs reviewed in the GitHub UI; the ruleset applies to direct pushes only and the App does not bypass it.

### 6.5 Key/secret handling

- The App private key (`.pem`) lives at `${GITHUB_APP_PRIVATE_KEY_PATH}` on the host with `chmod 600`, owned by the user that runs `docker compose`.
- It is bind-mounted **read-only** into the container, mirroring the SSH key pattern that exists today (`docker-compose.yml:15`).
- It is referenced by absolute path so rootless containerd/nerdctl can resolve the same path inside and outside the container - same constraint that already drives `user: "0:0"` in `docker-compose.yml:11`.
- It is **not** committed, **not** baked into the image, and **not** logged.

---

## 7. Data Flow Changes

Only the push step changes. Fetch, parse, store, export are untouched.

```
Before:  exporter → latest.json → git commit → git push (SSH, deploy key)
After:   exporter → latest.json → git commit → mint installation token
                                             → git push (HTTPS, bearer)
                                             → ruleset accepts iff path == data/latest.json
```

---

## 8. Error Handling

| Failure | Detection | Behaviour |
|---|---|---|
| `.pem` missing or unreadable | `github_auth` raises `FileNotFoundError`/`PermissionError` | log error, skip this hour's push, retry next hour |
| Token mint API call fails (network, 401, App uninstalled) | non-2xx from GitHub | log status + body, skip this hour's push |
| Token expires mid-push | very rare (60 s safety margin) | catch 401 from `git push`, mint a fresh token once, retry |
| Push rejected by ruleset (e.g. accidental scope creep in `pusher.py`) | `git push` exits non-zero with ruleset message | raise - this is a code bug, not a transient error; do not silently swallow |
| Network blip | `git push` exits non-zero | log; next hour retries |

The existing `_export_job` `except Exception: logger.exception(...)` in `service.py:49-50` already isolates push failures from fetch and export.

---

## 9. Migration Plan

Each step is independently revertible.

1. **Create the GitHub App** in the user's GitHub account. Download the `.pem`. Note App ID.
2. **Install the App** on the `s7bb` repo only. Note Installation ID.
3. **Place the `.pem`** on the VM at the chosen path, `chmod 600`, owned by the docker-running user.
4. **Add the push ruleset** in the GitHub UI (independent of code; can be done first as a safety net).
5. **Implement `github_auth.py`** with unit tests (JWT contents, token caching, retry on 401).
6. **Modify `pusher.py`** to use bearer-token HTTPS push behind a feature flag: if `GITHUB_APP_ID` is set, use App auth; else fall back to existing SSH path.
7. **Update `docker-compose.yml`** to mount `.pem` (still keep the SSH mount for one release).
8. **Update `.env.example`** with the new variables and a deprecation note on `SSH_DEPLOY_KEY_PATH`.
9. **Update `Dockerfile`** - keep `openssh-client` for now; remove in a follow-up after burn-in.
10. **Cut over** by setting the App vars in `.env` and restarting the container. Verify the next hourly push succeeds and is authored by the App.
11. **Burn-in for ~1 week.** Watch logs.
12. **Remove the SSH deploy key** from the GitHub repo settings; remove `SSH_DEPLOY_KEY_PATH` and the SSH mount from `docker-compose.yml`; remove the SSH fallback branch from `pusher.py`; remove `openssh-client` from the Dockerfile.
13. **Document rotation** in `README.md` (App private key rotation procedure: generate new key in App settings, replace `.pem`, restart container, delete old key).

---

## 10. Testing

- **Unit:** `tests/test_github_auth.py` - JWT claims (iss, iat, exp), RS256 signature verifies with public key extracted from the test key, token caching honours expiry, mocked HTTP exchange.
- **Unit:** `tests/test_pusher.py` *(new)* - exercise the App-auth branch with a mocked token provider and a temp git repo; cover the SSH fallback branch until removal step 12.
- **Integration (manual, once):** push a no-op commit from the VM after step 10 of the migration; confirm GitHub shows the commit authored as `s7bb-publisher[bot]`.
- **Negative integration (manual, once):** locally craft a commit that touches `site/index.html` and attempt to push with the App token; confirm the push ruleset rejects it. Document the rejection message in `features/secure-github-access/migration-notes.md`.

---

## 11. Risks and Open Questions

- **Risk:** GitHub App permissions UI changes. Mitigation: pin the exact required scopes in this doc and in `README.md`.
- **Risk:** PyJWT or `cryptography` dependency adds ~MB to the image. Mitigation: acceptable; pin to exact versions per the `=X.Y.Z` rule in `CLAUDE.md`.
- **Open question (decision needed before implementation):** human owner of the App. Recommended: the same GitHub account that owns the repo. Alternative: a dedicated machine account, which adds an account to manage and a 2FA recovery surface; not recommended for this small project.
- **Open question:** retain the archive write capability (`data/archive/**`)? The current code only pushes `data/latest.json`, but the architecture in `CLAUDE.md` mentions monthly archive dumps. The push ruleset above allows it pre-emptively; if the archives are written by a different process, revisit.

---

## 12. Out of Scope (for follow-up features)

- Commit signing with the App's GPG key (GitHub auto-signs App commits if enabled - cheap win, separate task).
- Migrating other automations (e.g. release tagging) to the same App.
- Alerting on consecutive push failures (Healthchecks.io ping or similar).
- Rotating the App private key on a schedule rather than on suspicion.
