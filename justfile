# Task runner for the repository.
# Run `just` with no arguments to see the list.

default:
    @just --list

# Everything CI runs, in the same order. Run this before you open a pull request.
check: lint prose diagrams-check claims baseline refs blueprints kconfig tier0 web storyboards notebooks site-check test

# Install the development dependencies into a local virtual environment.
setup:
    uv venv
    uv pip install -e ".[dev]"

# Python style and correctness.
lint:
    uvx ruff check .
    uvx ruff format --check .

# Fix what can be fixed automatically.
fmt:
    uvx ruff check --fix .
    uvx ruff format .

# House style for prose. The rules are in tools/lintprose/rules.py.
prose:
    python3 -m tools.lintprose README.md CONTRIBUTING.md LAYOUT.md lessons blueprints corpora kxbox site

# Print the prose rules and what each one is for.
prose-rules:
    python3 -m tools.lintprose --list-rules .

# Check that every claim a lesson makes has something behind it.
claims:
    python3 -m tools.claimledger

# Print the kinds of evidence a claim is allowed to rest on.
claim-kinds:
    python3 -m tools.claimledger --list-kinds

# Check how much of every committed artefact the parsers still understand.
baseline:
    python3 -m tools.baseline

# Print what the readers see, without comparing it to anything.
baseline-show:
    python3 -m tools.baseline --show

# Write down what the readers see now. Say in the commit message why a number moved.
baseline-write:
    python3 -m tools.baseline --write

# Check every reference: paths we write about, and citations into the kernel.
refs:
    python3 -m tools.refcheck

# Unpack the pinned kernel source, which is what a citation resolves against.
tree:
    ./kxbox/kernel/tree.sh

# Resolve every kernel citation against the unpacked tree, without writing anything.
refs-resolve tree="kxbox/kernel/build/tree/linux-7.2.2":
    python3 -m tools.refcheck --tree {{tree}}

# The same, but write the line numbers back and flip the confirmed flags.
refs-confirm tree="kxbox/kernel/build/tree/linux-7.2.2":
    python3 -m tools.refcheck --tree {{tree}} --confirm

# Print the paths this repository writes about that do not exist yet.
refs-planned:
    python3 -m tools.refcheck --list-planned

# Check the shape of every blueprint, and the seals on its generated sections.
blueprints:
    python3 -m tools.bpc

# Rewrite sections 2, 5 and 7 of every blueprint from BTF and the corpus, then reseal.
# With no btf= it writes the honest empty state, which is what CI has to see today.
blueprints-generate btf="":
    python3 -m tools.bpc --generate {{ if btf == "" { "" } else { "--btf " + btf } }}

# The same thing against the kernel this project pins, once `just kernel-build A-full` has run.
# That vmlinux is an ELF image and the BTF is in a section inside it, which the reader handles.
blueprints-generate-pinned:
    just blueprints-generate kxbox/kernel/build/A-full/vmlinux

# Recompute the seals after regenerating a section.
reseal:
    python3 -m tools.bpc --reseal blueprints

# Check the pinned kernel and every config profile built from it.
kconfig:
    python3 -m tools.kconfig

# Print the config symbols the book cannot work without, and what each one gives you.
kconfig-required:
    python3 -m tools.kconfig --list-required

# What Tier 0 can do on this machine, and which recordings it would fall back to.
tier0-report:
    python3 -m kxbox

# Fail if a Tier 0 recipe names a capture nobody committed.
tier0:
    python3 -m kxbox --check

# The browser half of Tier 0: the channel, the shell protocol and the blocking call.
web:
    node --test tests/web/*.test.js

# Build the project as a wheel where the worker can fetch it. Pyodide has no checkout to import
# from, so the only way Python in a tab gets kxray is to install it, and micropip installs wheels.
web-wheel:
    uv build --wheel --out-dir kxbox/web/build

# Serve Tier 0 with the two headers a blocking worker needs, and open /web/ in a browser.
web-serve: web-wheel
    python3 kxbox/web/serve.py

# The kill criterion: boot the kernel in a real browser and time it. Fills in the browser table
# in kxbox/kernel/RESULTS.md, which is the one measurement node cannot make.
web-measure profile="A-full": web-wheel
    node kxbox/web/measure.js --profile {{profile}}

# Fetch v86 at the pinned commit, checked against the sha256 of every file in web/vendor.toml.
vendor:
    python3 -m tools.vendor

# Fail if what is in web/vendor is not what the pin asks for.
vendor-check:
    python3 -m tools.vendor --check

# Build one profile of the pinned kernel in a container. Takes a while the first time.
kernel profile="A-full":
    ./kxbox/kernel/build.sh {{profile}}

# Build the initramfs the kernel boots into. No container and no root.
rootfs:
    sh kxbox/rootfs/build.sh

# Everything Tier 0 needs, in order, from nothing to a booted kernel.
box: vendor rootfs kernel boot-smoke

# Boot the built kernel under node and print how long it took.
boot:
    node kxbox/web/headless.js boot

# Boot it and check the nine things a lesson stops working without.
boot-smoke:
    node kxbox/web/headless.js smoke

# Run one command inside the box.
boot-sh command:
    node kxbox/web/headless.js sh {{quote(command)}}

# Check every storyboard against the rules: the budget, the captions, the alt text, the still.
storyboards:
    python3 -m kxmanim

# Write the caption track and the transcript for every storyboard.
captions out="/tmp/kxmanim":
    python3 -m kxmanim --captions {{out}}

# Install manim, which nothing except rendering an animation needs.
setup-animation:
    uv pip install -e ".[animation]"

# Draw all four widgets into one page, from the handwritten fixtures, so you can look at them.
widgets out="/tmp/kxwidgets.html":
    python3 -m kxwidgets --preview {{out}}

# Rebuild the small handwritten BTF blob the reader is tested against.
btf-fixture:
    python3 corpora/btf/handwritten/make.py

# Rebuild every lesson notebook and its markdown from the build.py beside it.
build-lessons:
    python3 -m tools.nbbuild

# Fail if a committed notebook or lesson.md is out of date with its builder.
notebooks:
    python3 -m tools.nbbuild --check

# Rebuild every diagram from its Python source.
diagrams:
    python3 -m tools.diagrams

# Fail if a committed diagram is out of date with its source.
diagrams-check:
    python3 -m tools.diagrams --check

# Stage the lessons and the blueprints into the site, and write mkdocs.yml and the stylesheet.
site:
    python3 -m tools.sitebuild

# Fail if mkdocs.yml or the generated stylesheet is out of date with what is on disk.
site-check:
    python3 -m tools.sitebuild --check

# Build the book. Strict, so a link that points at nothing stops the build.
site-build: site
    cd site && mkdocs build --strict

# Preview it on localhost:8000 while you edit.
site-serve: site
    cd site && mkdocs serve

# Install mkdocs, the theme and the notebook renderer. Nothing else needs them.
setup-site:
    uv pip install -e ".[site]"

test:
    python3 -m pytest
