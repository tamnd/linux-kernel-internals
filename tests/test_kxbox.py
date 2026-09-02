"""Tests for the Tier 0 session.

The property worth testing is the one the whole design rests on: a lesson cell written once runs
against the emulator and against a recording, and gets back the same types from both. A fallback
that is a second code path is a fallback nobody exercises until a reader hits it.

The live backend is driven through a stand in that implements the four calls in `PROTOCOL.md`, so
what these tests pin down is the Python half and the protocol it expects. That is worth saying out
loud, because a stand in agrees with whatever it was written to agree with. The live backend has
since been run against a real kernel under v86 and against these same recordings, by
`kxbox/bothways.py`, and that found four things no test here could have: the wrong tracefs file,
a missing trace option, a missing `owns_window`, and a restore order that left the guest wedged.
Tests below cover each of those now, but the order was the other way round and it is worth
remembering which of the two actually finds this class of mistake.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

import kxbox
from kxbox import bridge, corpus
from kxbox.__main__ import check
from kxray.models import Tape

ROOT = Path(__file__).resolve().parents[1]

TRACE = """\
# tracer: function_graph
#
# CPU  DURATION                  FUNCTION CALLS
# |     |   |                     |   |   |   |
 0)               |  vfs_write() {
 0)   1.250 us    |    generic_perform_write();
 0)   4.500 us    |  }
"""

RECIPES = """
schema = 1

[[recipes]]
name = "write-1byte"
profile = "teaching"
describes = "one byte written to a file"
command = "dd if=/dev/zero of=/tmp/one bs=1 count=1"
functions = ["vfs_write"]
trace = "traces/demo/write.txt"
stdout = "1+0 records in\\n"
status = 0

[recipes.files]
"/proc/self/status" = "proc/demo/status.txt"
"""

META = """
source = "handwritten"
evidence = {evidence}
"""


def repo(tmp_path: Path, *, recipes: str = RECIPES, evidence: str = "false") -> Path:
    """A small checkout with one recording in it."""
    traces = tmp_path / "corpora" / "traces" / "demo"
    traces.mkdir(parents=True)
    (traces / "write.txt").write_text(TRACE)
    (traces / "write.meta.toml").write_text(META.format(evidence=evidence))

    proc = tmp_path / "corpora" / "proc" / "demo"
    proc.mkdir(parents=True)
    (proc / "status.txt").write_text("Name:\tdd\n")

    (tmp_path / "corpora" / "tier0").mkdir()
    (tmp_path / "corpora" / "tier0" / "recipes.toml").write_text(recipes)
    return tmp_path


# -- the stand in for the page ----------------------------------------------------------------


@dataclass
class Reply:
    status: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeBridge:
    """The four calls in PROTOCOL.md, over a dictionary instead of an emulator."""

    def __init__(self) -> None:
        self.files = {
            "/sys/kernel/tracing/current_tracer": "nop\n",
            "/sys/kernel/tracing/trace": "",
            "/sys/kernel/tracing/set_graph_function": "",
            "/sys/kernel/tracing/max_graph_depth": "0\n",
            "/sys/kernel/tracing/trace_options": "",
            "/sys/kernel/tracing/tracing_on": "0\n",
        }
        # What the ring buffer fills up with once tracing is turned on. Keeping it here rather than
        # in `files` is what makes the buffer behave like one: it starts empty, a write to `trace`
        # empties it again, and it only has anything in it while the tracer is on.
        self.records = TRACE
        self.ran: list[str] = []
        self.wrote: list[tuple[str, str]] = []

    def sh(self, line: str) -> Reply:
        self.ran.append(line)
        return Reply(0, "1+0 records in\n", "")

    def read(self, path: str) -> str:
        return self.files[path]

    def write(self, path: str, text: str) -> None:
        # The one rule here that is not bookkeeping. The funcgraph options only exist while
        # `function_graph` is the selected tracer, and the real kernel answers `Invalid argument`
        # to anything else. That is not a detail worth modelling for its own sake. It is modelled
        # because putting the tracer back to `nop` and only then turning the option off is the
        # obvious order to write, it is the order this used to have, and the failure it causes does
        # not look like a wrong order. It looks like the guest hanging several commands later.
        if "funcgraph" in text and self.files["/sys/kernel/tracing/current_tracer"].strip() != (
            "function_graph"
        ):
            raise OSError(f"write error: Invalid argument, writing {text!r} to {path}")

        self.wrote.append((path, text))
        self.files[path] = text
        if path == "/sys/kernel/tracing/tracing_on" and text.strip() == "1":
            self.files["/sys/kernel/tracing/trace"] = self.records

    def insmod(self, path: str) -> Reply:
        return Reply(0, f"loaded {path}", "")


# -- the recording backend --------------------------------------------------------------------


def test_a_recorded_trace_comes_back_as_a_tape(tmp_path):
    box = kxbox.Box(corpus.Corpus(repo(tmp_path)), "teaching", "no emulator")
    tape = box.trace("write-1byte", lambda: box.sh("anything"))
    assert isinstance(tape, Tape)
    assert tape.find("vfs_write")


def test_a_recorded_shell_line_comes_back_as_a_command(tmp_path):
    box = kxbox.Box(corpus.Corpus(repo(tmp_path)), "teaching", "no emulator")
    ran = box.sh("dd if=/dev/zero of=/tmp/one bs=1 count=1", recipe="write-1byte")
    assert ran.ok
    assert "1+0 records in" in ran.stdout


def test_a_recorded_file_read_comes_back(tmp_path):
    box = kxbox.Box(corpus.Corpus(repo(tmp_path)), "teaching", "no emulator")
    assert "Name:" in box.read("/proc/self/status", recipe="write-1byte")


def test_asking_for_something_nobody_recorded_says_what_to_record(tmp_path):
    box = kxbox.Box(corpus.Corpus(repo(tmp_path)), "teaching", "no emulator")
    with pytest.raises(corpus.NotRecorded) as raised:
        box.trace("read-1byte")
    message = str(raised.value)
    assert "read-1byte" in message
    assert "write-1byte" in message, "it should say what has been recorded"
    assert "recipes.toml" in message, "it should say where to add it"


def test_a_handwritten_recording_is_not_evidence(tmp_path):
    backend = corpus.Corpus(repo(tmp_path, evidence="false"))
    assert backend.evidence is False


def test_a_real_capture_is_evidence(tmp_path):
    backend = corpus.Corpus(repo(tmp_path, evidence="true"))
    assert backend.evidence is True


def test_a_recipe_for_another_profile_is_not_offered(tmp_path):
    backend = corpus.Corpus(repo(tmp_path), profile="lockdep")
    assert backend.recipes == {}
    with pytest.raises(corpus.NotRecorded):
        backend.recipe("write-1byte")


# -- the live backend, through the stand in -----------------------------------------------------


def test_the_live_backend_runs_the_callable():
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", lambda: box.sh("dd if=/dev/zero of=/tmp/one bs=1 count=1"))
    assert fake.ran == ["dd if=/dev/zero of=/tmp/one bs=1 count=1"]


def test_the_live_backend_puts_the_tracer_back():
    """A lesson that left function_graph on would slow every later cell down."""
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", None, functions=["vfs_write"])
    assert fake.files["/sys/kernel/tracing/current_tracer"] == "nop"
    assert fake.files["/sys/kernel/tracing/tracing_on"] == "0"
    assert fake.files["/sys/kernel/tracing/set_graph_function"] == ""
    assert fake.files["/sys/kernel/tracing/max_graph_depth"] == "0"
    assert fake.files["/sys/kernel/tracing/trace_options"] == "funcgraph-irqs"


def test_the_live_backend_puts_the_tracer_back_even_when_the_callable_throws():
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")

    def explode():
        raise RuntimeError("the lesson did something wrong")

    with pytest.raises(RuntimeError):
        box.trace("write-1byte", explode)
    assert fake.files["/sys/kernel/tracing/tracing_on"] == "0"


def test_the_live_backend_asks_for_the_tree_and_not_just_the_named_functions():
    """`set_graph_function`, not `set_ftrace_filter`, and the difference is the whole answer.

    The filter traces the functions you name and nothing else, so asking it for `vfs_write` gets a
    flat list of `vfs_write` calls with no tree under any of them. `set_graph_function` traces the
    ones you name and everything they call. `kxray.tracefs` has always used the second on a real
    machine, so for as long as this used the first the same lesson showed a tree on Tier 1 and a
    flat list on Tier 0, and every test here passed the whole time.
    """
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", None, functions=["vfs_write", "generic_perform_write"])
    assert (
        "/sys/kernel/tracing/set_graph_function",
        "vfs_write\ngeneric_perform_write",
    ) in fake.wrote
    assert "/sys/kernel/tracing/set_ftrace_filter" not in [path for path, _ in fake.wrote]


def test_the_live_backend_asks_for_the_options_every_capture_was_taken_with():
    """A live tape taken with different options is a different file, and looks like a real answer.

    `funcgraph-proc` is the column saying which task a line belongs to, which every committed
    capture has. `nofuncgraph-irqs` keeps interrupt context out, which is what stops a timer tick
    that landed inside the window from counting as the trace changing.
    """
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", None, functions=["vfs_write"])
    for option in bridge.WANTED:
        assert ("/sys/kernel/tracing/trace_options", option) in fake.wrote


def test_the_options_the_bridge_asks_for_are_the_ones_the_captures_were_taken_with():
    """Otherwise the live backend and the recordings are answering slightly different questions.

    This is the check that would have caught `nofuncgraph-irqs` being missing, and it is worth
    having because the symptom without it is a comparison that passes most of the time.
    """
    for path in sorted((ROOT / "corpora" / "traces" / "tier0").glob("*.meta.toml")):
        meta = tomllib.loads(path.read_text(encoding="utf-8"))
        assert tuple(meta["options"]) == bridge.WANTED, (
            f"{path.name} was captured with {meta['options']} and the bridge asks for "
            f"{list(bridge.WANTED)}"
        )


def test_the_live_backend_stays_out_of_the_window_when_the_command_owns_it():
    """The rootfs programs turn the tracer on and off around one system call, from the inside.

    If the bridge opened the window as well, everything the shell did on the way to starting the
    program would be in the capture, and the write the reader came for would be somewhere in the
    middle with nothing marking it.
    """
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", lambda: box.sh("/bin/writebyte --quiet"), owns_window=True)
    assert ("/sys/kernel/tracing/tracing_on", "1") not in fake.wrote
    assert fake.ran == ["/bin/writebyte --quiet"]


def test_the_live_backend_empties_the_buffer_before_it_starts_recording():
    """A second tape in one session must not carry the first one's records."""
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", None, functions=["vfs_write"])

    paths = [path for path, _ in fake.wrote]
    cleared = paths.index("/sys/kernel/tracing/trace")
    # The one that turns it on, not the one that makes sure it is off before anything is set up.
    started = fake.wrote.index(("/sys/kernel/tracing/tracing_on", "1"))
    assert cleared < started, "the buffer has to be emptied before tracing is turned on"

    # The order the other way round is the bug this guards: the tracer would be on for the length
    # of the clear, so the tape would open with a handful of records belonging to nothing the
    # reader asked about, and they look exactly like real ones.
    assert ("/sys/kernel/tracing/trace", "") in fake.wrote


def test_the_tracer_is_put_back_last_of_everything():
    """The restore order, which is a rule of the interface and not a matter of taste.

    `funcgraph-proc` is only a writable option while `function_graph` is the selected tracer. Put
    the tracer back to `nop` first and the kernel refuses the rest of the restore with `Invalid
    argument`, which leaves the guest recording everything it does into a buffer nobody drains.
    The next command that reads the buffer waits for megabytes over a serial line and times out,
    minutes later, looking like a hang with no connection to what caused it. The stand in refuses
    the same write for the same reason, so getting this wrong fails here in a tenth of a second.
    """
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", None, functions=["vfs_write"])

    paths = [path for path, _ in fake.wrote]
    assert paths[-1] == "/sys/kernel/tracing/current_tracer"
    assert fake.wrote[-1][1] == "nop"


def test_the_tracer_is_put_back_last_even_when_the_callable_throws():
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")

    def explode():
        raise RuntimeError("the lesson did something wrong")

    with pytest.raises(RuntimeError):
        box.trace("write-1byte", explode, functions=["vfs_write"])
    assert fake.wrote[-1] == ("/sys/kernel/tracing/current_tracer", "nop")


def test_two_tapes_in_a_row_do_not_run_into_each_other():
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    first = box.trace("write-1byte", None, functions=["vfs_write"])
    fake.records = ""  # nothing happened the second time
    second = box.trace("write-1byte", None, functions=["vfs_write"])
    assert first.find("vfs_write")
    assert second.events == []


def test_a_bridge_missing_a_call_is_refused_at_the_door():
    class Half:
        def sh(self, line):
            return Reply()

    with pytest.raises(bridge.Unavailable) as raised:
        bridge.V86(Half())
    assert "read" in str(raised.value)


def test_there_is_no_bridge_on_a_machine_that_is_not_a_page():
    assert bridge.find_bridge() is None
    assert "not running in a browser" in bridge.explain()


# -- the property the design rests on ------------------------------------------------------------


def test_both_backends_answer_the_same_cell_with_the_same_types(tmp_path):
    """The whole reason the fallback is honest rather than a second code path."""
    recorded = kxbox.Box(corpus.Corpus(repo(tmp_path)), "teaching", "no emulator")
    live = kxbox.Box(bridge.V86(FakeBridge()), "teaching")

    def run(box):
        return box.trace("write-1byte", lambda: box.sh("dd", recipe="write-1byte"))

    for box in (recorded, live):
        tape = run(box)
        assert isinstance(tape, Tape)
        assert tape.find("vfs_write")
        ran = box.sh("dd", recipe="write-1byte")
        assert isinstance(ran, kxbox.Command)
        assert ran.ok


# -- picking a backend ---------------------------------------------------------------------------


def test_the_fallback_is_chosen_when_the_reader_asks_for_it(tmp_path, monkeypatch):
    monkeypatch.setenv("KXBOX_DISABLE", "1")
    box = kxbox.boot(root=repo(tmp_path))
    assert not box.live
    assert "KXBOX_DISABLE is set" in box.banner()


def test_the_fallback_is_never_silent(tmp_path, monkeypatch):
    """A reader has to know a trace came out of a file before they read a line of it."""
    monkeypatch.delenv("KXBOX_DISABLE", raising=False)
    box = kxbox.boot(root=repo(tmp_path))
    banner = box.banner()
    assert "not a running kernel" in banner
    assert "nothing here is evidence" in banner


def test_a_live_banner_states_what_tier_0_is():
    box = kxbox.Box(bridge.V86(FakeBridge()), "teaching")
    banner = box.banner()
    assert "uniprocessor, 32 bit x86, emulated timing" in banner
    assert "no performance claim" in banner


def test_disable_is_off_when_it_is_set_to_zero(monkeypatch):
    monkeypatch.setenv("KXBOX_DISABLE", "0")
    assert kxbox.disabled() is False


# -- the recipe list -------------------------------------------------------------------------------


def test_a_recipe_pointing_at_a_missing_capture_is_caught(tmp_path):
    root = repo(tmp_path, recipes=RECIPES.replace("traces/demo/write.txt", "traces/demo/gone.txt"))
    assert any("is not committed" in one for one in check(root))


def test_a_recipe_listed_twice_is_caught(tmp_path):
    root = repo(tmp_path, recipes=RECIPES + RECIPES.split("schema = 1")[1])
    assert any("listed twice" in one for one in check(root))


def test_a_recipe_with_no_command_is_caught(tmp_path):
    root = repo(
        tmp_path,
        recipes=RECIPES.replace('command = "dd if=/dev/zero of=/tmp/one bs=1 count=1"', ""),
    )
    assert any("no command" in one for one in check(root))


def test_this_repository_has_a_clean_recipe_list():
    assert check(ROOT) == []


def test_every_recipe_here_is_a_real_capture():
    """This used to assert the opposite, and the day it failed was the day it had done its job.

    It was written when there was no built kernel and every recording in the repository was a file
    somebody typed out from the documented format. Its point was to make the replacement of those
    files a thing that could not be forgotten, because a handwritten fixture quietly becoming a
    fact is the one failure this project promises not to have.

    Both recipes are captures now, off the pinned 7.2.2 running under v86. The assertion is
    reversed rather than deleted, so what it guards now is that nobody goes back.
    """
    backend = corpus.Corpus(ROOT)
    assert backend.recipes, "the repository should have recordings"
    assert backend.evidence is True


def test_one_recipe_here_can_be_run_more_than_once():
    """Something has to be, or nothing can take a live tape after the comparison has run.

    `kxbox/bothways.py` uses up the fresh guest, because the recordings of the two write recipes
    are recordings of the first run of a boot and only match the first run of a boot. Anything
    wanting a live tape afterwards has to have a recipe left that does not care, and if the last
    one of those ever loses the flag this says so rather than the browser harness timing out.
    """
    backend = corpus.Corpus(ROOT)
    assert backend.repeatable(), "no recipe left that gives the same trace on a second run"


def test_the_browser_demo_traces_a_recipe_it_is_allowed_to_trace():
    """The page runs `first-tape.py` after the comparison, so it has to name a repeatable recipe.

    Naming a write recipe there is not a test failure anywhere else in this suite. It fails in a
    browser, minutes into a run, as a trace that does not match its recording, and the reason is
    three files away from the symptom. So it is checked here instead.
    """
    program = (ROOT / "kxbox" / "web" / "first-tape.py").read_text(encoding="utf-8")
    named = re.search(r'^RECIPE = "([^"]+)"', program, re.MULTILINE)
    assert named, "first-tape.py should name the recipe it traces in a RECIPE line"
    wanted = named.group(1)

    backend = corpus.Corpus(ROOT)
    assert wanted in backend.recipes, f"first-tape.py traces `{wanted}`, which is not a recipe"
    assert backend.recipes[wanted].repeatable, (
        f"first-tape.py traces `{wanted}`, which is only the same as its recording on the first "
        "run of a boot, and the page has already run every recipe by the time it gets there"
    )


def test_the_browser_demo_asks_for_what_the_recipe_asks_for():
    """Same functions, same window. A demo that traced it differently would show a different tree.

    The point of the page is that it shows what a lesson shows. It stopped being true once before,
    when this program wrote a file over the bridge instead of running the recipe's command, and the
    picture had seventeen flat frames in it that no lesson would ever produce.
    """
    program = (ROOT / "kxbox" / "web" / "first-tape.py").read_text(encoding="utf-8")
    one = corpus.Corpus(ROOT).recipes[re.search(r'^RECIPE = "([^"]+)"', program, re.M).group(1)]
    assert one.command in program, f"the demo should run `{one.command}`"
    assert f"owns_window={one.owns_window}" in program, "the demo should use the recipe's window"
    for name in one.functions:
        assert f'"{name}"' in program, f"the demo should ask for `{name}` like the recipe does"
