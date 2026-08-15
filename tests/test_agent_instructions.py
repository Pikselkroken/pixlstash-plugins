"""``AGENTS.md`` and ``CLAUDE.md`` must stay byte-identical.

Two filenames exist because different tools look for different ones, not
because there are two sets of instructions. A copy that drifts is worse than no
copy at all: whichever file an agent happens to read, it must get the same
rules, and nobody notices a silent divergence in a file only machines read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"

# Linked from the instructions, and the whole point of them.
REFERENCED_DOCS = [
    "docs/writing-captioning-plugins.md",
    "docs/writing-image-plugins.md",
    "README.md",
]


@pytest.mark.parametrize("path", [AGENTS, CLAUDE], ids=lambda p: p.name)
def test_instruction_file_exists(path: Path):
    assert path.is_file(), f"{path.name} is missing"
    assert path.read_text().strip(), f"{path.name} is empty"


def test_agents_and_claude_are_identical():
    assert AGENTS.read_bytes() == CLAUDE.read_bytes(), (
        "AGENTS.md and CLAUDE.md have diverged. They are one document under two "
        "names, so copy whichever you edited over the other: "
        "`cp AGENTS.md CLAUDE.md`"
    )


@pytest.mark.parametrize("target", REFERENCED_DOCS)
def test_referenced_documents_exist(target: str):
    """A dead pointer in the instructions sends an agent guessing instead."""
    assert target in AGENTS.read_text(), f"AGENTS.md no longer points at {target}"
    assert (ROOT / target).is_file(), f"{target} is referenced but does not exist"
