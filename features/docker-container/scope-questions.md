# Docker Container Feature — Scope Questions

## Container Build
1. Base image preference? `python:3.12-slim`, `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` (uv pre-installed), or something else?
   **Answer:** `python:3.12-slim`
2. Build image locally and push to a registry, or build on the VM directly from the repo?
   **Answer:** Build locally on VM, no registry push.

## Runtime
3. Secrets (API key/client ID) — pass as env vars at runtime, or mount an `.env` file into the container?
   **Answer:** `.env` file, loaded via docker-compose `env_file`.
4. SQLite DB (`data/s7bb.db`) — mount as a host volume so data survives container restarts/upgrades?
   **Answer:** Single host volume covers both DB and latest.json.
5. `data/latest.json` — same volume, or separate mount? (It is git-committed hourly, so the push script needs to reach the repo on the host.)
   **Answer:** Same volume as Q4 — `data/` directory mounted as one host volume.

## Scheduling
6. Keep systemd timers on the host calling `docker run` for each tick, or run a scheduler *inside* the container (e.g., `crond`, `supercrond`)?
   **Answer:** Python process runs as long-running service inside container; fetcher called periodically from within that process.
6a. How should the internal scheduler be configured?
    - Interval hardcoded in Python (e.g., `time.sleep(300)` loop)?
    - Interval as env var (e.g., `FETCH_INTERVAL_SECONDS=300`)?
    - Cron expression as env var (e.g., `FETCH_CRON=*/5 * * * *`)?
    - Use a scheduler library (e.g., `APScheduler`, `schedule`)?
    **Answer:** Cron expression in `.env` file (e.g., `FETCH_CRON=*/5 * * * *`). Needs a scheduler library — `APScheduler` fits well.
7. The `push-data.sh` script needs git + SSH deploy key access — run that inside the container too, or keep it on the host and only containerize the Python fetcher/exporter?
   **Discussion:**
   - Option A: stay on host (clean container, but dual scheduling systems)
   - Option B: migrate to Python inside container (unified pipeline, SSH deploy key mounted as volume)
   **Answer:** Option B — migrate `push-data.sh` to Python, run inside container. SSH deploy key mounted as volume.
   **Follow-up:** Separate cron expressions — `FETCH_CRON` (e.g. `*/5 * * * *`) and `EXPORT_CRON` (e.g. `0 * * * *`) both in `.env`.

## Compose
8. Single service (`s7bb-fetcher`) or two (`fetcher` + `exporter`) since they have different cadences?
   **Answer:** Single service — both fetch and export run inside one container.
9. Any need for a second service alongside it (e.g., a lightweight web server to serve `latest.json` locally for dev)?
   **Answer:** Yes — lightweight dev web server as second compose service to serve `latest.json`.

## Key architectural decisions (highest impact)
- Q6 and Q7 determine complexity most — scheduler location and whether git/SSH lives inside or outside the container.
