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

## Every traced action has a name

`write-1byte` is not decoration. It is what the recording is filed under, and it is the thing both backends agree about. The callable beside it is what the live backend runs, and the recorded backend ignores it because there is nothing to run it on. That is the one asymmetry in the design and it lives in one function rather than in a hundred lesson cells.

The names, what each one does and which capture answers it are in `corpora/tier0/recipes.toml`.

## The banner

The first cell of every lesson prints it, because somebody reading a trace needs to know whether it came off a kernel or out of a file before they read a single line of it.

A live session says what Tier 0 is: uniprocessor, 32 bit x86, emulated timing, and no performance claim can be made from it. A recorded session says that it is not a running kernel, why the emulator was not used, and whether what it is handing back is evidence at all. Today it is not, because the two recordings that exist were written by hand so the parser had something to parse.

## What is here and what is not

`session.py` is the session and the banner. `corpus.py` replays a recording. `bridge.py` is the Python half of the conversation with the emulator, and `PROTOCOL.md` is the contract, which is four calls wide and says why the calls are synchronous and what that costs in hosting.

`web/` is the other half: the shared buffer the answer comes back through, the shell protocol every call turns into, the page that boots the emulator, and a server that sets the two headers a blocking worker needs.

`kernel/` is the pin, the config fragments and the build script. `pin.toml` says which kernel, from where, with which checksum.

Not here: the v86 vendoring, the rootfs, and a built kernel. Nobody has booted anything for this project. Both halves of the protocol are written and both are tested without an emulator, the Python one through a stand in that implements the four calls and the JavaScript one through a guest that answers like a shell, so the part that is unproven is the emulator rather than the code around it.
