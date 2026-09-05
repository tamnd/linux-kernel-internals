"""Tests for the event format reader and the event line reader.

The corpus tests read the committed formats and the committed capture and compare them against
the numbers in their metadata. The rest are small strings, and most of them are about the two
ways a printed line and a declared format can disagree, because that is the part a reader gets
nothing from unless somebody made it say so out loud.
"""

import tomllib
from pathlib import Path

import pytest

from kxray.trace import events, formats

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "corpora" / "events" / "tier0"
CAPTURE = ROOT / "corpora" / "traces" / "tier0" / "events-exec.txt"
FORMATS = sorted(EVENTS.glob("*.format"))

HEADER = "# tracer: nop\n#\n# entries-in-buffer/entries-written: 2/2   #P:1\n#\n"


def trace(*rows: str) -> str:
    return HEADER + "\n".join(rows) + "\n"


def line(body: str, flags: str = ".....", task: str = "sh-42") -> str:
    return f"   {task}      [000] {flags}     3.040809: {body}"


def written(*fields: str, name: str = "demo", identity: int = 1, fmt: str = "") -> str:
    common = [
        "\tfield:unsigned short common_type;\toffset:0;\tsize:2;\tsigned:0;",
        "\tfield:unsigned char common_flags;\toffset:2;\tsize:1;\tsigned:0;",
        "\tfield:unsigned char common_preempt_count;\toffset:3;\tsize:1;\tsigned:0;",
        "\tfield:int common_pid;\toffset:4;\tsize:4;\tsigned:1;",
    ]
    body = [f"name: {name}", f"ID: {identity}", "format:", *common, "", *fields, ""]
    if fmt:
        body.append(f"print fmt: {fmt}")
    return "\n".join(body) + "\n"


def field(decl: str, offset: int, size: int, signed: int = 1) -> str:
    return f"\tfield:{decl};\toffset:{offset};\tsize:{size};\tsigned:{signed};"


@pytest.fixture(scope="module")
def layouts():
    return formats.load(EVENTS)


# -- the committed formats --


def test_the_format_corpus_is_not_empty():
    assert FORMATS, f"no format files found under {EVENTS}"


@pytest.mark.parametrize("path", FORMATS, ids=lambda p: p.stem)
def test_a_format_matches_its_metadata(path):
    meta = tomllib.loads(path.with_suffix(".meta.toml").read_text())
    layout = formats.parse_file(path)

    assert layout.name == meta["event"]
    assert layout.id == meta["event_id"]
    assert len(layout.fields) == meta["fields"]
    assert len(layout.own) == meta["own_fields"]
    assert layout.size == meta["record_size"]


@pytest.mark.parametrize("path", FORMATS, ids=lambda p: p.stem)
def test_every_line_of_a_format_is_accounted_for(path):
    counted = formats.account(path.read_text())
    assert counted.unparsed == 0
    assert counted.total == len(path.read_text().splitlines())


@pytest.mark.parametrize("path", FORMATS, ids=lambda p: p.stem)
def test_every_format_starts_with_the_same_four_common_fields(path):
    layout = formats.parse_file(path)
    assert [one.name for one in layout.common] == [
        "common_type",
        "common_flags",
        "common_preempt_count",
        "common_pid",
    ]
    # And they always come first, which is what lets an event be identified before it is read.
    assert layout.fields[:4] == layout.common


def test_prev_state_is_four_bytes_on_this_kernel_and_that_is_the_point():
    # `long` is four bytes on 32 bit x86 and eight on x86-64, and every field after it moves. A
    # parser holding these offsets as constants reads the wrong bytes on the other machine and
    # reports nothing wrong, which is the whole argument for reading the format file.
    layout = formats.parse_file(EVENTS / "sched_switch.format")
    state = layout.field("prev_state")
    assert state is not None
    assert (state.type, state.size, state.offset) == ("long", 4, 32)
    assert layout.field("next_comm").offset == state.end


def test_a_comm_is_a_fixed_sixteen_byte_array_and_reads_as_text():
    one = formats.parse_file(EVENTS / "sched_switch.format").field("prev_comm")
    assert one.count == 16
    assert one.size == 16
    assert one.is_array
    assert one.is_text


def test_a_data_loc_field_is_four_bytes_holding_a_reference():
    # `filename` prints as `/bin/true` and takes four bytes in the record, because those four are
    # an offset and a length and the string lives further along.
    one = formats.parse_file(EVENTS / "sched_process_exec.format").field("filename")
    assert one.data_loc
    assert one.size == 4
    assert one.count is None
    assert one.is_text
    assert one.declared == "__data_loc char[] filename"


def test_an_array_that_is_not_a_string_is_one_field():
    one = formats.parse_file(EVENTS / "sys_enter.format").field("args")
    assert (one.count, one.size) == (6, 24)
    assert one.is_array
    assert not one.is_text


def test_no_committed_format_has_padding_in_it():
    # True on this kernel and not true in general, which is why `holes()` exists rather than an
    # assumption that offsets follow on from sizes.
    for path in FORMATS:
        assert formats.parse_file(path).holes() == [], path.name


# -- reading a format file --


def test_the_header_is_required_rather_than_guessed():
    with pytest.raises(formats.FormatError):
        formats.parse("field:int a;\toffset:8;\tsize:4;\tsigned:1;\n")


def test_a_format_with_no_fields_is_refused():
    with pytest.raises(formats.FormatError):
        formats.parse("name: demo\nID: 1\nformat:\n")


def test_a_pointer_written_with_no_space_keeps_its_star_on_the_type():
    layout = formats.parse("name: demo\nID: 1\nformat:\n" + field("const void *ptr", 8, 4, 0))
    one = layout.field("ptr")
    assert one is not None
    assert one.type == "const void *"


def test_a_pointer_written_with_a_space_reads_the_same_way():
    layout = formats.parse("name: demo\nID: 1\nformat:\n" + field("const void * ptr", 8, 4, 0))
    assert layout.field("ptr").type == "const void *"


def test_an_unsigned_field_is_not_signed():
    layout = formats.parse("name: demo\nID: 1\nformat:\n" + field("unsigned long x", 8, 4, 0))
    assert not layout.field("x").signed
    layout = formats.parse("name: demo\nID: 1\nformat:\n" + field("long x", 8, 4, 1))
    assert layout.field("x").signed


def test_padding_between_fields_is_reported():
    text = written(field("char a", 8, 1, 0), field("int b", 12, 4))
    assert formats.parse(text).holes() == [("a", 3)]


def test_the_record_size_is_the_end_of_the_last_field():
    assert formats.parse(written(field("int b", 12, 4))).size == 16


def test_print_fmt_is_kept_as_text_and_not_evaluated():
    layout = formats.parse_file(EVENTS / "sched_wakeup.format")
    assert layout.print_fmt.startswith('"comm=%s pid=%d prio=%d target_cpu=%03d"')


def test_load_keys_on_the_event_name_rather_than_the_file_name(tmp_path):
    (tmp_path / "whatever.format").write_text(written(field("int a", 8, 4), name="sched_thing"))
    assert list(formats.load(tmp_path)) == ["sched_thing"]


def test_a_format_prints_as_a_table_a_person_can_read():
    printed = formats.parse_file(EVENTS / "sched_wakeup.format").table()
    assert printed.splitlines()[0].split() == ["offset", "size", "field", "type"]
    assert "char comm[16]" in printed


def test_a_field_says_where_it_is_when_printed():
    one = formats.parse_file(EVENTS / "sched_wakeup.format").field("target_cpu")
    assert str(one) == "int target_cpu at 32, 4 byte(s)"


# -- the committed capture --


def test_the_capture_matches_its_metadata(layouts):
    meta = tomllib.loads(CAPTURE.with_suffix(".meta.toml").read_text())
    log = events.parse_file(CAPTURE, layouts)

    assert len(log.unparsed) == meta["unparsed_lines"], [(u.line, u.reason) for u in log.unparsed]
    assert len(log.events) == meta["events_read"]
    assert log.names() == meta["event_counts"]
    assert log.cpus == meta["cpus"]
    assert log.lines.total == len(CAPTURE.read_text().splitlines())


def test_the_capture_says_nop_because_events_are_not_a_tracer(layouts):
    # Events record whether or not a tracer is running, so `current_tracer` stays `nop` and the
    # banner says so. Somebody expecting a tracer name here would think the capture went wrong.
    assert events.parse_file(CAPTURE, layouts).tracer == "nop"


def test_every_event_in_the_capture_binds_to_a_format(layouts):
    log = events.parse_file(CAPTURE, layouts)
    assert log.unbound() == []
    assert all(one.bound for one in log.events)


def test_no_line_in_the_capture_disagrees_with_its_format(layouts):
    log = events.parse_file(CAPTURE, layouts)
    assert log.disagreements() == []


def test_prev_state_is_the_only_field_that_arrives_as_a_symbol(layouts):
    meta = tomllib.loads(CAPTURE.with_suffix(".meta.toml").read_text())
    log = events.parse_file(CAPTURE, layouts)
    assert sorted({one for e in log.events for one in e.symbolic}) == meta["symbolic_fields"]


def test_pids_in_the_capture_are_integers_and_comms_are_strings(layouts):
    switch = events.parse_file(CAPTURE, layouts).find("sched_switch")[0]
    assert switch["prev_pid"] == 1
    assert switch["next_pid"] == 37
    assert switch["prev_comm"] == "sh"
    assert isinstance(switch["prev_prio"], int)


def test_the_header_and_the_payload_disagree_about_one_task_on_purpose(layouts):
    # The line at 3.049350 is headed `sleep-38` and its payload says `prev_comm=sh prev_pid=38`.
    # Both are right. The payload holds a copy of the comm made when the event fired, before the
    # exec, and the header is looked up from the pid when the buffer is printed, by which time
    # the map says `sleep`. This is the reason to read a payload rather than trust a header.
    log = events.parse_file(CAPTURE, layouts)
    one = next(e for e in log.find("sched_switch") if abs(e.timestamp - 3.049350) < 1e-6)
    assert one.task == "sleep"
    assert one.pid == 38
    assert one["prev_comm"] == "sh"
    assert one["prev_pid"] == 38


def test_target_cpu_prints_padded_and_reads_back_as_a_number(layouts):
    # `%03d` in the print fmt, so the line says `target_cpu=000`. Comparing the text rather than
    # the value is the mistake this guards against.
    wakeup = events.parse_file(CAPTURE, layouts).find("sched_wakeup")[0]
    assert wakeup["target_cpu"] == 0


def test_the_capture_carries_contexts_like_any_other_trace(layouts):
    log = events.parse_file(CAPTURE, layouts)
    assert log.contexts() == {"nopreempt": 10, "process": 2, "softirq": 1}


def test_the_exec_events_report_the_filename(layouts):
    log = events.parse_file(CAPTURE, layouts)
    assert [one["filename"] for one in log.find("sched_process_exec")] == [
        "/bin/true",
        "/bin/sleep",
    ]


# -- binding a line to a format --


def test_a_value_the_format_calls_a_number_comes_back_as_one(layouts):
    log = events.parse(trace(line("sched_wakeup: comm=sh pid=7 prio=120 target_cpu=001")), layouts)
    assert log.events[0]["pid"] == 7
    assert log.events[0]["target_cpu"] == 1


def test_a_hexadecimal_value_is_read_as_a_number():
    text = written(field("unsigned long addr", 8, 4, 0))
    layouts = {"demo": formats.parse(text)}
    log = events.parse(trace(line("demo: addr=0x1f")), layouts)
    assert log.events[0]["addr"] == 31


def test_a_number_that_printed_as_a_symbol_is_recorded_rather_than_forced(layouts):
    body = "sched_switch: prev_comm=sh prev_pid=1 prev_prio=120 prev_state=S ==> "
    body += "next_comm=sh next_pid=2 next_prio=120"
    one = events.parse(trace(line(body)), layouts).events[0]
    assert one["prev_state"] == "S"
    assert one.symbolic == ("prev_state",)
    assert one.agrees


def test_the_arrow_in_a_switch_line_is_not_part_of_the_state(layouts):
    body = "sched_switch: prev_comm=sh prev_pid=1 prev_prio=120 prev_state=R+ ==> "
    body += "next_comm=cat next_pid=2 next_prio=120"
    one = events.parse(trace(line(body)), layouts).events[0]
    assert one["prev_state"] == "R+"
    assert one["next_comm"] == "cat"


def test_a_key_the_format_does_not_declare_is_named(layouts):
    body = "sched_wakeup: comm=sh pid=7 prio=120 target_cpu=000 nonsense=4"
    one = events.parse(trace(line(body)), layouts).events[0]
    assert one.unknown == ("nonsense",)
    assert not one.agrees
    # And it is still handed back, as text, because throwing it away helps nobody.
    assert one["nonsense"] == "4"


def test_a_field_the_line_did_not_print_is_named(layouts):
    one = events.parse(trace(line("sched_wakeup: comm=sh pid=7")), layouts).events[0]
    assert one.missing == ("prio", "target_cpu")
    assert not one.agrees


def test_a_common_field_the_line_did_not_print_is_not_counted_missing(layouts):
    # No print fmt prints the four common fields, so counting them missing would make every line
    # in every trace disagree with its format and the signal would be worth nothing.
    one = events.parse(trace(line("sched_wakeup: comm=sh pid=7 prio=1 target_cpu=0")), layouts)
    assert one.events[0].missing == ()
    assert one.events[0].agrees


def test_an_event_with_no_format_keeps_its_values_as_text():
    log = events.parse(trace(line("mystery: a=1 b=two")))
    one = log.events[0]
    assert not one.bound
    assert one.values == {"a": "1", "b": "two"}
    assert log.unbound() == ["mystery"]


def test_an_unbound_event_claims_nothing_about_agreement():
    one = events.parse(trace(line("mystery: a=1"))).events[0]
    assert one.unknown == ()
    assert one.missing == ()
    assert one.symbolic == ()


# -- pulling the pairs apart --


def test_a_value_containing_a_space_survives():
    # A comm can contain a space and ftrace does not quote it, so splitting on whitespace would
    # lose half the name and leave the rest looking like a key.
    assert events.pairs("prev_comm=my prog prev_pid=7") == {"prev_comm": "my prog", "prev_pid": "7"}


def test_a_value_containing_a_slash_survives():
    assert events.pairs("filename=/bin/true pid=37")["filename"] == "/bin/true"


def test_a_trailing_literal_is_dropped_and_a_joined_one_is_not():
    assert events.pairs("state=S ==> next=cat")["state"] == "S"
    assert events.pairs("state=R+ next=cat")["state"] == "R+"


def test_an_empty_value_is_allowed():
    assert events.pairs("comm= pid=7") == {"comm": "", "pid": "7"}


def test_a_body_with_no_pairs_gives_nothing_back():
    assert events.pairs("some free text") == {}


# -- tolerance, and the banner --


def test_a_line_with_no_header_is_unparsed_and_the_parse_carries_on():
    log = events.parse(trace("what is this", line("mystery: a=1")))
    assert len(log.events) == 1
    assert len(log.unparsed) == 1
    assert "no task, cpu, flags and timestamp header" in log.unparsed[0].reason


def test_a_function_tracer_line_is_unparsed_here_and_says_why():
    # `vfs_write <-ksys_write` has a header and no event name, so it belongs to the other reader.
    log = events.parse(trace(line("vfs_write <-ksys_write")))
    assert not log.events
    assert "no `event: ...` after the header" in log.unparsed[0].reason


def test_every_line_lands_in_exactly_one_bucket():
    text = trace("", "nonsense", line("mystery: a=1"))
    log = events.parse(text)
    assert log.lines.total == len(text.splitlines())
    assert (log.lines.read, log.lines.unparsed) == (1, 1)


def test_the_buffer_counts_are_read_the_same_way_as_the_other_tracers():
    log = events.parse(trace(line("mystery: a=1")))
    assert (log.in_buffer, log.written, log.lost) == (2, 2, 0)
    assert log.cpu_count == 1


def test_a_trace_that_dropped_events_says_so_in_the_table():
    text = "# entries-in-buffer/entries-written: 1/9\n" + line("mystery: a=1") + "\n"
    log = events.parse(text)
    assert log.lost == 8
    assert "8 event(s) dropped" in log.table()


def test_an_empty_log_answers_everything_without_raising():
    log = events.parse("")
    assert log.events == []
    assert log.names() == {}
    assert log.unbound() == []
    assert log.contexts() == {}


def test_parse_file_records_where_it_came_from(tmp_path):
    path = tmp_path / "one.txt"
    path.write_text(trace(line("mystery: a=1")))
    assert events.parse_file(path).source == str(path)


def test_an_event_prints_as_something_a_person_can_read():
    one = events.parse(trace(line("mystery: a=1 b=two"))).events[0]
    assert str(one) == "3.040809 [0] sh-42 mystery: a=1 b=two"


def test_get_falls_back_rather_than_raising():
    one = events.parse(trace(line("mystery: a=1"))).events[0]
    assert one.get("nothing", "fallback") == "fallback"
    with pytest.raises(KeyError):
        one["nothing"]


def test_the_table_can_be_asked_for_named_columns(layouts):
    log = events.parse_file(CAPTURE, layouts)
    printed = log.table("prev_comm", "next_comm")
    assert printed.splitlines()[0].split()[-2:] == ["prev_comm", "next_comm"]
    # A row for an event with no such field is blank rather than missing.
    assert len(printed.splitlines()) == len(log.events) + 2
