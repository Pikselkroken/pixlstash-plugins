"""Check the Python in the documentation at least parses.

`ruff.toml` excludes Markdown from the formatter (it reflows doc snippets into
machine output), and ruff's linter never reads Markdown at all, so without this
the code a reader is told to copy is the only Python in the repository nobody
checks. That is how a broken example gets published.

This compiles every ```python fence. It does not run them, so it catches a typo
or a syntax error, not a wrong claim; the semantics are still on the author.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"```python\n(.*?)```", re.DOTALL)

SNIPPETS = [
    pytest.param(md.relative_to(ROOT).as_posix(), index, code, id=f"{md.name}:{index}")
    for md in sorted([*ROOT.glob("*.md"), *ROOT.glob("docs/*.md")])
    for index, code in enumerate(FENCE.findall(md.read_text()))
]


def test_documentation_has_python_examples():
    assert SNIPPETS, "no ```python fences found; has the fence syntax changed?"


@pytest.mark.parametrize(("path", "index", "code"), SNIPPETS)
def test_python_snippets_parse(path: str, index: int, code: str):
    try:
        compile(code, f"{path} (snippet {index})", "exec")
    except SyntaxError as exc:
        pytest.fail(f"{path}: snippet {index} does not parse: {exc}")
