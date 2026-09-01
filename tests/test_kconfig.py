"""Tests for the pinned kernel checker.

The one that matters is the drop rule. A profile that turns off a requirement has to say so and
say why, because a requirement that gets switched off quietly is a lesson that stops working
months later with nothing pointing at the change that did it.
"""

from __future__ import annotations

from pathlib import Path

from tools import kconfig

REAL_PIN = Path(__file__).resolve().parents[1] / "kxbox" / "kernel" / "pin.toml"

FRAGMENT = "\n".join(f"{symbol}=y" for symbol in kconfig.REQUIRED) + "\n"


def pin(tmp_path, profiles: str, fragments: dict[str, str] | None = None) -> Path:
    """A pin file with a real shaped header and whatever profiles the test needs."""
    root = tmp_path / "kernel"
    (root / "config").mkdir(parents=True)
    for name, text in (fragments or {"config/all.config": FRAGMENT}).items():
        (root / name).write_text(text, encoding="utf-8")

    header = """
schema = 1

[kernel]
version = "7.2.2"
url = "https://example.invalid/linux-7.2.2.tar.xz"
sha256 = "7d0e7ce14f98c43efe880cffbf354a59be45928fdf7170d7333c374ae91c0d83"
recorded = "2026-09-01"

[fallback]
version = "6.18.48"
url = "https://example.invalid/linux-6.18.48.tar.xz"
sha256 = "5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c"
recorded = "2026-09-01"
"""
    path = root / "pin.toml"
    path.write_text(header + profiles, encoding="utf-8")
    return path


CLEAN_PROFILE = """
[[profiles]]
name = "A-full"
order = 1
kernel = "kernel"
fragments = ["config/all.config"]
kill_criterion = true
summary = "Everything."
"""


def messages(findings) -> str:
    return "\n".join(str(f) for f in findings)


def test_the_real_pin_is_clean():
    """The one test that would catch somebody editing pin.toml without running the checker."""
    assert kconfig.check(REAL_PIN) == []


def test_a_fragment_parses_into_settings(tmp_path):
    path = tmp_path / "one.config"
    path.write_text("# a comment\nCONFIG_FTRACE=y\n# CONFIG_SMP is not set\nCONFIG_HZ=100\n")

    settings, findings = kconfig.parse_fragment(path)
    assert findings == []
    assert [(s.symbol, s.value) for s in settings] == [
        ("CONFIG_FTRACE", "y"),
        ("CONFIG_SMP", None),
        ("CONFIG_HZ", "100"),
    ]


def test_a_line_that_is_not_a_config_line_is_an_error(tmp_path):
    """A typo in a fragment does not fail a kernel build, it silently does nothing."""
    path = tmp_path / "one.config"
    path.write_text("CONFIG_FTRACE=y\nCONFIG FTRACE=y\n")

    _, findings = kconfig.parse_fragment(path)
    assert len(findings) == 1
    assert "not a config line" in str(findings[0])


def test_an_unset_symbol_is_not_on(tmp_path):
    path = tmp_path / "one.config"
    path.write_text("# CONFIG_SMP is not set\nCONFIG_MODULES=n\n")

    settings, _ = kconfig.parse_fragment(path)
    assert [s.is_on for s in settings] == [False, False]


def test_a_later_fragment_wins(tmp_path):
    first = tmp_path / "a.config"
    second = tmp_path / "b.config"
    first.write_text("CONFIG_DEBUG_INFO_BTF=y\n")
    second.write_text("# CONFIG_DEBUG_INFO_BTF is not set\n")

    merged = kconfig.merge([kconfig.parse_fragment(first)[0], kconfig.parse_fragment(second)[0]])
    assert merged["CONFIG_DEBUG_INFO_BTF"].is_on is False


def test_a_clean_profile_passes(tmp_path):
    assert kconfig.check(pin(tmp_path, CLEAN_PROFILE)) == []


def test_a_missing_requirement_is_named_with_what_it_gives_you(tmp_path):
    without = FRAGMENT.replace("CONFIG_KPROBES=y\n", "")
    findings = kconfig.check(
        pin(tmp_path, CLEAN_PROFILE, {"config/all.config": without}),
    )
    assert "CONFIG_KPROBES" in messages(findings)
    assert "kxprobe" in messages(findings)


def test_a_requirement_can_be_dropped_when_the_profile_says_why(tmp_path):
    without = FRAGMENT.replace("CONFIG_DEBUG_INFO_BTF=y", "# CONFIG_DEBUG_INFO_BTF is not set")
    profile = (
        CLEAN_PROFILE
        + """
drops = ["CONFIG_DEBUG_INFO_BTF"]
drops_reason = "BTF adds several megabytes to an image a browser downloads and then decompresses, so this profile serves it separately."
"""
    )
    assert kconfig.check(pin(tmp_path, profile, {"config/all.config": without})) == []


def test_a_drop_without_a_reason_fails(tmp_path):
    without = FRAGMENT.replace("CONFIG_DEBUG_INFO_BTF=y", "# CONFIG_DEBUG_INFO_BTF is not set")
    profile = CLEAN_PROFILE + '\ndrops = ["CONFIG_DEBUG_INFO_BTF"]\ndrops_reason = "too big"\n'

    findings = kconfig.check(pin(tmp_path, profile, {"config/all.config": without}))
    assert "without saying why" in messages(findings)


def test_a_stale_drop_declaration_fails(tmp_path):
    """Claiming to drop something you then set is a declaration that has outlived its change."""
    profile = (
        CLEAN_PROFILE
        + """
drops = ["CONFIG_DEBUG_INFO_BTF"]
drops_reason = "BTF adds several megabytes to an image a browser downloads and then decompresses, so this profile serves it separately."
"""
    )
    findings = kconfig.check(pin(tmp_path, profile))
    assert "stale" in messages(findings)


def test_a_fragment_that_is_not_there_fails(tmp_path):
    profile = CLEAN_PROFILE.replace("config/all.config", "config/nope.config")
    assert "does not exist" in messages(kconfig.check(pin(tmp_path, profile)))


def test_a_profile_naming_a_kernel_that_is_not_pinned_fails(tmp_path):
    profile = CLEAN_PROFILE.replace('kernel = "kernel"', 'kernel = "nightly"')
    assert "pin.toml has not got" in messages(kconfig.check(pin(tmp_path, profile)))


def test_two_profiles_with_the_same_order_fail(tmp_path):
    assert "same order" in messages(kconfig.check(pin(tmp_path, CLEAN_PROFILE * 2)))


def test_a_pin_with_no_kill_criterion_profile_fails(tmp_path):
    profile = CLEAN_PROFILE.replace("kill_criterion = true", "kill_criterion = false")
    assert "kill criterion" in messages(kconfig.check(pin(tmp_path, profile)))


def test_a_checksum_that_is_not_a_checksum_fails(tmp_path):
    path = pin(tmp_path, CLEAN_PROFILE)
    path.write_text(
        path.read_text().replace("7d0e7ce14f98c43e", "not a checksum"), encoding="utf-8"
    )
    assert "64 hex" in messages(kconfig.check(path))


def test_a_missing_pin_file_is_an_error(tmp_path):
    assert "no pinned kernel" in messages(kconfig.check(tmp_path / "nope.toml"))


def test_verify_reads_a_built_config(tmp_path):
    path = pin(tmp_path, CLEAN_PROFILE)
    built = tmp_path / ".config"
    built.write_text("#\n# Automatically generated file; DO NOT EDIT.\n#\n" + FRAGMENT)

    assert kconfig.verify(path, built, "A-full") == []


def test_verify_catches_a_symbol_kconfig_quietly_dropped(tmp_path):
    """The failure this exists for. Unmet dependencies drop a symbol with no error at all."""
    path = pin(tmp_path, CLEAN_PROFILE)
    built = tmp_path / ".config"
    built.write_text(FRAGMENT.replace("CONFIG_DEBUG_INFO_BTF=y\n", ""))

    findings = kconfig.verify(path, built, "A-full")
    assert "not in the built config" in messages(findings)


def test_verify_catches_a_symbol_that_came_out_off(tmp_path):
    path = pin(tmp_path, CLEAN_PROFILE)
    built = tmp_path / ".config"
    built.write_text(FRAGMENT.replace("CONFIG_MODULES=y", "# CONFIG_MODULES is not set"))

    assert "came out off" in messages(kconfig.verify(path, built, "A-full"))


def test_verify_skips_what_the_profile_declared_it_drops(tmp_path):
    profile = (
        CLEAN_PROFILE
        + """
drops = ["CONFIG_DEBUG_INFO_BTF"]
drops_reason = "BTF adds several megabytes to an image a browser downloads and then decompresses, so this profile serves it separately."
"""
    )
    without = FRAGMENT.replace("CONFIG_DEBUG_INFO_BTF=y", "# CONFIG_DEBUG_INFO_BTF is not set")
    path = pin(tmp_path, profile, {"config/all.config": without})
    built = tmp_path / ".config"
    built.write_text(without)

    assert kconfig.verify(path, built, "A-full") == []


def test_verify_on_a_profile_that_does_not_exist_says_which_ones_do(tmp_path):
    path = pin(tmp_path, CLEAN_PROFILE)
    findings = kconfig.verify(path, tmp_path / ".config", "Z-nope")
    assert "A-full" in messages(findings)


def test_main_checks_the_real_pin():
    assert kconfig.main([str(REAL_PIN)]) == 0


def test_main_lists_the_requirements(capsys):
    assert kconfig.main(["--list-required"]) == 0
    printed = capsys.readouterr().out
    assert "CONFIG_FUNCTION_GRAPH_TRACER" in printed
    assert "Z02" in printed


def test_every_requirement_says_what_it_gives_you():
    """A requirement with no reason is a requirement nobody can argue with or remove."""
    for symbol, why in kconfig.REQUIRED.items():
        assert len(why.split()) >= 4, symbol
