# Task runner for the repository.
# Run `just` with no arguments to see the list.

default:
    @just --list

# Everything CI runs, in the same order. Run this before you open a pull request.
check: lint prose diagrams-check claims notebooks test

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
    python3 -m tools.lintprose README.md CONTRIBUTING.md LAYOUT.md lessons blueprints corpora

# Print the prose rules and what each one is for.
prose-rules:
    python3 -m tools.lintprose --list-rules .

# Check that every claim a lesson makes has something behind it.
claims:
    python3 -m tools.claimledger

# Print the kinds of evidence a claim is allowed to rest on.
claim-kinds:
    python3 -m tools.claimledger --list-kinds

# Check that every lesson notebook is a valid marimo notebook.
notebooks:
    uvx --from marimo marimo check --strict lessons/*/notebook.py

# Rebuild every diagram from its Python source.
diagrams:
    python3 -m tools.diagrams

# Fail if a committed diagram is out of date with its source.
diagrams-check:
    python3 -m tools.diagrams --check

test:
    python3 -m pytest
