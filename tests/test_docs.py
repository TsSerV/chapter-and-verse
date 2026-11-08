"""Every relative link in the README and in docs/ leads to a file and heading that exist."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
# [text](target), but not images.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def anchors(page: Path) -> set[str]:
    # GitHub's heading IDs: lower case, punctuation dropped, spaces to hyphens.
    headings = re.findall(r"^#+ (.+)$", page.read_text(), flags=re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.name)
def test_relative_links_resolve(page: Path) -> None:
    for target in LINK.findall(page.read_text()):
        if target.startswith(("http://", "https://")):
            continue
        path, _, anchor = target.partition("#")
        linked = (page.parent / path) if path else page
        assert linked.exists(), f"{page.name} links to a missing file: {target}"
        if anchor:
            assert anchor in anchors(linked), f"{page.name} links to a missing heading: {target}"
