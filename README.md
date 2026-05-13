# jz_pilot

`jzp` is a small Python CLI for orchestrating Jean Zay workflows from a local project checkout. It manages remote tool checkouts, immutable per-SHA virtualenvs, run packets, Slurm submission/polling, receipts, artifact sync, and local run ledgers.

The first target project is `myproject`, but the package is intentionally separate from that repository: configuration lives in the calling project via `.jz-manager.yaml`.

## Install

For local development:

```bash
uv pip install -e .
```

For command-line use from another checkout:

```bash
pipx install git+https://github.com/ricardofrantz/jz_pilot.git
```

## Quickstart

```bash
cd /path/to/your/project
jzp init --project myproject
jzp doctor
```

## Configure

Create `.jz-manager.yaml` in the project where you run `jzp`:

```yaml
project: myproject
remote: jz
work_root: /path/to/work
scratch_root: /path/to/scratch
remote_repos_root: /path/to/work/repos
remote_state_root: /path/to/work/.jz-manager
ledger: JZ_RUN_LOG.md
beads: .beads
artifact_sync:
  processed: data/jz_processed
  renders: plots/jz_renders
  paper_figs: paper/figs
  receipts: jz_manager/receipts
```

## Commands

```bash
jzp doctor
jzp status
jzp update-repo spipe --ref <sha-or-branch> --repo-url <git-url>
jzp update-repo neksnap --ref <sha-or-branch> --repo-url <git-url>
jzp submit process mycase/340 --spipe-ref <sha>
jzp submit render mycase/355 --neksnap-ref <sha>
jzp submit sparse mycase/340 --to 22224
jzp poll [run_id]
jzp sync-artifacts <run_id>
jzp receipt <run_id>
python -m jz_pilot doctor
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run python -m build
```

The repository uses the PyPA-recommended `src/` layout, standard `pyproject.toml` metadata, a public `[project.scripts]` entry point, and dependency groups for maintainer tooling.

Destructive remote cleanup is intentionally not implemented. Sparse continuation edits only the case-local `check_restart.py` knobs and records the backup name in the receipt.
