"""Regression guard: docker-compose.yml must wire s7bb-fetcher's /repo
to the auto-provisioned s7bb-data clone, never the code repo.

The original production defect mounted `.:/repo` (the code repo) on
s7bb-fetcher. The repo_identity preflight catches it only at startup;
this fails CI the moment the compose mount regresses. Stdlib-only —
pyyaml is not a project dependency.

The s7bb-data clone now lives on a gitignored host bind mount
(`./data-repo:/repo`), not the former `s7bb-repo` named volume — a host
bind mount survives `docker volume prune`. These tests assert the
bind-mount wiring and that the discard-visibility WARN guard is present
in s7bb-repo-init.

Scope: guards the *short-form* bind of the code repo at /repo
(`.`/`./` -> /repo, any mode/quoting). Long-form `type: bind` mounts
are intentionally out of scope — the project only uses short-form and
parsing long-form reliably without a YAML lib is not worth the
fragility.
"""

import re
from pathlib import Path

import pytest

# Layout assumed: <repo>/fetcher/tests/test_compose_wiring.py
_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# `.`/`./` -> /repo (the defect) in short form: optional quotes, "." or
# "./", optional :ro/:rw/:z mode. Catches the historical bare form AND
# its trivially-equivalent paraphrases.
_CODE_REPO_AT_REPO = re.compile(
    r"""^\s*-\s*["']?\.\/?:/repo(?::[a-z]+)?["']?\s*$""", re.M
)


def _service_block(text: str, name: str) -> str:
    """Return the lines of one 2-space-indented compose service block.

    Terminates at the next top-level key or the next 2-space-indented
    *service key*. Comments and deeper-indented lines do NOT end the
    block — a 2-space comment must not silently truncate it.
    """
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln == f"  {name}:":
            start = i
            break
    assert start is not None, f"service {name!r} not found in docker-compose.yml"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln and not ln[0].isspace():            # top-level key (e.g. volumes:)
            end = j
            break
        if (
            re.match(r"  \S", ln)
            and not ln.startswith("   ")
            and not ln.lstrip().startswith("#")   # 2-space comment != next service
        ):
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def compose_text() -> str:
    assert _COMPOSE.is_file(), f"{_COMPOSE} missing"
    return _COMPOSE.read_text().replace("\r\n", "\n")  # CRLF-safe


def test_fetcher_does_not_mount_the_code_repo(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    # The defect and its :ro/:rw/quoted paraphrases: bind-mounting the
    # code repo working tree at /repo.
    assert not _CODE_REPO_AT_REPO.search(block), (
        "s7bb-fetcher mounts the code repo at /repo ('.:/repo'). It must "
        "mount the ./data-repo host bind mount (the s7bb-data clone)."
    )


def test_fetcher_mounts_data_repo_bind(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert re.search(r"^\s*-\s*\./data-repo:/repo\s*$", block, re.M), (
        "s7bb-fetcher must mount './data-repo:/repo' (host bind mount)"
    )


def test_fetcher_depends_on_repo_init_completed(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert "depends_on:" in block, "s7bb-fetcher must declare depends_on"
    dep = block.split("depends_on:", 1)[1]
    assert "s7bb-repo-init:" in dep and "service_completed_successfully" in dep, (
        "s7bb-fetcher must depend_on s7bb-repo-init with "
        "condition: service_completed_successfully"
    )


def test_repo_init_clones_into_data_repo_bind(compose_text):
    assert re.search(r"^  s7bb-repo-init:\s*$", compose_text, re.M), (
        "s7bb-repo-init service missing"
    )
    init = _service_block(compose_text, "s7bb-repo-init")
    assert "s7bb-data.git" in init, "init must clone the s7bb-data repo"
    assert re.search(r"^\s*-\s*\./data-repo:/repo-clone\s*$", init, re.M), (
        "s7bb-repo-init must populate './data-repo:/repo-clone'"
    )
    m = re.search(r"^volumes:\s*$", compose_text, re.M)
    assert m, "top-level 'volumes:' block missing"
    assert not re.search(r"^\s+s7bb-repo:\s*$", compose_text[m.end():], re.M), (
        "top-level 'volumes:' must NOT declare s7bb-repo — the named "
        "volume was replaced by the ./data-repo host bind mount"
    )


def test_repo_init_warns_on_discard(compose_text):
    init = _service_block(compose_text, "s7bb-repo-init")
    assert "rev-list --count origin/main..HEAD" in init, (
        "s7bb-repo-init must count commits ahead of origin/main before reset"
    )
    assert "WARN: s7bb-repo-init discarding" in init, (
        "s7bb-repo-init must log a WARN when it discards unpushed commits"
    )
    assert "reset --hard origin/main" in init, (
        "s7bb-repo-init must still reset --hard origin/main (behavior unchanged)"
    )
