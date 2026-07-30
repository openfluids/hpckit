# navette

`navette` is a small Python CLI for orchestrating Jean Zay workflows from a local project checkout. It manages remote tool checkouts, immutable per-SHA virtualenvs, run packets, Slurm submission/polling, receipts, artifact sync, and local run ledgers.

The first target project is `myproject`, but the package is intentionally separate from that repository: configuration lives in the calling project via `.navette.yaml`.

## Install

For local development:

```bash
uv pip install -e .
```

For command-line use from another checkout:

```bash
pipx install git+https://github.com/openfluids/navette.git
```

## Quickstart

```bash
cd /path/to/your/project
navette init --project myproject
navette doctor
```

## Configure

Create `.navette.yaml` in the project where you run `navette` (see `.navette.example.yaml` for a full template). Tools, job types, and the sparse batch script name are all config-driven:

```yaml
project: myproject
remote: mycluster
work_root: /path/to/work
scratch_root: /path/to/scratch
remote_repos_root: /path/to/work/repos
remote_state_root: /path/to/work/.navette
ledger: NAVETTE_RUN_LOG.md
job_script: job.batch
restart_helper: check_restart.py
tools:
  sigtool:
    repo_url: git@github.com:myorg/sigtool.git
job_types:
  process:
    tool: sigtool
    command: "{venv}/bin/python -m sigtool.cli process --registry {run_dir}/registry.toml --output-root {output_dir}"
artifact_sync:
  processed: data/navette_processed
  renders: plots/navette_renders
  paper_figs: paper/figs
  receipts: navette/receipts
```

## Commands

```bash
navette doctor
navette status
navette update-repo <tool> --ref <sha-or-branch>
navette submit <job_type> <case> --ref <sha>
navette submit sparse <case> --to <target_end_time>
navette poll [run_id]
navette sync-artifacts <run_id>
navette receipt <run_id>
python -m navette doctor
```

Job type subcommands (e.g. `process`, `render`, `plot`) come from `job_types:` in the config. Sparse is built-in and uses `job_script` / `restart_helper`.

## Development

```bash
uv sync --group dev
uv run pytest
uv run python -m build
```

The repository uses the PyPA-recommended `src/` layout, standard `pyproject.toml` metadata, a public `[project.scripts]` entry point, and dependency groups for maintainer tooling.

Destructive remote cleanup is intentionally not implemented. Sparse continuation edits only the case-local restart helper knobs and records the backup name in the receipt.
