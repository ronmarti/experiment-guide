---
name: python-flat-layout
description: Navigate Python projects with import packages at the repository root. Use when locating source, tests, configuration, or entry points in a flat-layout project, or when checking whether imports resolve from the checkout or an installed distribution.
---

# Navigate a Python flat layout

Use this skill to map an existing Python project before making changes. A flat
layout places import packages beside project configuration at the repository
root; it is not the same as a `src/` layout, where import packages live under
`src/`.

## Map the project

1. Find the repository root from project markers such as `pyproject.toml`,
   `setup.cfg`, or `setup.py`. Read the build backend and package-discovery
   settings before drawing conclusions about what gets distributed.
2. Inspect root-level directories and representative files. Identify import
   packages from their Python modules and package structure; treat names such
   as `tests`, `docs`, and `tools` as candidates, not assumptions. Namespace
   packages may not contain `__init__.py`.
3. Trace the relevant feature through imports and callers. Check the package
   entry point (`__main__.py`, configured scripts, or application startup),
   then follow the code into its model, service, UI, or other domain areas.
4. Locate tests and project-specific run commands from the repository's
   configuration and documentation. Do not infer test or package boundaries
   from directory names alone.
5. Before diagnosing an import or packaging issue, establish how the project
   is run and installed. Python places the current working directory early on
   `sys.path`, so a command launched from the repository may import the
   checkout instead of an installed copy. Verify package-discovery settings
   and, when distribution contents matter, inspect a built distribution.

## Report the map

Give concise, evidence-based paths for:

- the import package or packages relevant to the task;
- tests and their run command;
- configuration that controls packaging or entry points; and
- the execution/import context when it affects the task.

Keep the existing layout. Recommend changing it only when the task requires a
layout change or a demonstrated packaging/import problem calls for one.

## This repository

- `gui/` contains the Solara entry point and UI/session code.
- `experiment/model/` contains project data helpers.
- `experiment/services/` contains validation, persistence, runs, and Ax
  integration.
- `tests/` contains unit and UI component tests. The documented suite is
  `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 poetry run python -m unittest discover -s tests -v`.
- `pyproject.toml` declares Poetry Core as the build backend. Check it for
  package-discovery configuration before making claims about distribution
  contents.

For the distinction between flat and `src/` layouts and their import behavior,
see the [Python Packaging User Guide](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).
