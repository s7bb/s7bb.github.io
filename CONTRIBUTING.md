# Contributing

## Commit messages — Conventional Commits

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Allowed types:

| Type | When to use |
|---|---|
| `feat` | New user-facing feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `chore` | Build, tooling, dependencies, release |
| `refactor` | Code change with no behaviour change |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `style` | Formatting, whitespace (no logic change) |
| `revert` | Reverts a previous commit |

Breaking changes: append `!` to the type and add a `BREAKING CHANGE:` footer.

```
feat!: rename delay field in latest.json

BREAKING CHANGE: `delay` renamed to `delay_minutes` in all JSON output.
```

## Changelog — Keep a Changelog

Every user-facing change must be recorded in `CHANGELOG.md` under `[Unreleased]` **before** merging.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Use these sections as needed:

- **Added** — new features
- **Changed** — changes to existing behaviour
- **Deprecated** — features that will be removed
- **Removed** — removed features
- **Fixed** — bug fixes
- **Security** — security fixes

Write entries from the user's perspective, not the code's. Describe what changed, not how.

```markdown
## [Unreleased]

### Fixed
- Delay shown as 0 for cancelled trains instead of "ausgefallen"
```

## Versioning — Semantic Versioning

This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (`MAJOR.MINOR.PATCH`):

- **MAJOR** — breaking change to `latest.json` schema or CLI interface
- **MINOR** — new feature, backwards compatible
- **PATCH** — bug fix, backwards compatible

## Release process

1. Update version in `fetcher/pyproject.toml`.
2. Rename `[Unreleased]` in `CHANGELOG.md` to `[X.Y.Z] - YYYY-MM-DD` and add a new empty `[Unreleased]` section above it.
3. Commit: `chore(release): X.Y.Z`
4. Tag: `git tag vX.Y.Z`
5. Push branch and tag: `git push && git push --tags`
