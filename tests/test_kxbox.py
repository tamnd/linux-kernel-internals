"""Tests for the Tier 0 session.

The property worth testing is the one the whole design rests on: a lesson cell written once runs
against the emulator and against a recording, and gets back the same types from both. A fallback
that is a second code path is a fallback nobody exercises until a reader hits it.

The live backend is driven through a stand in that implements the four calls in `PROTOCOL.md`.
Nobody has run it against v86, because the kernel is not built and the JavaScript is not written.
What these tests pin down is the Python half and the protocol it expects.
"""

from __future__ import annotations

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
            "/sys/kernel/tracing/trace": TRACE,
            "/sys/kernel/tracing/set_ftrace_filter": "",
            "/sys/kernel/tracing/tracing_on": "0\n",
        }
        self.ran: list[str] = []
        self.wrote: list[tuple[str, str]] = []

    def sh(self, line: str) -> Reply:
        self.ran.append(line)
        return Reply(0, "1+0 records in\n", "")

    def read(self, path: str) -> str:
        return self.files[path]

    def write(self, path: str, text: str) -> None:
        self.wrote.append((path, text))
        self.files[path] = text

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
    assert fake.files["/sys/kernel/tracing/set_ftrace_filter"] == ""


def test_the_live_backend_puts_the_tracer_back_even_when_the_callable_throws():
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")

    def explode():
        raise RuntimeError("the lesson did something wrong")

    with pytest.raises(RuntimeError):
        box.trace("write-1byte", explode)
    assert fake.files["/sys/kernel/tracing/tracing_on"] == "0"


def test_the_live_backend_sets_the_filter_it_was_given():
    fake = FakeBridge()
    box = kxbox.Box(bridge.V86(fake), "teaching")
    box.trace("write-1byte", None, functions=["vfs_write", "generic_perform_write"])
    assert (
        "/sys/kernel/tracing/set_ftrace_filter",
        "vfs_write\ngeneric_perform_write",
    ) in fake.wrote


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


def test_every_recipe_here_is_still_handwritten():
    """When this starts failing, somebody has booted a kernel, and that is the good failure."""
    backend = corpus.Corpus(ROOT)
    assert backend.recipes, "the repository should have recordings"
    assert backend.evidence is False
