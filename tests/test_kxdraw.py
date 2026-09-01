"""Tests for the diagram toolkit and the diagram build.

The last test in this file is the one that earns its keep. It rebuilds every diagram in the
repository and fails if the committed output differs, which is the only thing standing between a
diagram and its source drifting apart.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from kxdraw import Scene, to_excalidraw, to_svg
from kxdraw.scene import facing_sides
from tools import diagrams

REPO = Path(__file__).resolve().parents[1]


def simple() -> Scene:
    s = Scene("A test scene", width=400, height=200)
    a = s.box(20, 20, 120, 60, "first")
    b = s.box(240, 20, 120, 60, "second", style="accent")
    s.arrow(a, b, label="then")
    s.note(20, 150, "a note", muted=True)
    return s


def test_a_scene_holds_what_you_put_in_it():
    s = simple()
    assert [b.label for b in s.boxes] == ["first", "second"]
    assert len(s.arrows) == 1
    assert len(s.notes) == 1
    assert s.arrows[0].label == "then"


def test_an_unknown_style_is_refused_at_the_point_of_use():
    s = Scene("x")
    with pytest.raises(ValueError, match="unknown style"):
        s.box(0, 0, 10, 10, style="neon")


def test_an_arrow_leaves_from_the_side_facing_the_other_box():
    s = Scene("x")
    left = s.box(0, 0, 100, 100)
    right = s.box(300, 0, 100, 100)
    below = s.box(0, 300, 100, 100)
    assert facing_sides(left, right) == ("right", "left")
    assert facing_sides(right, left) == ("left", "right")
    assert facing_sides(left, below) == ("bottom", "top")
    assert facing_sides(below, left) == ("top", "bottom")


def test_the_svg_is_well_formed_and_carries_its_own_description():
    svg = to_svg(simple(), "two boxes joined by an arrow")
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert root.attrib["role"] == "img"
    texts = {e.text for e in root.iter() if e.tag.endswith("title") or e.tag.endswith("desc")}
    assert "A test scene" in texts
    assert "two boxes joined by an arrow" in texts


def test_the_svg_escapes_text_rather_than_breaking():
    s = Scene("x", width=100, height=100)
    s.note(0, 0, "a < b && c > d")
    root = ET.fromstring(to_svg(s))
    assert any(e.text == "a < b && c > d" for e in root.iter())


def test_excalidraw_output_is_the_same_every_time():
    # Excalidraw fills seeds with random numbers. If we did that, every rebuild would be a diff
    # and nobody would ever run the check.
    assert to_excalidraw(simple()) == to_excalidraw(simple())


def test_every_bound_label_points_at_an_element_that_exists():
    scene = to_excalidraw(simple())
    ids = {e["id"] for e in scene["elements"]}
    for element in scene["elements"]:
        for bound in element.get("boundElements", []):
            assert bound["id"] in ids
        container = element.get("containerId")
        if container:
            assert container in ids


def test_a_diagram_source_without_alt_text_is_refused(tmp_path):
    source = tmp_path / "no-alt.diagram.py"
    source.write_text("from kxdraw import Scene\n\n\ndef scene():\n    return Scene('x')\n")
    with pytest.raises(RuntimeError, match="ALT"):
        diagrams.load(source)


def test_a_diagram_source_that_returns_the_wrong_thing_is_refused(tmp_path):
    source = tmp_path / "wrong.diagram.py"
    source.write_text('ALT = "something"\n\n\ndef scene():\n    return 42\n')
    with pytest.raises(RuntimeError, match="expected a Scene"):
        diagrams.load(source)


def test_a_diagram_source_produces_an_svg_and_an_excalidraw(tmp_path):
    source = tmp_path / "thing.diagram.py"
    source.write_text(
        'ALT = "one box"\n'
        "from kxdraw import Scene\n\n\n"
        "def scene():\n"
        "    s = Scene('one box', width=100, height=100)\n"
        "    s.box(10, 10, 80, 40, 'hello')\n"
        "    return s\n"
    )
    built = diagrams.render(source)
    assert set(built) == {tmp_path / "thing.svg", tmp_path / "thing.excalidraw"}
    ET.fromstring(built[tmp_path / "thing.svg"])
    assert json.loads(built[tmp_path / "thing.excalidraw"])["type"] == "excalidraw"


def test_every_committed_diagram_is_up_to_date(monkeypatch):
    monkeypatch.chdir(REPO)
    assert diagrams.main(["--check"]) == 0
