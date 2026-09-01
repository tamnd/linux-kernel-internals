"""Z02: your first trace.

Run it with `marimo edit lessons/Z02/notebook.py`, or in the browser once the site is up.

The capture step is not here yet. `kxbox` is what boots a real kernel in the tab and runs the
write for you, and it does not exist, so today this notebook takes a trace you captured on a
Linux machine and does everything after that. The parsing, the tape and the grading are real and
work now. When `kxbox` lands, the paste box becomes a Run button and nothing else in here moves.
"""

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import importlib.util
    import sys
    from pathlib import Path

    import marimo as mo

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here.parents[1]))

    from kxray.trace import function_graph

    spec = importlib.util.spec_from_file_location("z02_grader", here / "grader.py")
    grader = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = grader
    spec.loader.exec_module(grader)
    return function_graph, grader, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Z02: your first trace

    You are going to watch the kernel do one small thing, function by function, with a time
    next to each one.

    Work down the page in order. The prediction step is first on purpose, and it is the
    step people skip.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Predict

    Answer before you look at anything. A wrong prediction you wrote down is worth more
    than a right answer you read.
    """)
    return


@app.cell
def _(mo):
    prediction = mo.ui.text_area(
        label="In your own words, what do you expect the kernel to do with one byte?",
        placeholder="It probably calls something like ...",
        rows=3,
        full_width=True,
    )
    frames = mo.ui.dropdown(
        options=["10", "100", "1000", "10000"],
        label="How many function calls does writing one byte take?",
    )
    outermost = mo.ui.text(label="Name the outermost kernel function you expect to see")
    depth = mo.ui.number(start=0, stop=64, step=1, value=0, label="How deep does the stack go?")
    reached_disk = mo.ui.checkbox(label="The write reaches the disk before write() returns")
    cpus = mo.ui.number(start=0, stop=64, step=1, value=1, label="How many CPUs appear?")

    mo.vstack([prediction, frames, outermost, depth, reached_disk, cpus])
    return cpus, depth, frames, outermost, prediction, reached_disk


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Capture

    On a Linux machine, as root:

    ```sh
    cd /sys/kernel/tracing
    echo function_graph > current_tracer
    echo vfs_write > set_graph_function
    echo 1 > tracing_on
    dd if=/dev/zero of=/tmp/one bs=1 count=1 status=none
    echo 0 > tracing_on
    cat trace
    ```

    Paste what `cat trace` printed into the box. Paste all of it, including the header
    lines at the top, because the parser reads those too.
    """)
    return


@app.cell
def _(mo):
    trace_text = mo.ui.text_area(
        label="Your trace",
        placeholder="# tracer: function_graph",
        rows=12,
        full_width=True,
    )
    trace_text
    return (trace_text,)


@app.cell(hide_code=True)
def _(function_graph, mo, trace_text):
    tape = function_graph.parse(trace_text.value or "", source="your capture")

    if not trace_text.value.strip():
        summary = mo.md("Waiting for a trace.")
    else:
        summary = mo.md(
            f"""
            **{tape.frame_count}** calls, **{len(tape.roots)}** outermost,
            **{tape.max_depth}** levels deep, on CPU(s) **{tape.cpus}**.
            **{len(tape.unparsed)}** lines the parser did not recognise.
            """
        )
    summary
    return (tape,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Read it

    The tree below is the same trace with the columns taken off, so the shape is easier to
    see. The raw text above is the evidence. This is a rendering of it, and if the two ever
    disagree, the raw text is right.
    """)
    return


@app.cell(hide_code=True)
def _(mo, tape):
    mo.md(f"```\n{tape.tree() or 'nothing parsed yet'}\n```")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Grade

    Every check below compares your answer against the trace you pasted. There is no answer
    key. A number that is right on somebody else's machine is not right here.
    """)
    return


@app.cell(hide_code=True)
def _(cpus, depth, frames, outermost, prediction, reached_disk):
    answers = {
        "prediction": prediction.value,
        "frames": frames.value,
        "outermost": outermost.value,
        "depth": depth.value,
        "reached_disk": reached_disk.value,
        "cpus": cpus.value,
    }
    return (answers,)


@app.cell(hide_code=True)
def _(answers, grader, mo, tape):
    if tape.frame_count == 0:
        marks = mo.md("Paste a trace first.")
    else:
        marks = mo.md(f"```\n{grader.report(grader.grade(tape, answers))}\n```")
    marks
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Change something

    Go back to the shell and capture again, once per change, comparing each result with the
    one before it.

    1. `echo vfs_write > set_graph_function` narrows the trace to one call. The frame count
       should fall a long way.
    2. `echo 3 > max_graph_depth` flattens the tree. The durations on what remains do not
       change, because the limit changes what gets printed and not what runs.
    3. `echo 0 > max_graph_depth` puts it back.

    Then read `per_cpu/cpu0/stats` and look at `overrun`. If it is not zero, the buffer
    threw away lines while you were tracing, and it did not tell you.
    """)
    return


if __name__ == "__main__":
    app.run()
