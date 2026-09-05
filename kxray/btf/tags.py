"""What the kernel's pointer annotations promise, and which ones BTF actually records.

    from kxray.btf import tags

    print(tags.explain("__user"))

`struct file *f` and `char __user *buf` are both pointers, and the second one is a pointer the
kernel is not allowed to dereference. That difference is invisible in a memory layout, because an
annotation changes no offset and no size. It is a rule about who may follow the pointer, and it is
the rule behind a large share of the bugs a lesson on system calls is about.

Three of the four annotations in this file ride along in BTF as a `type_tag` record, so a reader
can ask a kernel image which of its fields are annotated and get an answer. `__iomem` does not,
and this file says so rather than answering an empty list, because an empty list reads as "there
are none" and the truth is "the file cannot say".

One caveat that matters more than it looks. A type tag reaches BTF only when the compiler that
built the kernel emits it. A kernel built by a toolchain that does not will have BTF with no tags
in it at all, and every question here answers empty for the whole image. `Btf.tag_counts()` is how
you check before believing an empty answer, and `Btf.annotated` refuses outright on a blob that
has no tags anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from kxray.btf.format import BtfError


@dataclass(frozen=True)
class Annotation:
    """One annotation: how it is written, what it promises, and whether BTF carries it."""

    name: str  # what the tag record holds, with no underscores
    promise: str  # the rule a reader breaks by dereferencing it anyway
    reach: str  # how you are supposed to reach the thing behind the pointer
    recorded: bool = True
    instead: str = ""  # where to look when BTF does not record it

    @property
    def written(self) -> str:
        """How the kernel source spells it."""
        return f"__{self.name}"

    def __str__(self) -> str:
        return f"{self.written}: {self.promise} {self.reach}"


KNOWN: dict[str, Annotation] = {
    "user": Annotation(
        name="user",
        promise="This points into the address space of a process, not into the kernel.",
        reach="Copy it with copy_from_user or copy_to_user, which check the address and can fault.",
    ),
    "rcu": Annotation(
        name="rcu",
        promise="This may be replaced at any moment by a writer, and the old value freed later.",
        reach="Read it with rcu_dereference inside an RCU read side section, and publish it with "
        "rcu_assign_pointer.",
    ),
    "percpu": Annotation(
        name="percpu",
        promise="This is an offset into the per-CPU area rather than an address of anything.",
        reach="Turn it into an address for one CPU with this_cpu_ptr or per_cpu_ptr first.",
    ),
    "kptr": Annotation(
        name="kptr",
        promise="This is a kernel pointer stored in a BPF map, owned by the map rather than by "
        "the program that put it there.",
        reach="The verifier decides what a BPF program may do with it, which is the whole reason "
        "the tag exists.",
    ),
    "iomem": Annotation(
        name="iomem",
        promise="This points at a device, not at memory. Reading it has side effects on hardware "
        "and the compiler must not reorder or cache the access.",
        reach="Read and write it with readl, writel and their relatives.",
        recorded=False,
        instead="It is a sparse annotation and nothing else, so the compiler drops it and BTF "
        "never sees it. To find these, read the declaration in the header, or run sparse over "
        "the tree with C=1.",
    ),
}


def annotation(name: str) -> Annotation:
    """One annotation, by either spelling. `user` and `__user` both work."""
    found = KNOWN.get(name.lstrip("_"))
    if found is None:
        known = ", ".join(one.written for one in KNOWN.values())
        raise KeyError(f"{name!r} is not an annotation this knows about. It knows {known}.")
    return found


def explain(name: str) -> str:
    """What it promises, in a sentence or two, plus the BTF caveat when there is one."""
    one = annotation(name)
    lines = [one.promise, one.reach]
    if not one.recorded:
        lines.append(one.instead)
    return " ".join(lines)


def recorded() -> list[str]:
    """The annotations BTF can answer questions about."""
    return [one.name for one in KNOWN.values() if one.recorded]


def check_recorded(name: str) -> Annotation:
    """The annotation, or a refusal saying why the answer would have been misleading."""
    one = annotation(name)
    if not one.recorded:
        raise BtfError(f"{one.written} is not recorded in BTF. {one.instead}")
    return one
