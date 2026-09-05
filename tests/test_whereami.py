"""Tests for the banner.

The banner runs before anything else in every lesson, on runtimes nobody writing this has seen, so
the property that matters more than any particular line is that it does not raise. A lesson whose
first cell throws is a lesson the reader closes.
"""

from __future__ import annotations

import kxray
from kxray import whereami


def test_the_banner_says_which_kernel_this_project_is_about():
    assert "Linux 7.2.2" in whereami.text()


def test_the_banner_says_what_tier_zero_is():
    # The sentence a reader forgets first, and the one that invalidates the most conclusions.
    assert "uniprocessor, 32 bit x86, emulated timing" in whereami.text()


def test_the_banner_says_which_backend_is_behind_the_session():
    assert "backend" in whereami.text()


def test_the_banner_says_what_this_runtime_is():
    assert "tracefs" in whereami.text()


def test_the_banner_ends_with_where_the_numbers_come_from():
    assert whereami.text().splitlines()[-1].startswith("so:")


def test_the_verdict_is_one_line():
    assert "\n" not in whereami.verdict()


def test_the_verdict_on_a_machine_that_cannot_trace_says_the_captures_are_borrowed(monkeypatch):
    monkeypatch.setattr(whereami.tracefs, "available", lambda: False)
    monkeypatch.setattr(whereami.tracefs, "find", lambda: None)
    assert "somebody else took" in whereami.verdict()


def test_the_verdict_on_a_machine_that_can_trace_says_the_numbers_are_yours(monkeypatch):
    monkeypatch.setattr(whereami.tracefs, "available", lambda: True)
    assert "the numbers will be yours" in whereami.verdict()


def test_a_readable_tracefs_that_is_not_writable_says_so(monkeypatch):
    monkeypatch.setattr(whereami.tracefs, "available", lambda: False)
    monkeypatch.setattr(whereami.tracefs, "find", lambda: object())
    assert "until you are root" in whereami.verdict()


def test_no_pin_file_is_said_out_loud_rather_than_guessed(tmp_path):
    # A reader who pip installed the package has no checkout, and printing a version this cannot
    # stand behind would be worse than admitting it cannot see one.
    assert "no pin file here" in whereami.text(root=tmp_path)


def test_a_session_that_will_not_start_does_not_take_the_banner_with_it(monkeypatch):
    import kxbox

    monkeypatch.setattr(kxbox, "boot", _raises)
    printed = whereami.text()
    assert "could not start a session" in printed
    assert "tier 1:" in printed


def _raises(*args, **kwargs):
    raise RuntimeError("no emulator, no corpus, nothing")


def test_the_banner_prints_and_hands_the_same_text_back(capsys):
    returned = whereami.banner()
    assert capsys.readouterr().out.strip() == returned.strip()


def test_kxray_banner_is_the_name_a_lesson_calls():
    assert callable(kxray.banner)


def test_calling_it_twice_works(capsys):
    """The submodule is called `whereami` for this reason, and this is the test that says why.

    A submodule named `banner` would be bound onto the package the first time anything imported
    it, taking the name away from the function, and the second call in a session would fail with a
    module not being callable.
    """
    kxray.banner()
    kxray.banner()
    assert capsys.readouterr().out.count("kxray:") == 2
