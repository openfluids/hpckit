from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TOOLS = {"spipe", "neksnap", "dsgbr", "dynachaos"}
WORKFLOWS = {"process", "render", "plot", "sparse", "dense"}
# Where each workflow's output lands under $WORK/.jz-manager/outputs/.
# Used by build_packet, base_receipt, and cmd_sync_artifacts to stay in sync.
WORKFLOW_OUTPUT_KIND = {"render": "renders", "plot": "figures"}
DEFAULT_OUTPUT_KIND = "processed"


def output_kind(workflow: str) -> str:
    return WORKFLOW_OUTPUT_KIND.get(workflow, DEFAULT_OUTPUT_KIND)


@dataclass
class Config:
    root: Path
    project: str
    remote: str
    work_root: str
    scratch_root: str | None
    remote_repos_root: str
    remote_state_root: str
    ledger: Path
    artifact_sync: dict[str, str]


def run(cmd: list[str], *, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def load_config(start: Path | None = None) -> Config:
    root = start or Path.cwd()
    for path in [root, *root.parents]:
        cfg_path = path / ".jz-manager.yaml"
        if cfg_path.exists():
            data = yaml.safe_load(cfg_path.read_text()) or {}
            return Config(
                root=path,
                project=data.get("project", path.name),
                remote=data.get("remote", "jz"),
                work_root=data["work_root"],
                scratch_root=data.get("scratch_root"),
                remote_repos_root=data.get("remote_repos_root", f"{data['work_root']}/repos"),
                remote_state_root=data.get("remote_state_root", f"{data['work_root']}/.jz-manager"),
                ledger=path / data.get("ledger", "JZ_RUN_LOG.md"),
                artifact_sync=data.get("artifact_sync", {}),
            )
    raise SystemExit("missing .jz-manager.yaml in cwd or parents")


def ssh(cfg: Config, script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    # ssh joins argv[2:] with spaces; without quoting the script, only the
    # first token reaches bash -lc and the rest leak into the outer shell.
    # Quote once so the whole script is a single bash -lc argument.
    remote_cmd = f"bash -lc {shlex.quote(script.lstrip())}"
    return run(["ssh", cfg.remote, remote_cmd], check=check)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def shell_quote(s: str) -> str:
    return shlex.quote(s)


def short_ref(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", ref)[:7] or "unknown"


def case_slug(case: str) -> str:
    return case.strip("/").replace("/", "_")


def run_id(workflow: str, case: str, ref: str) -> str:
    return f"{utc_now()}-{workflow}-{case_slug(case)}-{short_ref(ref)}"


def project_path(cfg: Config, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else cfg.root / candidate


def local_receipt_dir(cfg: Config) -> Path:
    return project_path(cfg, cfg.artifact_sync.get("receipts", "jz_manager/receipts"))


def read_receipt(cfg: Config, rid: str) -> dict[str, Any]:
    path = local_receipt_dir(cfg) / f"{rid}.json"
    if path.exists():
        return json.loads(path.read_text())
    remote = f"{cfg.remote_state_root}/receipts/{rid}.json"
    cp = ssh(cfg, f"cat {shell_quote(remote)}", check=False)
    if cp.returncode != 0:
        raise SystemExit(f"receipt not found: {rid}")
    return json.loads(cp.stdout)


def write_local_receipt(cfg: Config, receipt: dict[str, Any]) -> None:
    out = local_receipt_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{receipt['run_id']}.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def append_ledger(cfg: Config, line: str) -> None:
    cfg.ledger.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    with cfg.ledger.open("a") as fh:
        fh.write(f"\n## {stamp} jzp\n\n{line}\n")


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"project: {cfg.project}")
    print(f"remote: {cfg.remote}")
    local = run(["ssh", "-G", cfg.remote], check=False)
    print(f"ssh_config: {'ok' if local.returncode == 0 else 'failed'}")
    venv = f"{cfg.work_root}/.venv"
    script = f"""
set -e
printf 'work_root: '; test -d {shell_quote(cfg.work_root)} && echo ok || echo missing
printf 'remote_state_root: '; mkdir -p {shell_quote(cfg.remote_state_root)}/{{runs,outputs/processed,outputs/renders,receipts}} && echo ok
printf 'remote_repos_root: '; mkdir -p {shell_quote(cfg.remote_repos_root)} && echo ok
printf 'slurm: '; command -v sbatch >/dev/null && command -v squeue >/dev/null && echo ok || echo missing
for t in spipe neksnap nekStab; do
  if test -d {shell_quote(cfg.remote_repos_root)}/$t/.git; then
    sha=$(git -C {shell_quote(cfg.remote_repos_root)}/$t rev-parse --short HEAD 2>/dev/null || true)
    echo "repo.$t: $sha"
  else
    echo "repo.$t: missing"
  fi
done
if test -d {shell_quote(venv)}; then
  pyver=$({shell_quote(venv)}/bin/python --version 2>&1)
  echo "shared_venv: ok ($pyver)"
  for mod in spipe neksnap dsgbr dynachaos scipy numpy matplotlib pyvista pymech vtk; do
    if {shell_quote(venv)}/bin/python -c "import $mod" 2>/dev/null; then
      echo "  import.$mod: ok"
    else
      echo "  import.$mod: missing"
    fi
  done
  command -v ffmpeg >/dev/null && echo "  bin.ffmpeg: ok" || echo "  bin.ffmpeg: missing"
else
  echo "shared_venv: missing (expected at {venv})"
fi
"""
    cp = ssh(cfg, script, check=False)
    print(cp.stdout, end="")
    if cp.stderr:
        print(cp.stderr, file=sys.stderr, end="")
    return cp.returncode


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    script = f"""
set -e
squeue -u \"$USER\" -o '%.18i %.9T %.30j %.10M %.10L' || true
echo '--- recent receipts ---'
ls -1t {shell_quote(cfg.remote_state_root)}/receipts/*.json 2>/dev/null | head -10 | xargs -r -n1 basename
"""
    cp = ssh(cfg, script, check=False)
    print(cp.stdout, end="")
    if cp.stderr:
        print(cp.stderr, file=sys.stderr, end="")
    return cp.returncode


def cmd_update_repo(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.tool not in TOOLS:
        raise SystemExit(f"unknown tool {args.tool}; expected one of {sorted(TOOLS)}")
    repo_url = args.repo_url or f"git@github.com:ricardofrantz/{args.tool}.git"
    tool = shell_quote(args.tool)
    ref = shell_quote(args.ref)
    repo_url_q = shell_quote(repo_url)
    script = f"""
set -euo pipefail
mkdir -p {shell_quote(cfg.remote_repos_root)} {shell_quote(cfg.remote_state_root)}/envs
repo={shell_quote(cfg.remote_repos_root)}/{tool}
if test ! -d "$repo/.git"; then git clone {repo_url_q} "$repo"; fi
git -C "$repo" fetch --all --tags --prune
git -C "$repo" checkout {ref}
sha=$(git -C "$repo" rev-parse HEAD)
env={shell_quote(cfg.remote_state_root)}/envs/{args.tool}-$sha
if test ! -d "$env"; then
  uv venv "$env"
  "$env/bin/python" -m pip install -U pip
  "$env/bin/python" -m pip install -e "$repo"
fi
ln -sfn ../../.jz-manager/envs/{args.tool}-$sha "$repo/.venv"
printf '%s\n' "$sha"
"""
    cp = ssh(cfg, script)
    sha = cp.stdout.strip().splitlines()[-1]
    print(f"{args.tool}: {sha}")
    return 0


def _minimal_registry_toml(work_root: str, case: str) -> str:
    slug = case_slug(case)
    return (
        "[defaults]\n"
        f'input_root = "{work_root}"\n\n'
        f"[cases.{slug}]\n"
        f'input_path = "{case}"\n'
        'signal_files = ["lift_drag.all"]\n'
    )


def build_packet(cfg: Config, rid: str, workflow: str, case: str, repos: dict[str, str], extra: dict[str, Any]) -> Path:
    root = cfg.root / ".jz-manager" / "runs" / rid
    root.mkdir(parents=True, exist_ok=True)
    run_yaml = {"run_id": rid, "project": cfg.project, "workflow": workflow, "case": case, "repos": repos, **extra}
    (root / "run.yaml").write_text(yaml.safe_dump(run_yaml, sort_keys=False))

    remote_run = f"{cfg.remote_state_root}/runs/{rid}"
    remote_out = f"{cfg.remote_state_root}/outputs/{output_kind(workflow)}/{rid}"
    venv = f"{cfg.work_root}/.venv"

    if workflow == "process":
        registry_src = extra.get("registry")
        if registry_src:
            src = Path(registry_src).expanduser()
            if not src.is_absolute():
                src = (cfg.root / src).resolve()
            if not src.exists():
                raise SystemExit(f"--registry path not found: {src}")
            (root / "registry.toml").write_text(src.read_text())
        else:
            (root / "registry.toml").write_text(_minimal_registry_toml(cfg.work_root, case))
        body = (
            f'mkdir -p {shell_quote(remote_out)}\n'
            f'{shell_quote(venv + "/bin/python")} -m spipe.cli process \\\n'
            f'  --registry {shell_quote(remote_run + "/registry.toml")} \\\n'
            f'  --output-root {shell_quote(remote_out)}\n'
            f'echo "DONE process {case} -> {remote_out}"\n'
        )
        time_limit = "01:00:00"
    elif workflow == "render":
        pattern = extra.get("pattern", "*0.f0*")
        body = (
            f'mkdir -p {shell_quote(remote_out)}\n'
            f'{shell_quote(venv + "/bin/neksnap")} render-many \\\n'
            f'  --case-dir {shell_quote(cfg.work_root + "/" + case)} \\\n'
            f'  --pattern {shell_quote(pattern)} \\\n'
            f'  --out {shell_quote(remote_out)}\n'
            f'echo "DONE render {case} -> {remote_out}"\n'
        )
        time_limit = "04:00:00"
    elif workflow == "plot":
        kind = extra.get("kind") or case
        registry_arg = ""
        registry_src = extra.get("registry")
        if registry_src:
            src = Path(registry_src).expanduser()
            if not src.is_absolute():
                src = (cfg.root / src).resolve()
            if not src.exists():
                raise SystemExit(f"--registry path not found: {src}")
            (root / "registry.toml").write_text(src.read_text())
            registry_arg = f' \\\n  --registry {shell_quote(remote_run + "/registry.toml")}'
        body = (
            f'mkdir -p {shell_quote(remote_out)}\n'
            f'{shell_quote(venv + "/bin/python")} -m spipe.cli plot \\\n'
            f'  --kind {shell_quote(kind)} \\\n'
            f'  --output-root {shell_quote(remote_out)}{registry_arg}\n'
            f'echo "DONE plot {kind} -> {remote_out}"\n'
        )
        time_limit = "00:30:00"
    else:
        body = f"echo 'jzp run {rid}'\necho 'workflow {workflow}'\necho 'case {case}'\n"
        time_limit = "00:30:00"

    job = (
        "#!/bin/bash\n"
        f"#SBATCH --job-name={rid[:40]}\n"
        f"#SBATCH --output={remote_run}/slurm-%j.out\n"
        f"#SBATCH --error={remote_run}/slurm-%j.err\n"
        "#SBATCH --account=vpo@cpu\n"
        "#SBATCH --partition=prepost\n"
        f"#SBATCH --time={time_limit}\n"
        "#SBATCH --ntasks=1\n"
        "#SBATCH --cpus-per-task=4\n"
        "set -euo pipefail\n"
        f"{body}"
    )
    (root / "job.sbatch").write_text(job)
    return root


def upload_packet(cfg: Config, rid: str, packet: Path) -> None:
    remote_run = f"{cfg.remote_state_root}/runs/{rid}"
    ssh(cfg, f"mkdir -p {shell_quote(remote_run)}")
    run(["rsync", "-az", f"{packet}/", f"{cfg.remote}:{remote_run}/"])


def base_receipt(cfg: Config, rid: str, workflow: str, case: str, repos: dict[str, str]) -> dict[str, Any]:
    return {
        "run_id": rid,
        "project": cfg.project,
        "workflow": workflow,
        "case": case,
        "job_id": None,
        "remote_case_path": f"{cfg.work_root}/{case}",
        "remote_output_path": f"{cfg.remote_state_root}/outputs/{output_kind(workflow)}/{rid}",
        "repos": repos,
        "status": "prepared",
        "submitted_at": None,
        "validated_at": None,
    }


def publish_receipt(cfg: Config, receipt: dict[str, Any]) -> None:
    write_local_receipt(cfg, receipt)
    tmp = cfg.root / ".jz-manager" / f"{receipt['run_id']}.receipt.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    remote = f"{cfg.remote_state_root}/receipts/{receipt['run_id']}.json"
    run(["scp", str(tmp), f"{cfg.remote}:{remote}"])


def cmd_submit(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.workflow == "sparse":
        return submit_sparse(cfg, args)
    # For `submit plot <kind>` the positional is named `kind`; mirror it onto
    # `case` so the run_id / receipt path is uniform across workflows.
    if args.workflow == "plot" and not getattr(args, "case", None):
        args.case = args.kind
    ref = getattr(args, "spipe_ref", None) or getattr(args, "neksnap_ref", None) or "unknown"
    rid = run_id(args.workflow, args.case, ref)
    repos = {"spipe": getattr(args, "spipe_ref", None), "neksnap": getattr(args, "neksnap_ref", None)}
    extra: dict[str, Any] = {}
    if getattr(args, "registry", None):
        extra["registry"] = args.registry
    if getattr(args, "pattern", None):
        extra["pattern"] = args.pattern
    if getattr(args, "kind", None):
        extra["kind"] = args.kind
    packet = build_packet(cfg, rid, args.workflow, args.case, repos, extra)
    upload_packet(cfg, rid, packet)
    receipt = base_receipt(cfg, rid, args.workflow, args.case, repos)
    if not args.manual:
        cp = ssh(cfg, f"cd {shell_quote(cfg.remote_state_root + '/runs/' + rid)} && sbatch job.sbatch")
        m = re.search(r"Submitted batch job (\d+)", cp.stdout)
        receipt["job_id"] = m.group(1) if m else cp.stdout.strip()
        receipt["status"] = "submitted"
        receipt["submitted_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    publish_receipt(cfg, receipt)
    append_ledger(cfg, f"- prepared {args.workflow} run `{rid}` for `{args.case}`; job_id={receipt['job_id']}")
    print(rid)
    return 0


def submit_sparse(cfg: Config, args: argparse.Namespace) -> int:
    case = args.case.strip("/")
    dom = hashlib.sha1(f"{case}:{args.to}:{args.chunk}".encode()).hexdigest()[:7]
    rid = run_id("sparse", case, dom)
    force = "True" if args.force_reconcile else "False"
    chunk_line = "" if args.chunk is None else f"new_chunk={float(args.chunk)}"
    dry_run = bool(getattr(args, "dry_run", False))

    # Probe-only half: parses helper constants, validates jz.pbs + .par, prints
    # a SENTINEL line on success. No file is mutated. Used by --dry-run, then
    # repeated as the first step of the real submit.
    probe = f"""
set -euo pipefail
case_dir={shell_quote(cfg.work_root + '/' + case)}
cd "$case_dir"
test -f check_restart.py || {{ echo 'missing check_restart.py' >&2; exit 2; }}
test -f jz.pbs || {{ echo 'missing jz.pbs' >&2; exit 2; }}
old_target=$(python3 - <<'PY'
import re, pathlib
s=pathlib.Path('check_restart.py').read_text()
m=re.search(r'^target_end_time\\s*=\\s*([0-9.eE+-]+)', s, re.M)
print(m.group(1) if m else '')
PY
)
old_chunk=$(python3 - <<'PY'
import re, pathlib
s=pathlib.Path('check_restart.py').read_text()
m=re.search(r'^single_job_time\\s*=\\s*([0-9.eE+-]+)', s, re.M)
print(m.group(1) if m else '')
PY
)
test -n "$old_target" && test -n "$old_chunk" || {{ echo 'cannot parse check_restart.py constants' >&2; exit 3; }}
python3 - <<'PY'
import pathlib, sys
text=pathlib.Path('jz.pbs').read_text()
if 'python3 check_restart.py >> nextlog' not in text:
    sys.exit('jz.pbs does not call python3 check_restart.py >> nextlog')
PY
par_end=$(python3 - <<'PY'
import pathlib,re
for p in pathlib.Path('.').glob('*.par'):
    s=p.read_text(errors='ignore')
    m=re.search(r'endTime\\s*=\\s*([0-9.eE+-]+)', s)
    if m:
        print(m.group(1)); break
PY
)
python3 - <<PY
old_target=float('$old_target'); par='$par_end'; force={force}
if par:
    pe=float(par)
    if pe > old_target + 1e-9 and not force:
        raise SystemExit(f'.par endTime {{pe}} is past helper target {{old_target}}; use --force-reconcile')
PY
would_backup="check_restart.py.pre${{old_target}}_{utc_now()}"
printf 'JZP_PROBE %s %s %s %s\\n' "$old_target" "$old_chunk" "$par_end" "$would_backup"
"""

    if dry_run:
        cp = ssh(cfg, probe)
        parts = [ln for ln in cp.stdout.strip().splitlines() if ln.startswith("JZP_PROBE ")]
        if not parts:
            raise SystemExit(f"sparse dry-run probe returned no JZP_PROBE line:\n{cp.stdout}\n{cp.stderr}")
        _, old_target, old_chunk, par_end, would_backup = parts[-1].split(maxsplit=4)
        new_chunk = float(args.chunk) if args.chunk is not None else float(old_chunk)
        print(
            f"DRY-RUN sparse continuation for {case}\n"
            f"  current target_end_time = {old_target}\n"
            f"  current single_job_time = {old_chunk}\n"
            f"  current .par endTime    = {par_end or '(none found)'}\n"
            f"  would set target_end_time = {float(args.to)}\n"
            f"  would set single_job_time = {new_chunk}\n"
            f"  would back up to         = {would_backup}\n"
            f"  would sbatch jz.pbs      (skipped in dry-run)"
        )
        return 0

    # Real submit: probe (with same sentinel), then mutate + sbatch.
    mutate = f"""
{probe}
backup="check_restart.py.pre${{old_target}}_{utc_now()}"
cp check_restart.py "$backup"
python3 - <<PY
import pathlib,re
p=pathlib.Path('check_restart.py')
s=p.read_text()
s=re.sub(r'^target_end_time\\s*=\\s*[0-9.eE+-]+', 'target_end_time = {float(args.to)}', s, count=1, flags=re.M)
{chunk_line}
if {args.chunk is not None}:
    s=re.sub(r'^single_job_time\\s*=\\s*[0-9.eE+-]+', f'single_job_time = {{new_chunk}}', s, count=1, flags=re.M)
p.write_text(s)
PY
job=$(sbatch jz.pbs | awk '{{print $NF}}')
printf '%s %s %s %s\\n' "$job" "$backup" "$old_target" "$old_chunk"
"""
    cp = ssh(cfg, mutate)
    job, backup, old_target, old_chunk = cp.stdout.strip().split()[-4:]
    receipt = base_receipt(cfg, rid, "sparse", case, {})
    receipt.update({"job_id": job, "status": "submitted", "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(), "target_end_time": float(args.to), "single_job_time": float(args.chunk) if args.chunk else None, "backup_file": backup, "previous_target_end_time": old_target, "previous_single_job_time": old_chunk})
    publish_receipt(cfg, receipt)
    append_ledger(cfg, f"- submitted sparse continuation `{rid}` for `{case}` to {args.to}; first job `{job}`; backup `{backup}`")
    print(rid)
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.run_id:
        receipt = read_receipt(cfg, args.run_id)
        job = receipt.get("job_id")
        if job:
            cp = ssh(cfg, f"sacct -j {shell_quote(str(job))} --format=JobID,State,Elapsed,ExitCode -P 2>/dev/null || squeue -j {shell_quote(str(job))}", check=False)
            print(cp.stdout, end="")
        if receipt.get("workflow") == "sparse":
            case = receipt["case"]
            script = f"cd {shell_quote(cfg.work_root + '/' + case)} && python3 - <<'PY'\nimport pathlib,re,glob,os\ns=pathlib.Path('check_restart.py').read_text()\nfor k in ['target_end_time','single_job_time']:\n m=re.search(r'^'+k+r'\\s*=\\s*([0-9.eE+-]+)', s, re.M); print(k + ': ' + (m.group(1) if m else '?'))\nfs=sorted(glob.glob('*0.f0*'), key=os.path.getmtime)\nprint('latest_field: '+(fs[-1] if fs else 'none'))\nPY"
            print(ssh(cfg, script, check=False).stdout, end="")
    else:
        return cmd_status(args)
    return 0


def cmd_sync_artifacts(args: argparse.Namespace) -> int:
    cfg = load_config()
    receipt = read_receipt(cfg, args.run_id)
    workflow = receipt["workflow"]
    key = output_kind(workflow)
    dest = project_path(cfg, cfg.artifact_sync.get(key, f"data/jz_{key}")) / args.run_id
    dest.mkdir(parents=True, exist_ok=True)
    src = receipt["remote_output_path"].rstrip("/") + "/"
    cp = run(["rsync", "-az", f"{cfg.remote}:{src}", str(dest) + "/"], check=False)
    if cp.returncode != 0:
        if cp.stdout:
            print(cp.stdout, end="")
        if cp.stderr:
            print(cp.stderr, file=sys.stderr, end="")
        raise SystemExit(f"rsync failed for {args.run_id} with exit code {cp.returncode}")
    receipt["status"] = "validated"
    receipt["validated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_local_receipt(cfg, receipt)
    append_ledger(cfg, f"- synced artifacts for `{args.run_id}` to `{dest}`")
    print(dest)
    return 0


def cmd_receipt(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(json.dumps(read_receipt(cfg, args.run_id), indent=2, sort_keys=True))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    project = args.project or Path.cwd().name
    remote = args.remote
    work_root = args.work_root
    scratch_root = args.scratch_root
    cfg_path = Path(".jz-manager.yaml")
    if cfg_path.exists() and not args.force:
        print(f"{cfg_path} already exists; use --force to overwrite", file=sys.stderr)
        return 1
    data = {
        "project": project,
        "remote": remote,
        "work_root": work_root,
        "scratch_root": scratch_root,
        "remote_repos_root": f"{work_root}/repos",
        "remote_state_root": f"{work_root}/.jz-manager",
        "ledger": "JZ_RUN_LOG.md",
        "beads": ".beads",
        "artifact_sync": {
            "processed": "data/jz_processed",
            "renders": "plots/jz_renders",
            "figures": "data/jz_figures",
            "paper_figs": "paper/figs",
            "receipts": "jz_manager/receipts",
        },
    }
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False))
    Path("jz_manager/receipts").mkdir(parents=True, exist_ok=True)
    Path(".jz-manager").mkdir(parents=True, exist_ok=True)
    print(str(cfg_path.resolve()))
    print("Next: jzp doctor")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jzp")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    ini = sub.add_parser("init")
    ini.add_argument("--project")
    ini.add_argument("--remote", default="jz")
    ini.add_argument("--work-root", default="/path/to/work")
    ini.add_argument("--scratch-root", default="/path/to/scratch")
    ini.add_argument("--force", action="store_true")
    ini.set_defaults(func=cmd_init)
    sub.add_parser("status").set_defaults(func=cmd_status)
    u = sub.add_parser("update-repo")
    u.add_argument("tool", choices=sorted(TOOLS))
    u.add_argument("--ref", required=True)
    u.add_argument("--repo-url")
    u.set_defaults(func=cmd_update_repo)

    s = sub.add_parser("submit")
    ss = s.add_subparsers(dest="workflow", required=True)

    pr = ss.add_parser("process")
    pr.add_argument("case")
    pr.add_argument("--spipe-ref", required=True)
    pr.add_argument("--registry", help="path to a spipe registry.toml; minimal one generated if omitted")
    pr.add_argument("--manual", action="store_true")
    pr.set_defaults(func=cmd_submit)

    rr = ss.add_parser("render")
    rr.add_argument("case")
    rr.add_argument("--neksnap-ref", required=True)
    rr.add_argument("--pattern", default="*0.f0*", help="snapshot glob inside the case dir")
    rr.add_argument("--manual", action="store_true")
    rr.set_defaults(func=cmd_submit)

    pl = ss.add_parser("plot", help="render a spipe.figures paper figure on JZ")
    pl.add_argument("kind", help="figure name (must match spipe.figures registry, e.g. fig9)")
    pl.add_argument("--spipe-ref", required=True)
    pl.add_argument("--registry", help="optional registry.toml supplied by the cockpit")
    pl.add_argument("--manual", action="store_true")
    pl.set_defaults(func=cmd_submit)

    sp = ss.add_parser("sparse")
    sp.add_argument("case")
    sp.add_argument("--dry-run", action="store_true", help="probe + report; do not mutate check_restart.py or sbatch")
    sp.add_argument("--to", required=True, type=float)
    sp.add_argument("--chunk", type=float)
    sp.add_argument("--force-reconcile", action="store_true")
    sp.set_defaults(func=cmd_submit)

    po = sub.add_parser("poll")
    po.add_argument("run_id", nargs="?")
    po.set_defaults(func=cmd_poll)

    sy = sub.add_parser("sync-artifacts")
    sy.add_argument("run_id")
    sy.set_defaults(func=cmd_sync_artifacts)

    r = sub.add_parser("receipt")
    r.add_argument("run_id")
    r.set_defaults(func=cmd_receipt)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
