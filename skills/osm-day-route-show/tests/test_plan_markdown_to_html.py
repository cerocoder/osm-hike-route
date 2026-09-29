from render_map import plan_markdown_to_html


def test_headings_become_h2_h3_h4():
    html = plan_markdown_to_html("# Title\n\n## Section\n\n### Sub")
    assert "<h2>Title</h2>" in html
    assert "<h3>Section</h3>" in html
    assert "<h4>Sub</h4>" in html


def test_plain_lines_are_paragraphs_not_list_items():
    html = plan_markdown_to_html("first line\nsecond line\n\nnext paragraph")
    assert html == "<p>first line second line</p><p>next paragraph</p>"


def test_lists_and_wrapped_list_items():
    html = plan_markdown_to_html("- one\n  continued\n- two\n\n1. a\n2. b")
    assert html == "<ul><li>one continued</li><li>two</li></ul><ul><li>a</li><li>b</li></ul>"


def test_italic_bold_code_and_links():
    html = plan_markdown_to_html("*note* and **bold** and `x` [site](https://e.com)")
    assert "<i>note</i>" in html and "<b>bold</b>" in html and "<code>x</code>" in html
    assert '<a href="https://e.com" target="_blank" rel="noopener">site</a>' in html


def test_bold_is_not_mistaken_for_italic():
    assert plan_markdown_to_html("**Danger:** text") == "<p><b>Danger:</b> text</p>"


def test_tables_render_with_wrapper():
    html = plan_markdown_to_html("| A | B |\n|---|---|\n| 1 | 2 |")
    assert '<div class="table-wrap"><table>' in html
    assert "<th>A</th>" in html and "<td>2</td>" in html


def test_table_directly_after_heading_and_before_paragraph():
    html = plan_markdown_to_html("### T\n| A |\n|---|\n| 1 |\n\n*src*")
    assert html.index("<h4>") < html.index("<table>") < html.index("<i>src</i>")


def test_html_in_plan_text_is_escaped():
    html = plan_markdown_to_html("## <script>alert(1)</script>\n\n- <img src=x onerror=y>")
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


def test_empty_input():
    assert plan_markdown_to_html("") == ""
