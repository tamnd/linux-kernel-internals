# Recorded sessions

Real terminal sessions from a real Linux machine, recorded so that a reader on Tier 0 can step through them.

Everywhere else in this project the rule is that nothing is asserted that you cannot watch happen. A reader opens a notebook, runs a cell, and the thing the lesson claims happens in front of them. That works for the whole of Tier 0 and it does not work for a kernel build, because a browser tab cannot run gcc over a hundred and sixty megabytes of source, and it never will.

So the few things a browser cannot do are recorded instead of described. You get the command, the output, how long it took, and whether it worked. A recording is not the same as running it yourself and this directory does not pretend otherwise, but it beats a paragraph telling you what you would have seen.

## What is in a recording

Three files per session, and only the first one is evidence.

    build-and-boot-uml.cast          the recording, asciinema v2, never edited
    build-and-boot-uml.meta.toml     which machine, which day, and why Tier 0 could not do it
    build-and-boot-uml.notes.toml    one sentence per step, saying what to look at

The split is deliberate. The recording is what happened and nothing is allowed to change it, not a typo fix and not a tidier line. Everything anybody wants to say about it goes in the notes file, keyed by step number and by the command that step ran. If a session is recorded again and the commands move, the notes stop matching and loading them raises rather than quietly attaching last week's sentence to this week's step.

The `.cast` is asciinema v2, which is a documented format and not one invented here. `asciinema play build-and-boot-uml.cast` will play it back at the speed it happened.

## What makes it steppable

A terminal recording is one long stream of bytes with nothing in it that says where one command ended and the next began. The structure comes from four escape sequences the shell was asked to print, a convention called OSC 133 that iTerm2, kitty and WezTerm already speak: a prompt is starting, the prompt is finished, the command is running, the command finished with this status. `kxray.replay.session` reads those four and cuts the stream between them.

A recording made with plain `asciinema rec` has no marks in it. That is not an error and it does not get guessed at. It comes back as one step holding the whole session, and the widget says so, because looking for a dollar sign to find the prompts would find every dollar sign in a build log too.

## Reading one

    from kxray import replay
    from kxwidgets import SessionPlayer

    one = replay.load("corpora/replays/tier1/build-and-boot-uml.cast")
    print(one.table())
    SessionPlayer(one)

`table()` is the whole session in a dozen lines and is usually where to start. `SessionPlayer` draws the strip across the top, one segment per step as wide a share as that step was of the time, with the output behind a fold under it.

## build-and-boot-uml.cast

Thirteen commands. A Debian container with no compiler in it becomes a container that has built Linux 7.2.2 and booted it, in six and a half minutes.

The point of the session is the last step. The kernel that was built two commands earlier is started as an ordinary program, with no disk image and no virtual machine, and it prints the same version string that the compiler stamped into it a minute before. That is User Mode Linux, which is a real port of the kernel to an architecture whose hardware is Linux system calls, and it is the cheapest way to get a kernel you built to say something back to you.

Step 4 is worth more than it looks. It prints the sha256 of the tarball, and the hash it prints is character for character the one in `pin.toml`. The kernel built in step 9 is the kernel this project pins, and the recording proves it rather than asserting it.

Step 9 is the reason the widget has a strip. Five minutes and eleven seconds, against a minute and a half for the other twelve steps put together. That shape is the fact a person who has never built a kernel is missing, and it is exactly the fact a written transcript throws away.

Two Docker options in the metadata's `setup` list are load bearing, and both cost an afternoon to find. User Mode Linux uses ptrace to intercept the system calls of the processes inside it, so the container needs `--security-opt seccomp=unconfined --cap-add=SYS_PTRACE` or the boot dies in its own start up checks. And UML keeps its physical memory in a file under `/dev/shm` which it maps executable, so the container needs `--tmpfs /dev/shm:rw,exec,size=2g`, because Docker mounts `/dev/shm` noexec and the boot stops on `Checking PROT_EXEC mmap in /dev/shm...Operation not permitted`.

## Taking one

You need a real Linux machine and the container `pin.toml` names. The `setup` list in the `.meta.toml` is everything that happened before the recording started, and `command` says what drove it.

    python3 -m kxray.replay.record out.cast --title "..." -- first command -- second command

Each `--` starts another command. They run one after another in one bash under a pseudo terminal, and the next one is not sent until the shell says the last one finished.

The pseudo terminal is not an implementation detail. A program behaves differently when it thinks a person is watching: `make` draws its progress by writing over the line above, and it only does that to a terminal. Record through a pipe and you have recorded the program's other personality.

Two things to know before recording something long. The recorder waits on the prompt rather than on the exit status, because there is a moment between a command finishing and the next prompt being drawn where anything typed lands above the prompt instead of below it. And a session ends when the last command ends: the `exit` that closes the shell is not recorded, because a walkthrough whose final step is a shell shutting down with no status reads like the recording broke.
