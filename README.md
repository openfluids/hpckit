# jz_pilot

`jzp` is a Jean Zay cockpit CLI for the myproject workflow. It manages remote tool checkouts, immutable per-SHA virtualenvs, run packets, Slurm submission/polling, receipts, artifact sync, and local run ledgers.

## Install

```bash
uv pip install -e .
# or
pip install -e .
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
jzp submit process mycase/340 --spipe-ref <sha>
jzp submit render mycase/355 --neksnap-ref <sha>
jzp submit sparse mycase/340 --to 22224
jzp poll [run_id]
jzp sync-artifacts <run_id>
jzp receipt <run_id>
```

Destructive remote cleanup is intentionally not implemented. Sparse continuation edits only the case-local `check_restart.py` knobs and records the backup name in the receipt.
