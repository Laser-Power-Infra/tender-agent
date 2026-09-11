"""Self-check for parse_document._page_markdowns: one export pass, per-page loop only as fallback.

Run: python test_page_markdowns.py
No installed deps needed — docling/pypdf imports in this module are lazy.
"""
from ingestion.nodes.parse_document import _PAGE_BREAK, _page_markdowns


class FakeDoc:
    """Counts export calls so the test can prove the fast path does exactly one."""

    def __init__(self, pages, supports_placeholder=True):
        self.pages = pages
        self.supports_placeholder = supports_placeholder
        self.calls = 0

    def export_to_markdown(self, page_no=None, page_break_placeholder=None):
        self.calls += 1
        if page_break_placeholder is not None:
            if not self.supports_placeholder:
                raise TypeError("unexpected keyword argument 'page_break_placeholder'")
            return page_break_placeholder.join(self.pages)
        if page_no is None:
            raise AssertionError("caller must pass page_no or page_break_placeholder")
        return self.pages[page_no - 1]


def test_single_pass_splits_every_page():
    doc = FakeDoc(["page one", "page two", "page three"])
    out = _page_markdowns(doc, 3)
    assert [md for md, _ in out] == ["page one", "page two", "page three"], out
    assert all(err is None for _, err in out), out
    assert doc.calls == 1, f"fast path must export once, did {doc.calls}"


def test_falls_back_when_placeholder_unsupported():
    doc = FakeDoc(["a", "b"], supports_placeholder=False)
    out = _page_markdowns(doc, 2)
    assert [md for md, _ in out] == ["a", "b"], out
    # 1 failed attempt + 1 per page
    assert doc.calls == 3, doc.calls


def test_falls_back_on_segment_count_mismatch():
    # docling returned 2 segments but the page count says 3 — trust the page count
    doc = FakeDoc(["a", "b"])
    out = _page_markdowns(doc, 3)
    assert len(out) == 3, out
    assert out[2][1] is not None, "the page beyond the export must carry an error, not a silent None"


def test_empty_page_is_none_not_blank():
    doc = FakeDoc(["real text", "   "])
    out = _page_markdowns(doc, 2)
    assert out[1][0] is None, "a whitespace-only page must normalize to None so it is marked failed"


def test_page_break_not_left_in_output():
    doc = FakeDoc(["one", "two"])
    for md, _ in _page_markdowns(doc, 2):
        assert _PAGE_BREAK not in (md or ""), md


if __name__ == "__main__":
    test_single_pass_splits_every_page()
    test_falls_back_when_placeholder_unsupported()
    test_falls_back_on_segment_count_mismatch()
    test_empty_page_is_none_not_blank()
    test_page_break_not_left_in_output()
    print("page markdown self-check passed")
