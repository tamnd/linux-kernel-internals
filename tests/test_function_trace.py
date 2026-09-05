"""Tests for the flat function tracer parser.

Same two kinds as the function_graph tests. The corpus tests read the committed captures and
compare them against the numbers written in their `.meta.toml`, so a change to the parser or a
bump of the pinned kernel cannot quietly alter what a lesson shows. The rest are small strings
that pin one behaviour each.

The flags column gets more attention here than anything else, because it is the part of this
format that function_graph does not have and it is the part every concurrency lesson leans on.
"""

import tomllib
from pathlib import Path

import pytest

from kxray.models import Flags
from kxray.trace import common, function

TRACES = Path(__file__).resolve().parents[1] / "corpora" / "traces"
CAPTURES = sorted(TRACES.glob("*/flat-*.txt"))

BANNER = "# tracer: function\n#\n# entries-in-buffer/entries-written: 2/2   #P:1\n#\n"


def trace(*rows: str) -> str:
    return BANNER + "\n".join(rows) + "\n"


def line(flags: str = ".....", body: str = "vfs_write <-ksys_write", task: str = "sh-42") -> str:
    return f"   {task}      [000] {flags}     7.153411: {body}"


# -- the committed captures --


def test_the_corpus_is_not_empty():
    assert CAPTURES, f"no flat captures found under {TRACES}"


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_a_capture_matches_its_metadata(capture):
    meta = tomllib.loads(capture.with_suffix(".meta.toml").read_text())
    log = function.parse_file(capture)

    assert len(log.unparsed) == meta["unparsed_lines"], [(u.line, u.reason) for u in log.unparsed]
    assert log.tracer == meta["tracer"]
    assert len(log.calls) == meta["calls"]
    assert log.cpus == meta["cpus"]
    assert log.contexts() == meta["contexts"]


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_every_line_of_a_capture_is_accounted_for(capture):
    log = function.parse_file(capture)
    assert log.lines.total == len(capture.read_text().splitlines())


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_no_capture_dropped_events(capture):
    # A trace with holes in it looks complete, which is why this is checked rather than assumed.
    log = function.parse_file(capture)
    assert log.lost == 0, f"{capture} lost {log.lost} events"


def test_the_write_capture_is_all_process_context():
    log = function.parse_file(TRACES / "tier0" / "flat-write.txt")
    assert {one.context for one in log.calls} == {"process"}
    assert not any(one.flags.interrupts_are_off for one in log.calls)


def test_the_write_capture_ends_with_the_tracer_turning_itself_off():
    # The last line is a second `vfs_write` and it is not the byte being written twice. It is the
    # write to `tracing_on` that stopped the recording, which is itself a write.
    log = function.parse_file(TRACES / "tier0" / "flat-write.txt")
    assert len(log.find("vfs_write")) == 2
    assert log.calls[-1].name == "vfs_write"
    assert log.calls[-1].caller == "ksys_write"


def test_the_interrupt_capture_crosses_from_hardirq_into_softirq():
    log = function.parse_file(TRACES / "tier0" / "flat-interrupt.txt")
    order = [one.context for one in log.calls]
    assert order[0] == "hardirq"
    assert order[-1] == "softirq"
    # And the transition happens once rather than flapping.
    assert order.count("softirq") == 1


def test_the_interrupt_capture_shows_the_request_before_the_service():
    # `raise_softirq` is the ask and `handle_softirqs` is the work, and the gap between them is
    # what deferred work means.
    log = function.parse_file(TRACES / "tier0" / "flat-interrupt.txt")
    asked = log.find("raise_softirq")[0]
    served = log.find("handle_softirqs")[0]
    assert asked.line < served.line
    assert asked.context == "hardirq"
    assert served.context == "nopreempt"


def test_the_task_name_in_the_interrupt_capture_is_who_was_interrupted():
    # Every line says `sleep` and `sleep` did none of it. An interrupt borrows whatever task was
    # on the CPU, so the comm column answers who was interrupted rather than who ran.
    log = function.parse_file(TRACES / "tier0" / "flat-interrupt.txt")
    assert log.tasks == ["sleep-37"]
    assert log.contexts()["hardirq"] == 4


# -- the flags column --


def test_all_dots_is_ordinary_process_context():
    flags = common.parse_flags(".....")
    assert flags.context == "process"
    assert not flags.interrupts_are_off
    assert not flags.wants_resched
    assert flags.preempt_depth == 0


def test_a_four_character_column_still_reads():
    # Kernels from before migrate-disable print four characters. A trace somebody took in 2021 is
    # still a trace.
    flags = common.parse_flags("d.h1")
    assert flags.migrate_disable is None
    assert flags.context == "hardirq"
    assert flags.preempt_depth == 1


def test_a_five_character_column_keeps_the_last_one():
    assert common.parse_flags("d.h1.").migrate_disable == "."
    assert common.parse_flags("d.h1m").migrate_disable == "m"


def test_a_dot_in_the_count_means_zero_rather_than_unknown():
    assert common.parse_flags(".....").preempt_depth == 0


def test_hardirq_wins_over_the_preemption_count():
    flags = common.parse_flags("d.h2.")
    assert flags.preempt_depth == 2
    assert flags.context == "hardirq"


def test_softirq_is_its_own_context():
    assert common.parse_flags(".Ns1.").context == "softirq"


def test_an_nmi_is_read_from_either_letter():
    assert common.parse_flags("..z1.").context == "nmi"
    assert common.parse_flags("..Z1.").context == "nmi"


def test_a_capital_h_is_a_hardirq_inside_a_softirq():
    # `H` means a hardware interrupt arrived while a softirq was running. It is still hardirq
    # context, because that is the one with the stricter rules.
    assert common.parse_flags("d.H2.").context == "hardirq"


def test_a_raised_count_with_no_interrupt_flag_is_nopreempt():
    assert common.parse_flags("...1.").context == "nopreempt"
    assert common.parse_flags("d..2.").context == "nopreempt"


def test_the_column_never_answers_atomic():
    # A held spinlock and a bare preempt_disable() both raise the count, and the column carries
    # only the count. Answering `atomic` here would be a guess dressed up as a reading.
    every = {common.parse_flags(f"...{n}.").context for n in range(1, 10)}
    assert every == {"nopreempt"}


def test_interrupts_off_is_read_from_either_letter():
    assert common.parse_flags("d....").interrupts_are_off
    assert common.parse_flags("D....").interrupts_are_off
    assert not common.parse_flags(".....").interrupts_are_off


def test_a_pending_reschedule_is_anything_but_a_dot():
    assert common.parse_flags(".N...").wants_resched
    assert common.parse_flags(".p...").wants_resched
    assert not common.parse_flags(".....").wants_resched


def test_describe_says_the_whole_state_in_one_line():
    said = common.parse_flags("dN.2.").describe()
    assert said == "nopreempt context, interrupts off, reschedule pending, preemption count 2"


def test_describe_on_an_ordinary_line_says_only_the_context():
    assert common.parse_flags(".....").describe() == "process context"


def test_flags_print_as_the_column_they_came_from():
    assert str(common.parse_flags("d.h2.")) == "d.h2."


# -- reading a line --


def test_a_call_with_a_caller():
    log = function.parse(trace(line()))
    assert len(log.calls) == 1
    call = log.calls[0]
    assert call.name == "vfs_write"
    assert call.caller == "ksys_write"
    assert call.task == "sh"
    assert call.pid == 42
    assert call.cpu == 0
    assert call.timestamp == 7.153411


def test_a_call_with_no_caller():
    # `func_stack_trace` off and `print-parent` off gives a bare function name, which is legal.
    log = function.parse(trace(line(body="vfs_write")))
    assert log.calls[0].caller is None


def test_a_comm_containing_a_dash_and_a_slash():
    # `kworker/0:1-9` is one task called `kworker/0:1` with pid 9. The pid is the anchor.
    log = function.parse(trace(line(task="kworker/0:1-9")))
    assert log.calls[0].task == "kworker/0:1"
    assert log.calls[0].pid == 9


def test_a_comm_containing_a_space():
    log = function.parse(trace(line(task="my prog-7")))
    assert log.calls[0].task == "my prog"
    assert log.calls[0].pid == 7


def test_a_two_digit_cpu():
    log = function.parse(trace("   sh-42      [013] .....     7.153411: vfs_write <-ksys_write"))
    assert log.calls[0].cpu == 13


def test_a_line_prints_as_something_a_person_can_read():
    log = function.parse(trace(line()))
    assert str(log.calls[0]) == "7.153411 [0] sh-42 vfs_write <- ksys_write"


def test_the_line_number_is_kept():
    log = function.parse(trace(line(), line(body="ksys_write")))
    assert [one.line for one in log.calls] == [5, 6]


# -- the banner --


def test_the_tracer_name_is_read():
    assert function.parse(trace(line())).tracer == "function"


def test_the_buffer_counts_are_read():
    log = function.parse(trace(line()))
    assert log.in_buffer == 2
    assert log.written == 2
    assert log.lost == 0
    assert not log.overran


def test_a_trace_that_dropped_events_says_so():
    text = (
        "# tracer: function\n# entries-in-buffer/entries-written: 40/2119   #P:4\n" + line() + "\n"
    )
    log = function.parse(text)
    assert log.lost == 2079
    assert log.overran
    assert "2079 event(s) dropped" in log.table()


def test_a_banner_with_no_counts_leaves_lost_unknown():
    log = function.parse("# tracer: function\n" + line() + "\n")
    assert log.lost is None
    assert not log.overran


def test_the_processor_count_is_read():
    assert function.parse(trace(line())).cpu_count == 1


# -- tolerance, and what stops it turning into silence --


def test_a_line_with_no_header_is_unparsed_and_the_parse_carries_on():
    log = function.parse(trace("what is this", line()))
    assert len(log.calls) == 1
    assert len(log.unparsed) == 1
    assert log.unparsed[0].line == 5
    assert "no task, cpu, flags and timestamp header" in log.unparsed[0].reason


def test_a_header_with_a_body_nobody_understands_is_unparsed():
    # An event line has a header and then `name: field=value`, which is not a function call. It
    # belongs to the event reader rather than this one, and being told so beats being ignored.
    log = function.parse(trace(line(body="sched_switch: prev_comm=cat prev_pid=41")))
    assert not log.calls
    assert "unrecognised body" in log.unparsed[0].reason


def test_blank_lines_and_comments_are_skipped_rather_than_unparsed():
    log = function.parse(trace("", "#", line()))
    assert not log.unparsed
    assert log.lines.read == 1


def test_every_line_lands_in_exactly_one_bucket():
    text = trace("", "nonsense", line())
    log = function.parse(text)
    assert log.lines.total == len(text.splitlines())
    assert (log.lines.read, log.lines.unparsed) == (1, 1)


# -- what the log can answer --


def test_counts_are_ordered_by_how_often_each_ran():
    log = function.parse(
        trace(
            line(body="b <-a"),
            line(body="c <-a"),
            line(body="b <-a"),
            line(body="b <-a"),
        )
    )
    assert list(log.counts()) == ["b", "c"]
    assert log.counts() == {"b": 3, "c": 1}


def test_callers_and_callees_are_two_different_questions():
    log = function.parse(trace(line(body="b <-a"), line(body="b <-x"), line(body="c <-b")))
    assert log.callers("b") == {"a": 1, "x": 1}
    assert log.callees("b") == {"c": 1}


def test_callees_only_sees_what_the_filter_let_through():
    # `set_ftrace_filter` is why. A function whose callees were filtered out looks like a leaf,
    # and that is a property of the capture rather than of the kernel.
    log = function.parse(trace(line(body="b <-a")))
    assert log.callees("b") == {}


def test_find_returns_every_time_a_function_ran():
    log = function.parse(trace(line(), line(body="ksys_write"), line()))
    assert len(log.find("vfs_write")) == 2


def test_tasks_are_named_with_their_pid():
    log = function.parse(trace(line(task="sh-42"), line(task="sh-43"), line(task="sh-42")))
    assert log.tasks == ["sh-42", "sh-43"]


def test_cpus_are_listed_in_order():
    log = function.parse(
        trace(
            "   sh-42      [002] .....     7.1: a",
            "   sh-42      [000] .....     7.2: b",
        )
    )
    assert log.cpus == [0, 2]


def test_the_table_has_a_context_column():
    log = function.parse(trace(line(flags="d.h1.")))
    printed = log.table()
    assert "context" in printed.splitlines()[0]
    assert "hardirq" in printed


def test_parse_file_records_where_it_came_from(tmp_path):
    path = tmp_path / "one.txt"
    path.write_text(trace(line()))
    assert function.parse_file(path).source == str(path)


def test_an_empty_log_answers_everything_without_raising():
    log = function.parse("")
    assert log.calls == []
    assert log.contexts() == {}
    assert log.cpus == []
    assert log.lost is None


# -- the shared header --


def test_the_header_reader_hands_back_the_rest_of_the_line():
    head = common.header(line(body="sched_switch: prev_comm=cat"))
    assert head is not None
    assert head.rest == "sched_switch: prev_comm=cat"


def test_the_header_reader_says_no_rather_than_guessing():
    assert common.header("# tracer: function") is None
    assert common.header("") is None


def test_the_header_reader_gives_back_read_flags():
    head = common.header(line(flags="d.h2."))
    assert head is not None
    assert isinstance(head.flags, Flags)
    assert head.flags.context == "hardirq"
