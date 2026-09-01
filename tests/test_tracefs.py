"""Tests for the tracefs bridge.

None of these touch a real `/sys/kernel/tracing`. They build a directory that looks like one, in
a temporary path, which is enough to pin the thing that matters: the order of the writes, and
whether the machine gets put back the way it was found.
"""

from __future__ import annotations

import pytest

from kxray import tracefs


def fake_tracefs(tmp_path, tracers: str = "nop function function_graph"):
    """A directory with the files the tracer has, and a log of every write, in order."""
    root = tmp_path / "tracing"
    root.mkdir()
    for name in ("current_tracer", "tracing_on", "trace", "set_graph_function", "max_graph_depth"):
        (root / name).write_text("")
    (root / "available_tracers").write_text(tracers)
    (root / "current_tracer").write_text("nop\n")
    return tracefs.Tracefs(root)


def logged(found, log):
    """Wrap `write` so the test can see the sequence rather than only the end state."""
    original = found.write

    def record(name, value):
        log.append((name, value))
        original(name, value)

    object.__setattr__(found, "write", record)
    return found


def test_find_prefers_the_newer_location(tmp_path):
    old = tmp_path / "debug"
    new = tmp_path / "tracing"
    for directory in (old, new):
        directory.mkdir()
        for name in tracefs.CONTROLS:
            (directory / name).write_text("")

    assert tracefs.find((new, old)).root == new


def test_find_returns_none_when_the_controls_are_missing(tmp_path):
    (tmp_path / "tracing").mkdir()
    assert tracefs.find((tmp_path / "tracing",)) is None


def test_a_capture_turns_tracing_off_before_it_configures_anything(tmp_path):
    found = fake_tracefs(tmp_path)
    log: list[tuple[str, str]] = []
    logged(found, log)

    found.capture(lambda: None, function="vfs_write", max_depth=3)

    assert log[0] == ("tracing_on", "0")
    order = [name for name, _ in log]
    assert order.index("current_tracer") < order.index("trace")
    assert order.index("trace") < order.index("tracing_on", 1)


def test_a_capture_empties_the_buffer_so_the_trace_holds_this_run_and_nothing_else(tmp_path):
    found = fake_tracefs(tmp_path)
    log: list[tuple[str, str]] = []
    logged(found, log)

    found.capture(lambda: None)

    assert ("trace", "") in log


def test_a_capture_puts_the_previous_tracer_back(tmp_path):
    found = fake_tracefs(tmp_path)
    found.write("current_tracer", "function")

    found.capture(lambda: None)

    assert found.read("current_tracer").strip() == "function"
    assert found.read("set_graph_function") == ""
    assert found.read("max_graph_depth") == "0"


def test_a_capture_puts_it_back_even_when_the_action_raises(tmp_path):
    found = fake_tracefs(tmp_path)
    found.write("current_tracer", "function")

    def explode():
        raise RuntimeError("the thing being traced fell over")

    with pytest.raises(RuntimeError):
        found.capture(explode)

    assert found.read("current_tracer").strip() == "function"
    assert found.read("tracing_on") == "0"


def test_a_capture_hands_back_what_the_trace_file_said(tmp_path):
    found = fake_tracefs(tmp_path)

    def write_the_trace():
        (found.root / "trace").write_text(" 0)  1.000 us  |  vfs_write();\n")

    assert "vfs_write" in found.capture(write_the_trace)


def test_a_kernel_without_the_tracer_says_so_rather_than_failing_later(tmp_path):
    found = fake_tracefs(tmp_path, tracers="nop function")
    with pytest.raises(tracefs.Unavailable, match="function_graph"):
        found.capture(lambda: None)


def test_stats_reads_the_overrun_count(tmp_path):
    found = fake_tracefs(tmp_path)
    per_cpu = found.root / "per_cpu" / "cpu0"
    per_cpu.mkdir(parents=True)
    (per_cpu / "stats").write_text("entries: 412\noverrun: 39\nread events: 412\n")

    assert found.stats(0)["overrun"] == 39
    assert found.stats(0)["entries"] == 412


def test_stats_on_a_cpu_that_is_not_there_is_empty_rather_than_an_error(tmp_path):
    assert fake_tracefs(tmp_path).stats(7) == {}


def test_write_one_byte_writes_one_byte(tmp_path):
    target = tmp_path / "one"
    tracefs.write_one_byte(str(target))()
    assert target.read_bytes() == b"x"


def test_explain_names_the_thing_that_is_missing(monkeypatch):
    monkeypatch.setattr(tracefs.platform, "system", lambda: "Darwin")
    assert "Darwin" in tracefs.explain()

    monkeypatch.setattr(tracefs.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tracefs, "find", lambda: None)
    assert "mount" in tracefs.explain()


def test_capture_write_refuses_with_a_reason_when_there_is_no_tracefs(monkeypatch):
    monkeypatch.setattr(tracefs, "find", lambda: None)
    with pytest.raises(tracefs.Unavailable):
        tracefs.capture_write()
