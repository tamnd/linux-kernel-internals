# kxbox

Tier 0: a real Linux kernel in a browser tab, and a recording of one for every machine that does not have a browser tab.

```python
import kxbox

box = kxbox.boot(profile="teaching")
print(box.banner())

tape = box.trace("write-1byte", lambda: box.sh("dd if=/dev/zero of=/tmp/one bs=1 count=1"))
print(tape.tree())
```

Those lines run the same way against the emulator and against a recording, and they hand back the same objects either way.

## Why that matters more than it sounds

The obvious way to write a fallback is a branch: use the emulator if it is there, and print something canned if it is not. That gives you two code paths, one of which is exercised constantly and one of which is exercised by nobody until a reader hits it on a Tuesday.

Here there is one path. `box.trace(...)` returns a `kxray.models.Tape` from both backends, so the widget, the diagram and the blueprint that consume it cannot tell which one they got. `KXBOX_DISABLE=1` forces the recording, every lesson has to work that way, and CI runs them all like that. The fallback is the tested path rather than the promised one.

## The five calls

| call | what it does | on a recording |
| --- | --- | --- |
| `kxbox.boot(profile)` | a session, live if there is one | picks the recorded backend and says why in the banner |
| `box.sh(line, recipe=)` | one shell line, waited for | the recorded standard output and exit status |
| `box.read(path, recipe=)` | a file inside the guest | the recorded snapshot of that file |
| `box.trace(name, do, ...)` | the function graph tracer around something | the recorded tape, and the callable is not run |
| `box.insmod(path)` | load a module | the recorded reply to having loaded it |

All five return the same types from both backends. `sh` and `insmod` give a `Command`, `read` gives a string, `trace` gives a `kxray.models.Tape`. A test compares the two backends' signatures argument by argument, because an argument one has and the other does not is a lesson that raises `TypeError` on the reader's machine rather than on the one it was written on. That test is how `max_depth` was found: the live backend had it from the day it was written, nothing else did, and a knob documented as the fix for a hanging guest could not be reached from a lesson.

There is no `box.write`. The live backend has one and uses it to drive the tracer, and it is not offered to a lesson, because a recording can say what a file contained and can do nothing at all about a lesson writing to it. A cell whose effect quietly does not happen on most readers' machines is worse than one that cannot be written.

The `recipe=` argument on `sh` and `read` names which recording answers the call. A live kernel ignores it. That is the one asymmetry in the design and it is in one place rather than in a hundred lesson cells.

## Every traced action has a name

`write-1byte` is not decoration. It is what the recording is filed under, and it is the thing both backends agree about. The callable beside it is what the live backend runs, and the recorded backend ignores it because there is nothing to run it on. That is the one asymmetry in the design and it lives in one function rather than in a hundred lesson cells.

The names, what each one does and which capture answers it are in `corpora/tier0/recipes.toml`.

## The banner

The first cell of every lesson prints it, because somebody reading a trace needs to know whether it came off a kernel or out of a file before they read a single line of it.

A live session says what Tier 0 is: uniprocessor, 32 bit x86, emulated timing, and no performance claim can be made from it. A recorded session says that it is not a running kernel, why the emulator was not used, and whether what it is handing back is evidence at all. Today it is not, because the two recordings that exist were written by hand so the parser had something to parse.

Either way the banner also says what the profile turns on and what it costs, which is the line that stops somebody timing a function on the lockdep kernel and reporting the number.

## The three profiles

A lesson asks for one of three kernels by name, and `kxbox/profiles.py` is the list.

| profile | gives you | costs |
| --- | --- | --- |
| `teaching` | ftrace, kprobes, BTF, every `/proc` file the book reads, and modules | nothing beyond its size, which is what makes it the default |
| `lockdep` | lockdep, lock statistics, and the sleeping in atomic context checks | every lock the kernel takes is recorded and checked, so timings mean nothing |
| `memcheck` | KFENCE, page poisoning, unmapped freed pages, and the slab debugger | freed pages are unmapped and rewritten, so allocation timings mean nothing |

A name nothing builds raises rather than being carried. This used to be a free string, so `boot("lockdpe")` came up saying it had booted a lockdep kernel while actually running the teaching one, and a lesson about lock ordering would then find no lock ordering problems for the least interesting reason there is. A clean answer that means nothing is worse than a crash.

The third one is called `memcheck` and not `kasan` because KASAN cannot exist on this kernel. `arch/x86/Kconfig` selects `HAVE_ARCH_KASAN` only under `X86_64`, Tier 0 is 32 bit, and Kconfig drops a symbol whose dependencies are unmet without saying a word. `kernel/README.md` has the whole story, including the two config lines that had been asking for it since the day they were written.

These three names are separate from the six build profiles in `kernel/pin.toml`. Those are named `A-full` through `E-memcheck` and exist to settle the kill criterion. `profiles.py` is where a name a lesson wrote turns into a kernel somebody built, so a lesson never has to know which is which.

## What is here and what is not

`session.py` is the session and the banner. `profiles.py` is the three kernels a lesson may ask for. `corpus.py` replays a recording. `bridge.py` is the Python half of the conversation with the emulator, and `PROTOCOL.md` is the contract, which is four calls wide and says why the calls are synchronous and what that costs in hosting.

`web/` is the other half: the shared buffer the answer comes back through, the shell protocol every call turns into, the page that boots the emulator, and a server that sets the two headers a blocking worker needs.

`kernel/` is the pin, the config fragments and the build script. `pin.toml` says which kernel, from where, with which checksum.

`rootfs/` is the initramfs: a pinned busybox, a pinned strace built from source, three small programs that each do one thing so a trace of one has one thing in it, an init script that mounts the filesystems the lessons need and prints the ready marker, and a build script that makes the cpio. `web/vendor.toml` pins v86 and `tools/vendor.py` fetches it against those checksums.

## Booting one

Three commands, in this order, and none of them needs root.

```sh
python3 -m tools.vendor          # fetch v86 at the pinned commit
sh kxbox/rootfs/build.sh         # build the initramfs
sh kxbox/kernel/build.sh A-full  # build the kernel, needs docker
node kxbox/web/headless.js smoke # boot it and check what works
```

The kernel build is the only one that takes real time. `headless.js` runs v86 under node, which means the whole thing can be exercised on a machine with no display and in CI, and a boot that broke can be bisected without anybody clicking anything.

The numbers from the first real boot are in `kernel/RESULTS.md`.
