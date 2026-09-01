"""Check the pinned kernel and its config profiles.

    python3 -m tools.kconfig                            check pin.toml and every fragment
    python3 -m tools.kconfig --list-required            print what the book cannot work without
    python3 -m tools.kconfig --profile A-full --verify build/.config

A kernel claim without a version, a config and an architecture attached is not a claim, which is
the rule this project keeps repeating. `pin.toml` is where the version lives and the fragments in
`config/` are where the config lives. This is what stops either of them drifting away from what
the lessons actually need.

The list that matters is `REQUIRED`. Each entry is a symbol the book stops working without, and a
one line reason saying what breaks. A profile is allowed to drop one, because profile B exists
precisely to drop BTF, but it has to say so in `pin.toml` and give a reason. Turning off a
requirement is a decision. Turning one off quietly is how a project ends up with lessons that
cannot run and nobody knowing which change did it.

Nothing here builds a kernel. It reads text files, so it runs in the dependency free job in a
couple of seconds, and it will keep working on a laptop with no toolchain.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1

DEFAULT_PIN = Path("kxbox/kernel/pin.toml")

# What the book cannot work without, and what stops working without it. If you are adding a
# symbol here, name the lesson or the checker. If you cannot, it belongs in a fragment and not in
# this list.
REQUIRED = {
    "CONFIG_FTRACE": "the tracing infrastructure, and so every trace in the book",
    "CONFIG_FUNCTION_TRACER": "the function tracer that function_graph is built on",
    "CONFIG_FUNCTION_GRAPH_TRACER": "Z02, and every trace rendered as a tape",
    "CONFIG_DYNAMIC_FTRACE": "turning tracing on without paying for it when it is off",
    "CONFIG_KPROBES": "kxprobe, and the lessons ftrace cannot reach",
    "CONFIG_KALLSYMS_ALL": "names in a trace instead of addresses",
    "CONFIG_DEBUG_FS": "the tracing filesystem, which is where all the controls are",
    "CONFIG_PROC_FS": "everything the kernel says about itself",
    "CONFIG_SYSFS": "the other half of what the kernel says about itself",
    "CONFIG_MODULES": "every part ends in a change, and most of those changes are a module",
    "CONFIG_MODULE_UNLOAD": "a change you cannot undo is a change nobody experiments with",
    "CONFIG_DEBUG_INFO_BTF": "bpc, and the generated sections of every blueprint",
    "CONFIG_BLK_DEV_INITRD": "there is no disk in a browser tab, so this is how it boots at all",
    "CONFIG_SERIAL_8250_CONSOLE": "the bridge talks to the kernel over the serial port",
}

# A line in a fragment is one of these three shapes and nothing else.
SET = re.compile(r"^(CONFIG_[A-Z0-9_]+)=(.*)$")
UNSET = re.compile(r"^#\s*(CONFIG_[A-Z0-9_]+)\s+is not set\s*$")
COMMENT = re.compile(r"^\s*(#.*)?$")

NOT_SET = None


@dataclass(frozen=True)
class Finding:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class Setting:
    symbol: str
    value: str | None  # None means the symbol is explicitly turned off
    path: str
    line: int

    @property
    def is_on(self) -> bool:
        return self.value not in (None, "n")


def parse_fragment(path: Path) -> tuple[list[Setting], list[Finding]]:
    """Read one fragment. A line that is not a setting, an unset or a comment is an error.

    Being strict here is the point. A typo in a Kconfig fragment does not fail a build, it
    silently leaves the symbol at whatever the base defconfig said, and the first sign of trouble
    is a lesson that does not work months later.
    """
    settings: list[Setting] = []
    findings: list[Finding] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.rstrip()
        unset = UNSET.match(text)
        if unset:
            settings.append(Setting(unset.group(1), NOT_SET, str(path), number))
            continue
        assignment = SET.match(text)
        if assignment:
            settings.append(Setting(assignment.group(1), assignment.group(2), str(path), number))
            continue
        if COMMENT.match(text):
            continue
        findings.append(Finding(f"{path}:{number}", f"not a config line: {text!r}"))
    return settings, findings


def merge(fragments: list[list[Setting]]) -> dict[str, Setting]:
    """Later fragments win, which is what the kernel's own merge_config.sh does."""
    merged: dict[str, Setting] = {}
    for fragment in fragments:
        for setting in fragment:
            merged[setting.symbol] = setting
    return merged


def read_config(path: Path) -> dict[str, Setting]:
    """A real `.config` out of a build. Same three shapes, and unreadable lines are ignored.

    A generated `.config` has header comments and section banners in it that no fragment would
    have, so being strict here would fail on the kernel's own output.
    """
    settings, _ = parse_fragment(path)
    return merge([settings])


def check_profile(root: Path, pin: dict, profile: dict) -> list[Finding]:
    where = f"{root}#{profile.get('name', '?')}"
    findings: list[Finding] = []

    name = profile.get("name")
    if not name:
        return [Finding(str(root), "a profile with no name")]
    for key in ("order", "summary", "kill_criterion", "fragments", "kernel"):
        if key not in profile:
            findings.append(Finding(where, f"missing {key}"))

    if profile.get("kernel") not in pin:
        findings.append(
            Finding(where, f"names kernel {profile.get('kernel')!r}, which pin.toml has not got")
        )

    fragments = []
    for relative in profile.get("fragments", []):
        path = root.parent / relative
        if not path.exists():
            findings.append(Finding(where, f"names {relative}, which does not exist"))
            continue
        settings, problems = parse_fragment(path)
        findings.extend(problems)
        fragments.append(settings)

    if findings:
        return findings

    merged = merge(fragments)
    drops = set(profile.get("drops", []))
    reason = str(profile.get("drops_reason", "")).strip()

    if drops and len(reason.split()) < 10:
        findings.append(
            Finding(
                where, "drops a symbol without saying why, which is how a requirement gets lost"
            )
        )

    for symbol, why in REQUIRED.items():
        setting = merged.get(symbol)
        present = setting is not None and setting.is_on
        if present and symbol in drops:
            findings.append(
                Finding(
                    where,
                    f"declares it drops {symbol} and then sets it, so the declaration is stale",
                )
            )
        if present or symbol in drops:
            continue
        findings.append(Finding(where, f"does not set {symbol}, which is what gives you {why}"))

    for symbol in sorted(drops - set(REQUIRED)):
        findings.append(
            Finding(
                where,
                f"declares it drops {symbol}, which was never required, so it says nothing",
            )
        )

    return findings


def check(path: Path) -> list[Finding]:
    """Read a pin file and check every profile in it."""
    if not path.exists():
        return [Finding(str(path), "no pin file, so there is no pinned kernel")]

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    findings: list[Finding] = []

    if document.get("schema") != SCHEMA:
        findings.append(
            Finding(str(path), f"schema is {document.get('schema')!r}, expected {SCHEMA}")
        )

    for key in ("kernel", "fallback"):
        block = document.get(key)
        if not isinstance(block, dict):
            findings.append(Finding(str(path), f"no [{key}] block"))
            continue
        for field in ("version", "url", "sha256", "recorded"):
            if not block.get(field):
                findings.append(Finding(f"{path}#{key}", f"missing {field}"))
        digest = str(block.get("sha256", ""))
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            findings.append(Finding(f"{path}#{key}", "sha256 is not 64 hex characters"))

    profiles = document.get("profiles", [])
    if not profiles:
        findings.append(Finding(str(path), "no profiles, so nothing to build"))

    orders = [p.get("order") for p in profiles]
    if len(set(orders)) != len(orders):
        findings.append(
            Finding(str(path), "two profiles claim the same order, so the order is not one")
        )

    if not any(p.get("kill_criterion") for p in profiles):
        findings.append(
            Finding(
                str(path), "no profile counts towards the kill criterion, so it cannot be settled"
            )
        )

    for profile in profiles:
        findings.extend(check_profile(path, document, profile))

    return findings


def verify(path: Path, built: Path, name: str) -> list[Finding]:
    """Check a real `.config` out of a build against one profile's requirements.

    A fragment says what was asked for. A `.config` says what Kconfig actually did with it, after
    resolving every dependency, and those are not the same thing. A symbol whose dependencies are
    unmet gets dropped without an error, which is the failure this catches.
    """
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = {p.get("name"): p for p in document.get("profiles", [])}
    if name not in profiles:
        return [Finding(str(path), f"no profile called {name!r}, there is {sorted(profiles)}")]
    if not built.exists():
        return [Finding(str(built), "no built config to check")]

    profile = profiles[name]
    drops = set(profile.get("drops", []))
    actual = read_config(built)

    findings = []
    for symbol, why in REQUIRED.items():
        if symbol in drops:
            continue
        setting = actual.get(symbol)
        if setting is None:
            findings.append(
                Finding(str(built), f"{symbol} is not in the built config, and it gives you {why}")
            )
        elif not setting.is_on:
            findings.append(Finding(str(built), f"{symbol} came out off, and it gives you {why}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kconfig", description="Check the pinned kernel and its config."
    )
    ap.add_argument("pin", nargs="?", default=str(DEFAULT_PIN), help="Path to pin.toml")
    ap.add_argument("--list-required", action="store_true", help="Print the required symbols")
    ap.add_argument("--profile", help="Profile name, with --verify")
    ap.add_argument("--verify", help="A built .config to check against --profile")
    args = ap.parse_args(argv)

    if args.list_required:
        for symbol, why in REQUIRED.items():
            print(f"{symbol:32} {why}")
        return 0

    pin = Path(args.pin)

    if args.verify:
        if not args.profile:
            print("kconfig: --verify needs --profile", file=sys.stderr)
            return 2
        findings = verify(pin, Path(args.verify), args.profile)
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} problem(s) in the built config", file=sys.stderr)
            return 1
        print(f"kconfig: {args.verify} has everything {args.profile} promised")
        return 0

    findings = check(pin)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} problem(s) in {pin}", file=sys.stderr)
        return 1

    document = tomllib.loads(pin.read_text(encoding="utf-8"))
    profiles = document.get("profiles", [])
    print(f"kconfig: {document['kernel']['version']} pinned, {len(profiles)} profile(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
