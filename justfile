# Task runner for the repository.
# Run `just` with no arguments to see the list.

default:
    @just --list

# Everything CI runs, in the same order. Run this before you open a pull request.
check: lint prose diagrams-check claims refs blueprints kconfig notebooks test

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
    python3 -m tools.lintprose README.md CONTRIBUTING.md LAYOUT.md lessons blueprints corpora kxbox

# Print the prose rules and what each one is for.
prose-rules:
    python3 -m tools.lintprose --list-rules .

# Check that every claim a lesson makes has something behind it.
claims:
    python3 -m tools.claimledger

# Print the kinds of evidence a claim is allowed to rest on.
claim-kinds:
    python3 -m tools.claimledger --list-kinds

# Check every reference: paths we write about, and citations into the kernel.
refs:
    python3 -m tools.refcheck

# Resolve every kernel citation against a real tree, and write the line numbers back.
refs-confirm tree:
    python3 -m tools.refcheck --tree {{tree}} --confirm

# Print the paths this repository writes about that do not exist yet.
refs-planned:
    python3 -m tools.refcheck --list-planned

# Check the shape of every blueprint, and the seals on its generated sections.
blueprints:
    python3 -m tools.bpc

# Recompute the seals after regenerating a section.
reseal:
    python3 -m tools.bpc --reseal blueprints

# Check the pinned kernel and every config profile built from it.
kconfig:
    python3 -m tools.kconfig

# Print the config symbols the book cannot work without, and what each one gives you.
kconfig-required:
    python3 -m tools.kconfig --list-required

# Build one profile of the pinned kernel in a container. Takes a while the first time.
kernel profile="A-full":
    ./kxbox/kernel/build.sh {{profile}}

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

test:
    python3 -m pytest
