from skimlint.text import analyze_text


def test_counts_words_per_paragraph_and_reports_line():
    report = analyze_text("# Title\n\nOne two three.\n\nFour five six seven eight.\n")

    assert [(p.line, p.words) for p in report.paragraphs] == [(3, 3), (5, 5)]
    assert report.longest.line == 5


def test_list_items_and_quotes_are_paragraphs():
    report = analyze_text("- one two\n- three four five\n\n> six seven\n")

    assert [p.words for p in report.paragraphs] == [2, 3, 2]


def test_headings_count_toward_words_but_are_not_blocks():
    report = analyze_text("# Big heading here\n\nOne two.\n")

    assert [p.words for p in report.paragraphs] == [2]
    assert report.words == 3 + 2


def test_table_cells_are_blocks_with_their_row_line():
    markdown = "| a b | c |\n|---|---|\n| d | e f g |\n"

    report = analyze_text(markdown)

    assert [(p.kind, p.line, p.words) for p in report.paragraphs] == [
        ("cell", 1, 2), ("cell", 1, 1), ("cell", 3, 1), ("cell", 3, 3),
    ]


def test_code_blocks_are_not_words():
    report = analyze_text("Text here.\n\n```\nlots of code words in a fence\n```\n")

    assert report.words == 2


def test_inline_code_spans_are_counted():
    report = analyze_text("Call `foo()` then `bar baz` and stop.\n")

    paragraph = report.paragraphs[0]
    assert paragraph.code_spans == 2
    assert paragraph.code_words == 3
    assert paragraph.words == 7


def test_soft_line_breaks_join_words():
    report = analyze_text("one\ntwo\nthree\n")

    assert report.paragraphs[0].words == 3
