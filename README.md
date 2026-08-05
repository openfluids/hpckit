![hpckit banner](https://raw.githubusercontent.com/openfluids/hpckit/main/assets/readme-banner-v1.jpg)

[![CI](https://github.com/openfluids/hpckit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/openfluids/hpckit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hpckit.svg)](https://pypi.org/project/hpckit/)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fopenfluids%2Fhpckit%2Fmain%2Fpyproject.toml&label=python)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

`hpckit` is a small Python CLI for orchestrating Slurm cluster workflows from a
local project checkout. It manages remote tool checkouts, immutable per-SHA
virtualenvs, run packets, Slurm submission and polling, receipts, artifact sync,
and local run ledgers.

The tools it runs are declared in your own `.hpckit.yaml` — `hpckit` ships none of
them, and depends on nothing but a YAML parser itself.

Its companion renderer is [`quadros`](https://github.com/openfluids/quadros),
which turns simulation field snapshots into frames and video. Add it with the
`renderer` extra if you want to render as well as submit:

```bash
pip install hpckit              # submit jobs only
pip install 'hpckit[renderer]'  # ...and render locally
```

It stays optional on purpose: `quadros` brings VTK, roughly 700 MB, and a machine
that only submits jobs should not pay that.

Configuration lives in the project you run it from, not in this repository, so one
installation drives any number of projects.

## Install

For local development:

```bash
uv pip install -e .
```

For command-line use from another checkout:

```bash
pipx install git+https://github.com/openfluids/hpckit.git
```

## Quickstart

```bash
cd /path/to/your/project
hpckit init --project myproject
hpckit doctor
```

## Configure

Create `.hpckit.yaml` in the project where you run `hpckit` (see `.hpckit.example.yaml` for a full template). Tools, job types, and the sparse batch script name are all config-driven:

```yaml
project: myproject
remote: mycluster
work_root: /path/to/work
scratch_root: /path/to/scratch
remote_repos_root: /path/to/work/repos
remote_state_root: /path/to/work/.hpckit
ledger: HPCKIT_RUN_LOG.md
job_script: job.batch
restart_helper: check_restart.py
prologue: |                      # optional — site environment setup
  module load myenv
  export OMP_NUM_THREADS=1
slurm:
  account: myproj@cpu   # required — no default
  partition: prepost
  ntasks: 1
  cpus_per_task: 4
tools:
  sigtool:
    repo_url: git@github.com:myorg/sigtool.git
job_types:
  process:
    tool: sigtool
    command: "{venv}/bin/python -m sigtool.cli process --registry {run_dir}/registry.toml --output-root {output_dir}"
artifact_sync:
  processed: data/hpckit_processed
  renders: plots/hpckit_renders
  paper_figs: paper/figs
  receipts: hpckit/receipts
```

## Commands

```bash
hpckit doctor
hpckit status
hpckit update-repo <tool> --ref <sha-or-branch>
hpckit submit <job_type> <case> --ref <sha>
hpckit submit sparse <case> --to <target_end_time>
hpckit poll [run_id]
hpckit sync-artifacts <run_id>
hpckit receipt <run_id>
python -m hpckit doctor
```

Job type subcommands (e.g. `process`, `render`, `plot`) come from `job_types:` in the config. Sparse is built-in and uses `job_script` / `restart_helper`.

### Site environment setup

`sbatch` starts a **non-login shell**, so anything your login profile would normally
provide — `module load`, an MPI or compiler environment — is absent inside the job unless
you set it up there. That failure is a quiet one: the command still runs, it just cannot
find the tools it expected, and you get a result that looks like a real one.

`prologue:` is shell run inside the generated `job.sbatch`, after `set -euo pipefail` and
before the job type's command. It goes there rather than inside each `command:` because
command templates are expanded with `str.format_map`, so a shell `${VAR}` would raise
`unknown placeholder '{VAR}'`; because every job type would otherwise repeat it; and
because it varies with the machine, not with the job. Omit it and the generated script is
what it was before.

Some environment scripts reference unbound variables and trip `set -u`. Fence those rather
than dropping the option for the whole job:

```yaml
prologue: |
  set +u
  . /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1
  set -u
  export OMP_NUM_THREADS=1
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run python -m build
```

The repository uses the PyPA-recommended `src/` layout, standard `pyproject.toml` metadata, a public `[project.scripts]` entry point, and dependency groups for maintainer tooling.

Destructive remote cleanup is intentionally not implemented. Sparse continuation edits only the case-local restart helper knobs and records the backup name in the receipt.
