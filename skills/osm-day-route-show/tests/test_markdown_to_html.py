from render_map import markdown_to_html


def test_plain_bullet_list_unaffected():
    html = markdown_to_html("- Первое\n- Второе\n")
    assert html == "<ul><li>Первое</li><li>Второе</li></ul>"


def test_numbered_list_unaffected():
    html = markdown_to_html("1. Первое\n2. Второе\n")
    assert html == "<ul><li>Первое</li><li>Второе</li></ul>"


def test_simple_table_renders_as_real_table_not_one_run_on_bullet():
    md = (
        "| Точка | Тип | Уровень |\n"
        "|---|---|---|\n"
        "| Casas del Pozo | sight | web-sourced |\n"
        "| La Sopeña | historic_viewpoint | web-sourced |\n"
    )
    html = markdown_to_html(md)

    assert "<table>" in html
    assert "<li>" not in html  # this is the exact bug being fixed: no run-on bullet
    assert html.count("<tr>") == 3  # 1 header row + 2 data rows
    assert "<th>Точка</th>" in html
    assert "<th>Тип</th>" in html
    assert "<td>Casas del Pozo</td>" in html
    assert "<td>web-sourced</td>" in html


def test_table_without_leading_or_trailing_pipes():
    md = "Точка | Тип\n--- | ---\nRodник | spring\n"
    html = markdown_to_html(md)
    assert "<th>Точка</th>" in html
    assert "<td>Rodник</td>" in html


def test_table_cells_get_inline_markdown_and_escaping():
    md = (
        "| Название | Источник |\n"
        "|---|---|\n"
        '| Casas del Pozo & Co | [mapaymochila.es](https://mapaymochila.es/d7slp) |\n'
    )
    html = markdown_to_html(md)
    assert "Casas del Pozo &amp; Co" in html
    assert '<a href="https://mapaymochila.es/d7slp" target="_blank" rel="noopener">mapaymochila.es</a>' in html


def test_table_stops_at_blank_line_and_following_list_still_renders():
    md = (
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "\n"
        "- Обычный пункт списка\n"
    )
    html = markdown_to_html(md)
    assert html.index("</table>") < html.index("<ul>")
    assert "<li>Обычный пункт списка</li>" in html


def test_paragraph_before_table_is_rendered_as_separate_list_block():
    md = (
        "Некоторый вводный текст.\n"
        "\n"
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
    )
    html = markdown_to_html(md)
    assert "<li>Некоторый вводный текст.</li>" in html
    assert "<table>" in html
    assert html.index("</ul>") < html.index("<table>")


def test_table_with_no_trailing_blank_line_at_end_of_section():
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    html = markdown_to_html(md)
    assert html.count("<tr>") == 2
    assert "<td>2</td>" in html


def test_pipe_without_a_following_separator_row_is_not_treated_as_a_table():
    md = "Вариант `a|b` — просто текст, не таблица.\n"
    html = markdown_to_html(md)
    assert "<table>" not in html
    assert "<li>" in html


import pytest


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "\tjava\x01script:alert(1)",
    "data:text/html,<b>x</b>", "vbscript:x", "file:///etc/passwd", "/relative/path",
])
def test_unsafe_or_relative_link_targets_are_not_linked(url):
    html = markdown_to_html(f"- [x]({url})\n")
    assert "<a " not in html
    assert "[x](" in html


@pytest.mark.parametrize("url", ["https://e.com", "http://e.com", "mailto:a@b.c", "HTTPS://E.COM"])
def test_http_https_mailto_links_still_linked(url):
    html = markdown_to_html(f"- [x]({url})\n")
    assert f'<a href="{url}"' in html


def test_wikipedia_url_with_parentheses_still_linked():
    url = "https://es.wikipedia.org/wiki/L%C3%ADnea_C-5_(Cercan%C3%ADas_Madrid)"
    assert f'<a href="{url}"' in markdown_to_html(f"- [x]({url})\n")
