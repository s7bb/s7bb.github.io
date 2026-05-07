# Next Update Display

## Summary

Add "Nächstes Update: HH:MM" next to existing "Stand:" timestamp in the today-page footer so non-technical users know when fresh data is expected.

## Motivation

`data/latest.json` is regenerated and pushed at the top of every hour by the production VM (`EXPORT_CRON="0 * * * *"`). Visitors currently only see when the data was last refreshed (`Stand`). Telling them when the next refresh is expected reduces confusion when delays are stale.

## Scope

- In: `site/src/pages/today.ts` footer line, plus a new unit test.
- Out: JSON schema changes, CSS changes, archive page, charts, fetcher code.

## Design

### Source of truth

The fetcher's export cron (`0 * * * *`) is fixed in production. Computing the next update client-side from `data.generated_at` is sufficient and keeps the JSON schema unchanged.

### Helper

New module-level helper in `site/src/pages/today.ts`:

```ts
export function nextUpdate(generatedAt: string): Date {
  const d = new Date(generatedAt);
  d.setUTCMinutes(0, 0, 0);
  d.setUTCHours(d.getUTCHours() + 1);
  return d;
}
```

Behavior:
- Floor `generated_at` to the hour (UTC), then add 1h.
- Always strictly after `generated_at`, even if `generated_at` is exactly on the hour.
- Day rollover handled by `Date` arithmetic (23:30 UTC → 00:00 UTC next day).

### Render change

Replace `today.ts:69`:

```ts
<p class="data-age">
  Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}
  · Nächstes Update: ${formatTime(nextUpdate(data.generated_at).toISOString())}
</p>
```

`formatTime` already returns `HH:MM` in `de-DE` locale (line 6).

### Tests

New file `site/src/pages/today.test.ts` covering `nextUpdate`:

| Input (UTC) | Expected (UTC) |
|---|---|
| `2026-05-07T14:00:00Z` | `2026-05-07T15:00:00Z` |
| `2026-05-07T14:00:30Z` | `2026-05-07T15:00:00Z` |
| `2026-05-07T14:59:59Z` | `2026-05-07T15:00:00Z` |
| `2026-05-07T23:30:00Z` | `2026-05-08T00:00:00Z` |

Export `nextUpdate` from `today.ts` to enable testing.

## Non-Goals

- Live countdown / `setInterval` updates.
- Reflecting actual cron config from the fetcher (assumes hourly).
- Status indicator if data is overdue.

## Risks

- If `EXPORT_CRON` changes from `0 * * * *`, displayed next-update time drifts from reality. Mitigation: cron is locked in CLAUDE.md; if it ever changes, swap helper or move computation server-side.

## Files Touched

- `site/src/pages/today.ts` — add helper, edit footer.
- `site/src/pages/today.test.ts` — new file.
- `CHANGELOG.md` — entry under `[Unreleased]` › `Added`.
