---
name: release-hygiene
description: Use when writing commit messages, bumping versions, editing CHANGELOG.md, cutting releases, or auditing release-related diffs. Enforces Conventional Commits, Semantic Versioning, and Keep a Changelog.
---

# Release Hygiene

Three linked standards govern commits, versions, and changelogs:

- **Conventional Commits 1.0.0** — commit message format (https://www.conventionalcommits.org)
- **Semantic Versioning 2.0.0** — version number rules (https://semver.org)
- **Keep a Changelog 1.1.0** — `CHANGELOG.md` format (https://keepachangelog.com)

They interlock: commit `type` + `!` flag drive the SemVer bump, which drives the `CHANGELOG.md` section header.

## When to Use

Trigger on any of:
- Drafting/reviewing a commit message
- Bumping version in `pyproject.toml`, `package.json`, `Cargo.toml`, etc.
- Adding/editing `CHANGELOG.md`
- Cutting a release (tag `vX.Y.Z`)
- Auditing a PR diff for release-readiness

Skip when: hotfix branches with explicit different convention, or repo CLAUDE.md overrides.

## Conventional Commits

Format:

```
<type>[optional scope][!]: <description>

[optional body]

[optional footer(s)]
```

**Allowed types** (project-locked set in s7bb CLAUDE.md):

| Type | Use | SemVer impact |
|------|-----|---------------|
| `feat` | new user-facing feature | MINOR |
| `fix` | bug fix | PATCH |
| `docs` | docs only | none |
| `chore` | tooling, deps, no src logic | none |
| `refactor` | restructure, no behavior change | none |
| `perf` | performance improvement | PATCH |
| `test` | tests only | none |
| `style` | formatting, whitespace | none |
| `revert` | revert prior commit | depends |

**Breaking changes**: append `!` after type/scope AND add `BREAKING CHANGE:` footer.

```
feat(api)!: drop SSH deploy key path

BREAKING CHANGE: GITHUB_PAT env var now required; SSH_DEPLOY_KEY removed.
```

Rules:
- Subject in imperative mood, lowercase, no trailing period
- Subject ≤72 chars (≤50 preferred)
- Body wraps at 72 chars, blank line after subject
- Scope is optional, lowercase, parenthesized: `feat(parser):`
- One logical change per commit

## Semantic Versioning

Version = `MAJOR.MINOR.PATCH` (e.g. `1.4.2`).

| Bump | When | Trigger |
|------|------|---------|
| MAJOR | breaking API/data-schema change | any `!` commit or `BREAKING CHANGE:` footer |
| MINOR | new feature, backwards-compatible | any `feat:` commit since last release |
| PATCH | bug/perf fix, backwards-compatible | only `fix:` / `perf:` since last release |

Rules:
- `0.y.z` = unstable; anything may change. `1.0.0` = first stable public API.
- Pre-release: `1.0.0-alpha.1`, `1.0.0-rc.2`. Lower precedence than `1.0.0`.
- Build metadata: `1.0.0+sha.abc123`. Ignored for precedence.
- Once published, never re-use a version. Bump and re-tag.

## Keep a Changelog

Single `CHANGELOG.md` at repo root. Reverse chronological. Latest version on top.

Required structure:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New feature description (user-visible effect)

### Fixed
- Bug fix description

## [1.2.0] - 2026-05-06

### Added
- ...

### Changed
- ...

[Unreleased]: https://github.com/USER/REPO/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/USER/REPO/compare/v1.1.0...v1.2.0
```

**Section headers** (use only these, in this order, omit empty ones):

| Section | Use |
|---------|-----|
| `Added` | new features |
| `Changed` | changes to existing functionality |
| `Deprecated` | soon-to-be-removed features |
| `Removed` | removed features |
| `Fixed` | bug fixes |
| `Security` | vulnerability fixes |

Rules:
- Every user-facing change goes under `[Unreleased]` BEFORE merging
- Entries describe **user-visible effect**, not code paths or file names
- Keep entries human-readable; not just commit subjects pasted in
- Date format: `YYYY-MM-DD` (ISO 8601)
- Compare links at bottom

## Release Workflow

Cutting `X.Y.Z`:

1. Verify `[Unreleased]` section reflects all merged changes
2. Determine bump from commits since last tag:
   - any `!` or `BREAKING CHANGE:` → MAJOR
   - else any `feat:` → MINOR
   - else PATCH
3. Bump version in source-of-truth file (`pyproject.toml`, `package.json`, etc.)
4. In `CHANGELOG.md`: rename `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`, add fresh empty `[Unreleased]` above, update compare links
5. Commit: `chore(release): X.Y.Z`
6. Tag: `git tag vX.Y.Z` (lowercase `v` prefix)
7. Push commits + tag

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `feat: Add X.` (capitalized, period) | `feat: add X` (imperative, lowercase, no period) |
| Breaking change without `!` | Append `!` AND add `BREAKING CHANGE:` footer |
| `fix:` for new feature | Use `feat:` — type drives SemVer bump |
| Bumping MINOR for bug fix | PATCH for `fix:`/`perf:` only |
| `CHANGELOG.md` entry = commit subject | Rewrite as user-visible effect |
| Editing released version section | Never. Add note under `[Unreleased]`. |
| Re-tagging existing version | Bump and tag new version |
| Forgetting compare links | Add at bottom of CHANGELOG, update on each release |
| `v1.2.0` in `pyproject.toml` | Source files use `1.2.0`; tag uses `v1.2.0` |

## Quick Reference

**Decide commit type:**

```
behavior change visible to user? → feat or fix
  bug? → fix
  new capability? → feat
  breaking? → add ! and BREAKING CHANGE: footer

no behavior change?
  faster? → perf
  cleanup? → refactor
  docs? → docs
  tests only? → test
  deps/tooling? → chore
  formatting? → style
```

**Decide SemVer bump:** scan commits since last tag, take highest impact (MAJOR > MINOR > PATCH).

**CHANGELOG entry template:**
```markdown
### Added
- Hourly export of latest.json to data/ (visible as faster site refresh).
```
