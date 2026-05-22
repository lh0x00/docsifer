from docsifer.core.html_cleaner import clean_html


def test_removes_style_script_noscript() -> None:
    html = (
        "<html><head><style>body{}</style><script>x()</script></head>"
        "<body><noscript>nope</noscript><p>hi</p></body></html>"
    )
    out = clean_html(html)
    assert "<style" not in out.lower()
    assert "<script" not in out.lower()
    assert "<noscript" not in out.lower()
    assert "hi" in out


def test_removes_hidden_attribute_and_inline_styles() -> None:
    html = (
        "<div hidden>secret</div>"
        '<div style="display:none">also-hidden</div>'
        '<div style="display: none;">spaced</div>'
        '<div aria-hidden="true">aria</div>'
        "<p>visible</p>"
    )
    out = clean_html(html)
    assert "secret" not in out
    assert "also-hidden" not in out
    assert "spaced" not in out
    assert "aria" not in out
    assert "visible" in out


def test_empty_input_returns_empty() -> None:
    assert clean_html("") == ""


def test_malformed_html_does_not_raise() -> None:
    out = clean_html("<<<<><><>")
    assert isinstance(out, str)
