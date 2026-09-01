"""Tests for the house style checker.

The important ones are the negative tests. A linter that fires on kernel symbol names and
file paths gets switched off within a week, and then it may as well not exist.
"""

from tools.lintprose import check_text


def rules_fired(text: str, path: str = "doc.md") -> set[str]:
    return {f.rule for f in check_text(text, path)}


def test_dismissive_words_are_caught():
    assert "dismissive" in rules_fired("You simply call the function.")
    assert "dismissive" in rules_fired("This is obviously the wrong lock.")
    assert "dismissive" in rules_fired("Of course the page is already mapped.")


def test_dismissive_ignores_inline_code_and_paths():
    # ext4_writepages has no dismissive word in it, and neither does a path.
    assert "dismissive" not in rules_fired("See `just_in_time_alloc()` for the fast path.")
    assert "dismissive" not in rules_fired("Read [the docs](https://example.com/just/easy).")


def test_filler_is_caught():
    assert "filler" in rules_fired("It is important to note that the lock is held.")
    assert "filler" in rules_fired("We leverage the page cache here.")


def test_dashes_are_caught():
    assert "dash" in rules_fired("The kernel copies your buffer — every time.")
    assert "dash" in rules_fired("Pages 4–8 are dirty.")


def test_dashes_ignore_code_blocks():
    text = "```\nsome — output from a tool\n```\n"
    assert "dash" not in rules_fired(text)


def test_mid_sentence_break_is_caught():
    text = "The kernel copies your buffer into its own memory before it\ntouches the page cache.\n"
    assert "mid-sentence-break" in rules_fired(text)


def test_one_sentence_per_line_is_fine():
    text = "The kernel copies your buffer first.\nThen it touches the page cache.\n"
    assert "mid-sentence-break" not in rules_fired(text)


def test_mid_sentence_break_ignores_lists_and_tables():
    assert "mid-sentence-break" not in rules_fired("- a list item with no full stop\n- another\n")
    assert "mid-sentence-break" not in rules_fired("| a | b |\n| - | - |\n| c | d |\n")
    assert "mid-sentence-break" not in rules_fired("# A heading\nSome prose here.\n")


def test_page_break_is_caught():
    assert "page-break" in rules_fired("Some prose.\n\n---\n\nMore prose.\n")


def test_front_matter_is_not_a_page_break():
    text = "---\ntitle: Z02\n---\n\nSome prose.\n"
    assert "page-break" not in rules_fired(text)


def test_word_cap_applies_to_lessons_only():
    hook = "<!-- block: hook -->\n" + ("word " * 200) + "\n"
    assert "word-cap" in rules_fired(hook, "lessons/Z02/lesson.md")
    assert "word-cap" not in rules_fired(hook, "blueprints/page-fault.md")


def test_hook_under_the_cap_passes():
    hook = "<!-- block: hook -->\n" + ("word " * 100) + "\n"
    assert "word-cap" not in rules_fired(hook, "lessons/Z02/lesson.md")


def test_clean_document_has_no_findings():
    text = (
        "---\ntitle: Z02\n---\n\n"
        "# Your first trace\n\n"
        "The kernel exports a live view of what it is doing right now.\n"
        "You turn it on by writing one word to a file.\n\n"
        "```sh\necho function_graph > current_tracer\n```\n\n"
        "| tracer | what it shows |\n| --- | --- |\n| function_graph | every call and return |\n"
    )
    assert check_text(text, "lessons/Z02/lesson.md") == []
