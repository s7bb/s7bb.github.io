"""Regression guard: docker-compose.yml must wire s7bb-fetcher's /repo
to the auto-provisioned s7bb-data clone, never the code repo.

The original production defect mounted `.:/repo` (the code repo) on
s7bb-fetcher. The repo_identity preflight catches it only at startup;
this fails CI the moment the compose mount regresses. Stdlib-only —
pyyaml is not a project dependency.
"""

import re
from pathlib import Path

import pytest

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _service_block(text: str, name: str) -> str:
    """Return the lines of one 2-space-indented compose service block."""
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
        if ln and not ln[0].isspace():          # top-level key (e.g. volumes:)
            end = j
            break
        if re.match(r"  \S", ln) and not ln.startswith("   "):  # next service
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def compose_text() -> str:
    assert _COMPOSE.is_file(), f"{_COMPOSE} missing"
    return _COMPOSE.read_text()


def test_fetcher_does_not_mount_the_code_repo(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    # The exact defect: bind-mounting the code repo working tree at /repo.
    assert not re.search(r"^\s*-\s*\.:/repo\s*$", block, re.M), (
        "s7bb-fetcher mounts '.:/repo' — that is the CODE repo. It must "
        "mount the s7bb-repo named volume (the s7bb-data clone)."
    )


def test_fetcher_mounts_s7bb_repo_volume(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert re.search(r"^\s*-\s*s7bb-repo:/repo\s*$", block, re.M), (
        "s7bb-fetcher must mount 's7bb-repo:/repo'"
    )


def test_fetcher_depends_on_repo_init_completed(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert "depends_on:" in block
    assert "s7bb-repo-init:" in block
    assert "condition: service_completed_successfully" in block


def test_repo_init_service_and_volume_declared(compose_text):
    assert "\n  s7bb-repo-init:\n" in compose_text, "s7bb-repo-init service missing"
    init = _service_block(compose_text, "s7bb-repo-init")
    assert "s7bb-data.git" in init, "init must clone the s7bb-data repo"
    assert re.search(r"^\s*-\s*s7bb-repo:/repo-clone\s*$", init, re.M), (
        "s7bb-repo-init must populate the s7bb-repo volume at /repo-clone"
    )
    # top-level named volume must be declared
    vol = compose_text.split("\nvolumes:\n", 1)
    assert len(vol) == 2 and re.search(r"^\s+s7bb-repo:\s*$", vol[1], re.M), (
        "top-level 'volumes:' must declare s7bb-repo"
    )
