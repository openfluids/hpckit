from __future__ import annotations

import re

import yaml

from hpckit.cli import build_parser, case_slug, run_id, short_ref

# Shared job_types / tools used by packet and parser tests.
DEMO_TOOLS = {
    "sigtool": {"repo_url": "git@github.com:myorg/sigtool.git"},
    "snaptool": {"repo_url": "git@github.com:myorg/snaptool.git"},
}
DEMO_JOB_TYPES = {
    "process": {
        "tool": "sigtool",
        "command": (
            "{venv}/bin/python -m sigtool.cli process "
            "--registry {run_dir}/registry.toml --output-root {output_dir}"
        ),
        "time_limit": "01:00:00",
    },
    "render": {
        "tool": "snaptool",
        "command": (
            "{venv}/bin/snaptool render-many --case-dir {case_dir} "
            "--pattern '{pattern}' --out {output_dir}"
        ),
        "output_kind": "renders",
        "time_limit": "04:00:00",
    },
    "plot": {
        "tool": "sigtool",
        "command": (
            "{venv}/bin/python -m sigtool.cli plot --kind {kind} --output-root {output_dir}"
        ),
        "output_kind": "figures",
        "time_limit": "00:30:00",
    },
}


def _write_cfg(tmp_path, **extra) -> None:
    data = {
        "project": "Demo",
        "remote": "mycluster",
        "work_root": "/work/demo",
        "remote_state_root": "/work/demo/.hpckit",
        "job_script": "job.batch",
        "restart_helper": "check_restart.py",
        "tools": DEMO_TOOLS,
        "job_types": DEMO_JOB_TYPES,
        "artifact_sync": {"receipts": "hpckit/receipts"},
        "slurm": {"account": "demo@cpu", "partition": "prepost"},
    }
    data.update(extra)
    (tmp_path / ".hpckit.yaml").write_text(yaml.safe_dump(data))


def _cfg(tmp_path, **kwargs):
    import hpckit.cli as cli

    base = dict(
        root=tmp_path,
        project="Demo",
        remote="mycluster",
        work_root="/work/demo",
        scratch_root=None,
        remote_repos_root="/work/demo/repos",
        remote_state_root="/work/demo/.hpckit",
        ledger=tmp_path / "L",
        artifact_sync={},
        job_script="job.batch",
        restart_helper="check_restart.py",
        tools=DEMO_TOOLS,
        job_types=DEMO_JOB_TYPES,
    )
    base.update(kwargs)
    return cli.Config(**base)


def test_case_slug_replaces_slashes() -> None:
    assert case_slug("mycase/340") == "mycase_340"


def test_case_slug_strips_shell_metacharacters() -> None:
    """A case name reaches a remote shell, so it must not carry metacharacters.

    run_id() embeds case_slug() output, and run_id becomes an rsync remote path
    (`host:path`, which rsync hands to a shell on the far side) and a Slurm
    --job-name. short_ref() already reduces the git ref to [A-Za-z0-9]; the case
    was left unfiltered, so `;`, `$(...)`, quotes and spaces survived the whole
    way to the cluster.
    """
    assert case_slug("x;touch /tmp/pwned") == "x_touch__tmp_pwned"
    assert case_slug("a$(id)b") == "a__id_b"
    assert case_slug("my case") == "my_case"
    assert case_slug("q'uote") == "q_uote"
    # ordinary names keep the characters that make them readable
    assert case_slug("mycase/340") == "mycase_340"
    assert case_slug("cube-281_v2.1") == "cube-281_v2.1"


def test_run_id_contains_only_safe_path_characters() -> None:
    rid = run_id("process", "x;touch /tmp/p", "feature/foo")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", rid), rid


def test_short_ref_sanitizes_and_truncates() -> None:
    assert short_ref("feature/foo-abcdef123") == "feature"
    assert short_ref("!!!") == "unknown"


def test_run_id_shape() -> None:
    rid = run_id("process", "mycase/340", "abcdef123")
    assert rid.endswith("-process-mycase_340-abcdef1")


def test_parser_has_expected_commands(tmp_path, monkeypatch) -> None:
    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["submit", "process", "mycase/340", "--ref", "abcdef1", "--manual"])
    assert args.workflow == "process"
    assert args.case == "mycase/340"
    assert args.ref == "abcdef1"
    assert args.manual is True


def test_init_requires_work_root(tmp_path, monkeypatch, capsys) -> None:
    # There is no portable default for a cluster's work filesystem, so init
    # must refuse rather than invent one.
    monkeypatch.chdir(tmp_path)
    from hpckit.cli import main

    rc = main(["init"])
    assert rc == 1
    assert not (tmp_path / ".hpckit.yaml").exists()
    assert "--work-root is required" in capsys.readouterr().err


def test_init_writes_config_with_work_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from hpckit.cli import main

    rc = main(["init", "--work-root", "/scratch/proj"])
    assert rc == 0
    cfg_path = tmp_path / ".hpckit.yaml"
    assert cfg_path.exists()
    data = yaml.safe_load(cfg_path.read_text())
    assert data["project"] == tmp_path.name
    assert data["remote"] == "mycluster"
    assert data["work_root"] == "/scratch/proj"
    assert data["remote_repos_root"] == "/scratch/proj/repos"
    assert data["remote_state_root"] == "/scratch/proj/.hpckit"
    assert data["artifact_sync"]["receipts"] == "hpckit/receipts"
    assert data["job_script"] == "job.batch"
    assert data["restart_helper"] == "check_restart.py"
    assert data["tools"] == {}
    assert data["job_types"] == {}
    assert (tmp_path / "hpckit" / "receipts").is_dir()
    assert (tmp_path / ".hpckit").is_dir()


def test_init_refuses_overwrite_without_force(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / ".hpckit.yaml"
    cfg_path.write_text("project: sentinel\n")
    from hpckit.cli import main

    rc = main(["init"])
    assert rc != 0
    assert cfg_path.read_text() == "project: sentinel\n"


def test_init_force_overwrites(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / ".hpckit.yaml"
    cfg_path.write_text("project: garbage\n")
    from hpckit.cli import main

    rc = main(["init", "--force", "--work-root", "/scratch/proj"])
    assert rc == 0
    data = yaml.safe_load(cfg_path.read_text())
    assert data["project"] == tmp_path.name
    assert data["work_root"] == "/scratch/proj"


def test_init_subcommand_in_parser() -> None:
    parser = build_parser()
    args = parser.parse_args(["init", "--project", "myproject", "--force"])
    assert args.project == "myproject"
    assert args.force is True


def test_load_config_anchors_project_paths_to_config_parent(tmp_path, monkeypatch) -> None:
    from hpckit.cli import build_packet, load_config, local_receipt_dir

    _write_cfg(tmp_path)
    subdir = tmp_path / "nested" / "dir"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)

    cfg = load_config()
    assert cfg.root == tmp_path
    assert local_receipt_dir(cfg) == tmp_path / "hpckit" / "receipts"

    packet = build_packet(cfg, "rid", "process", "case/1", {}, {})
    assert packet == tmp_path / ".hpckit" / "runs" / "rid"
    assert not (subdir / ".hpckit").exists()


def test_publish_receipt_creates_temp_dir_from_fresh_project(tmp_path, monkeypatch) -> None:
    import subprocess
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    calls = []

    def fake_run(cmd, *, check=True, cwd=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    cli.publish_receipt(cfg, {"run_id": "rid", "status": "submitted"})

    assert (tmp_path / ".hpckit" / "rid.receipt.json").exists()
    assert (tmp_path / "hpckit" / "receipts" / "rid.json").exists()
    assert calls and calls[0][0] == "scp"


def test_sparse_subparser_accepts_dry_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["submit", "sparse", "cube_7/282", "--to", "5000", "--dry-run"])
    assert args.dry_run is True
    assert args.to == 5000.0


def test_submit_sparse_dry_run_skips_mutation_and_sbatch(monkeypatch, tmp_path) -> None:
    """Dry-run sparse must not mutate the restart helper or call sbatch — only
    parse and report. The fake ssh records the script it received so we can
    assert no sbatch / write-back text leaks into a dry-run probe.
    """
    import subprocess
    import hpckit.cli as cli

    cfg = _cfg(tmp_path)
    captured = {}

    def fake_ssh(_cfg, script, *, check=True):
        captured["script"] = script
        return subprocess.CompletedProcess(
            ["ssh"],
            0,
            "HPCKIT_PROBE 10000 1000 5600 check_restart.py.preXXX_TS\n",
            "",
        )

    monkeypatch.setattr(cli, "ssh", fake_ssh)

    args = build_parser().parse_args(["submit", "sparse", "cube_7/282", "--to", "5500", "--dry-run"])
    assert cli.submit_sparse(cfg, args) == 0
    sent = captured["script"]
    assert "old_target=" in sent
    assert "HPCKIT_PROBE" in sent
    assert "cp check_restart.py" not in sent
    assert "sbatch job.batch" not in sent
    assert "p.write_text(s)" not in sent
    # Config-driven names appear in the probe.
    assert "job.batch" in sent
    assert "check_restart.py" in sent


def test_submit_sparse_requires_job_script(monkeypatch, tmp_path) -> None:
    import pytest
    import hpckit.cli as cli

    cfg = _cfg(tmp_path, job_script=None)
    args = build_parser().parse_args(["submit", "sparse", "cube_7/282", "--to", "5500", "--dry-run"])
    with pytest.raises(SystemExit, match="job_script not configured"):
        cli.submit_sparse(cfg, args)


def test_probe_par_endtime_regex_is_case_insensitive(monkeypatch, tmp_path) -> None:
    """Legacy .par files use lowercase 'endtime = 15000.0'; newer cases use
    camelCase 'endTime = 14400.0'. The probe regex must match both.
    """
    import re
    import inspect
    import hpckit.cli as cli

    pattern = re.compile(r"endTime\s*=\s*([0-9.eE+-]+)", re.IGNORECASE)
    assert pattern.search("endTime = 14400.0") is not None
    assert pattern.search("endtime = 15000.0") is not None
    assert pattern.search("EndTime = 9999.9") is not None
    assert pattern.search("endTimes = 1.0") is None or pattern.search("endTimes = 1.0").group(1) == "1.0"
    src = inspect.getsource(cli)
    assert "endTime" in src and "re.IGNORECASE" in src, (
        "probe regex must use re.IGNORECASE to handle lowercase 'endtime' .par"
    )


def test_submit_sparse_dry_run_handles_empty_par_end(monkeypatch, tmp_path) -> None:
    """At-target cases have no `endTime` line in .par, so the probe emits `-`
    as the par_end sentinel. The parser must accept this without raising
    'expected 5, got 4'.
    """
    import subprocess
    import hpckit.cli as cli

    cfg = _cfg(tmp_path)

    def fake_ssh(_cfg, _script, *, check=True):
        return subprocess.CompletedProcess(
            ["ssh"],
            0,
            "HPCKIT_PROBE 5000 1000 - check_restart.py.pre5000_TS\n",
            "",
        )

    monkeypatch.setattr(cli, "ssh", fake_ssh)
    args = build_parser().parse_args(["submit", "sparse", "sphere_5/450", "--to", "5000", "--dry-run"])
    assert cli.submit_sparse(cfg, args) == 0


def test_submit_sparse_uses_python_boolean_literals(monkeypatch, tmp_path) -> None:
    import subprocess
    import hpckit.cli as cli

    cfg = _cfg(tmp_path, ledger=tmp_path / "HPCKIT_RUN_LOG.md")
    captured = {}

    def fake_ssh(_cfg, script, *, check=True):
        captured["script"] = script
        return subprocess.CompletedProcess(["ssh"], 0, "123 backup 10 2\n", "")

    monkeypatch.setattr(cli, "ssh", fake_ssh)
    monkeypatch.setattr(cli, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))

    args = build_parser().parse_args(["submit", "sparse", "case/1", "--to", "20", "--force-reconcile"])
    assert cli.submit_sparse(cfg, args) == 0
    assert "force=True" in captured["script"].replace(" ", "")
    assert "force=true" not in captured["script"]
    assert "sbatch job.batch" in captured["script"] or "sbatch 'job.batch'" in captured["script"]


def test_build_packet_uses_slurm_settings_from_config(tmp_path, monkeypatch) -> None:
    """Slurm account and partition are site-specific, so they come from config.

    They were hardcoded to one IDRIS allocation and one Jean Zay partition,
    which made the README's "configuration lives in the project you run it
    from" untrue and left the tool unusable elsewhere without a source edit.
    """
    import hpckit.cli as cli

    _write_cfg(
        tmp_path,
        slurm={"account": "abc@gpu", "partition": "compute", "ntasks": 2, "cpus_per_task": 8},
    )
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid42", "process", "mycase/340", {"sigtool": "abc1234"}, {})

    sbatch = (packet / "job.sbatch").read_text()
    assert "#SBATCH --account=abc@gpu" in sbatch
    assert "#SBATCH --partition=compute" in sbatch
    assert "#SBATCH --ntasks=2" in sbatch
    assert "#SBATCH --cpus-per-task=8" in sbatch
    # exactly one account directive, and it is the configured one — guards
    # against a hardcoded default being emitted alongside it
    assert sbatch.count("#SBATCH --account=") == 1
    assert "prepost" not in sbatch  # the old hardcoded partition must not leak


def test_build_packet_requires_a_slurm_account(tmp_path, monkeypatch) -> None:
    """No default account: like work_root, there is no sane value to invent."""
    import pytest

    import hpckit.cli as cli

    _write_cfg(tmp_path, slurm={})  # explicitly no slurm settings
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    with pytest.raises(SystemExit) as excinfo:
        cli.build_packet(cfg, "rid42", "process", "mycase/340", {"sigtool": "abc1234"}, {})
    assert "slurm.account" in str(excinfo.value)


def test_build_packet_process_emits_sbatch_calling_venv(tmp_path, monkeypatch) -> None:
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid42", "process", "mycase/340", {"sigtool": "abc1234"}, {})

    sbatch = (packet / "job.sbatch").read_text()
    assert "#SBATCH --job-name=rid42" in sbatch
    assert "#SBATCH --account=demo@cpu" in sbatch
    assert "#SBATCH --partition=prepost" in sbatch
    assert "/work/demo/.venv/bin/python" in sbatch
    assert "sigtool.cli process" in sbatch
    assert "/work/demo/.hpckit/runs/rid42/registry.toml" in sbatch
    assert "/work/demo/.hpckit/outputs/processed/rid42" in sbatch

    registry = (packet / "registry.toml").read_text()
    assert "[defaults]" in registry
    assert 'input_root = "/work/demo"' in registry
    assert "[cases.mycase_340]" in registry
    assert 'input_path = "mycase/340"' in registry
    assert 'signal_files = ["lift_drag.all"]' in registry


def test_build_packet_process_uses_user_registry(tmp_path, monkeypatch) -> None:
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    user_reg = tmp_path / "custom_registry.toml"
    user_reg.write_text('[cases.custom]\ninput_path = "custom/path"\n')

    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid", "process", "custom/path", {}, {"registry": str(user_reg)})
    assert (packet / "registry.toml").read_text() == user_reg.read_text()


def test_build_packet_render_emits_tool_call(tmp_path, monkeypatch) -> None:
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    packet = cli.build_packet(
        cfg, "rid", "render", "mycase/340", {"snaptool": "abc"}, {"pattern": "*0.f0*"}
    )
    sbatch = (packet / "job.sbatch").read_text()
    assert "/work/demo/.venv/bin/snaptool" in sbatch
    assert "render-many" in sbatch
    assert "--case-dir /work/demo/mycase/340" in sbatch
    assert "--pattern '*0.f0*'" in sbatch
    assert "/work/demo/.hpckit/outputs/renders/rid" in sbatch


def test_build_packet_plot_emits_tool_call(tmp_path, monkeypatch) -> None:
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid", "plot", "fig9", {"sigtool": "abc"}, {"kind": "fig9"})
    sbatch = (packet / "job.sbatch").read_text()
    assert "/work/demo/.venv/bin/python" in sbatch
    assert "sigtool.cli plot" in sbatch
    assert "--kind fig9" in sbatch
    assert "/work/demo/.hpckit/outputs/figures/rid" in sbatch


def test_plot_subparser_accepts_kind(tmp_path, monkeypatch) -> None:
    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["submit", "plot", "fig9", "--ref", "abc", "--manual"])
    assert args.workflow == "plot"
    assert args.kind == "fig9"
    assert args.ref == "abc"


def test_ssh_lstrips_and_quotes_script(tmp_path, monkeypatch) -> None:
    """ssh joins argv[2:] with spaces, so the script must be passed as a
    single shlex-quoted argument or only the first token reaches the inner
    bash -lc and the rest leak into the outer login shell.
    """
    import subprocess
    import hpckit.cli as cli

    cfg = _cfg(tmp_path, project="x", work_root="/w", remote_repos_root="/r", remote_state_root="/s")
    captured = {}

    def fake_run(cmd, *, check=True, cwd=None):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    cli.ssh(cfg, "\n\n  set -e\nmkdir -p /tmp/X && echo done\n")

    assert captured["cmd"][:2] == ["ssh", "mycluster"], captured["cmd"]
    remote = captured["cmd"][2]
    assert remote.startswith("bash -lc "), remote
    assert "lstrip" not in remote
    assert remote.startswith("bash -lc 'set -e")
    assert remote.endswith("'") and remote.count("'") >= 2
    assert "mkdir -p /tmp/X && echo done" in remote


def test_render_subparser_accepts_pattern(tmp_path, monkeypatch) -> None:
    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    args = parser.parse_args(
        [
            "submit",
            "render",
            "mycase/340",
            "--ref",
            "abc",
            "--pattern",
            "sphere0.f000*",
            "--manual",
        ]
    )
    assert args.pattern == "sphere0.f000*"


def test_process_subparser_accepts_registry(tmp_path, monkeypatch) -> None:
    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    args = parser.parse_args(
        [
            "submit",
            "process",
            "mycase/340",
            "--ref",
            "abc",
            "--registry",
            "case_registries/sphere.toml",
            "--manual",
        ]
    )
    assert args.registry == "case_registries/sphere.toml"


def test_rsync_protects_remote_paths_from_the_remote_shell(tmp_path, monkeypatch) -> None:
    """rsync must be told not to let a shell expand the remote path.

    Unlike ssh, where the whole script is shlex.quote'd into one argument,
    `rsync host:path` hands `path` to a shell on the far side. A space splits it
    into two source arguments and metacharacters are interpreted. `-s`
    (--secluded-args) sends the path over the protocol instead. run_id is
    sanitised too, but remote_state_root comes straight from user config, so
    this is the backstop rather than the only defence.
    """
    import subprocess

    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    calls = []

    def fake_run(cmd, *, check=True, cwd=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "ssh", lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""))

    packet = tmp_path / "packet"
    packet.mkdir()
    cli.upload_packet(cfg, "rid42", packet)

    rsync_calls = [c for c in calls if c and c[0] == "rsync"]
    assert rsync_calls, calls
    for cmd in rsync_calls:
        assert "-s" in cmd, cmd


def test_sync_artifacts_fails_closed_when_rsync_fails(tmp_path, monkeypatch) -> None:
    import subprocess
    import pytest
    import hpckit.cli as cli

    _write_cfg(
        tmp_path,
        artifact_sync={"processed": "data/processed", "receipts": "receipts"},
    )
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    receipt_dir.joinpath("rid.json").write_text(
        '{"run_id":"rid","workflow":"process","remote_output_path":"/remote/missing","status":"submitted"}'
    )
    monkeypatch.chdir(tmp_path)

    def fake_run(cmd, *, check=True, cwd=None):
        return subprocess.CompletedProcess(cmd, 23, "", "missing\n")

    monkeypatch.setattr(cli, "run", fake_run)
    args = build_parser().parse_args(["sync-artifacts", "rid"])
    with pytest.raises(SystemExit):
        cli.cmd_sync_artifacts(args)

    data = yaml.safe_load(receipt_dir.joinpath("rid.json").read_text())
    assert data["status"] == "submitted"


def test_update_repo_rejects_unknown_tool(tmp_path, monkeypatch) -> None:
    import pytest
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["update-repo", "not_a_tool", "--ref", "main"])
    with pytest.raises(SystemExit, match="unknown tool"):
        cli.cmd_update_repo(args)


def test_update_repo_requires_repo_url_in_config(tmp_path, monkeypatch) -> None:
    import pytest
    import hpckit.cli as cli

    _write_cfg(tmp_path, tools={"orphan": {}})
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["update-repo", "orphan", "--ref", "main"])
    with pytest.raises(SystemExit, match="tools.orphan.repo_url"):
        cli.cmd_update_repo(args)


def test_expand_command_rejects_unknown_placeholder() -> None:
    import pytest
    import hpckit.cli as cli

    with pytest.raises(SystemExit, match="unknown placeholder"):
        cli.expand_command("{venv}/bin/x --out {missing}", {"venv": "/v"})


def test_output_kind_from_job_type(tmp_path) -> None:
    import hpckit.cli as cli

    cfg = _cfg(tmp_path)
    assert cli.output_kind(cfg, "render") == "renders"
    assert cli.output_kind(cfg, "plot") == "figures"
    assert cli.output_kind(cfg, "process") == "processed"
    assert cli.output_kind(cfg, "sparse") == "processed"


def test_load_config_reads_tools_and_job_script(tmp_path, monkeypatch) -> None:
    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    assert cfg.job_script == "job.batch"
    assert cfg.restart_helper == "check_restart.py"
    assert "sigtool" in cfg.tools
    assert cfg.job_types["render"]["tool"] == "snaptool"


# --- cmd_submit: the primary command, previously exercised only via sparse ----


def _submit_harness(tmp_path, monkeypatch, sbatch_stdout="Submitted batch job 98765\n"):
    """Stub every outbound call so cmd_submit can run end to end offline.

    Returns (cli, calls, ssh_scripts) so a test can assert on what would have
    been executed rather than on internals.
    """
    import subprocess

    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)

    calls: list[list[str]] = []
    ssh_scripts: list[str] = []

    def fake_run(cmd, *, check=True, cwd=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_ssh(cfg, script, *, check=True):
        ssh_scripts.append(script)
        return subprocess.CompletedProcess(["ssh"], 0, sbatch_stdout, "")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "ssh", fake_ssh)
    return cli, calls, ssh_scripts


def test_submit_rejects_an_unknown_job_type(tmp_path, monkeypatch) -> None:
    import argparse

    import pytest

    cli, _, _ = _submit_harness(tmp_path, monkeypatch)
    args = argparse.Namespace(workflow="nosuchthing", case="c/1", ref="abc1234", manual=True)
    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_submit(args)
    msg = str(excinfo.value)
    assert "unknown job type nosuchthing" in msg
    # the message must name what IS available, or the user has to read the source
    assert "process" in msg


def test_submit_manual_prepares_without_calling_sbatch(tmp_path, monkeypatch, capsys) -> None:
    """--manual is the escape hatch: stage everything, submit nothing."""
    import argparse
    import json

    cli, _, ssh_scripts = _submit_harness(tmp_path, monkeypatch)
    args = argparse.Namespace(workflow="process", case="mycase/340", ref="abc1234", manual=True)
    rc = cli.cmd_submit(args)
    assert rc == 0

    rid = capsys.readouterr().out.strip()
    assert rid.endswith("-process-mycase_340-abc1234")
    assert not any("sbatch" in s for s in ssh_scripts), ssh_scripts

    receipt = json.loads((tmp_path / "hpckit" / "receipts" / f"{rid}.json").read_text())
    assert receipt["status"] == "prepared"
    assert receipt["job_id"] is None
    assert receipt["submitted_at"] is None


def test_submit_records_the_slurm_job_id_from_sbatch_output(tmp_path, monkeypatch, capsys) -> None:
    import argparse
    import json

    cli, _, ssh_scripts = _submit_harness(tmp_path, monkeypatch)
    args = argparse.Namespace(workflow="process", case="mycase/340", ref="abc1234", manual=False)
    assert cli.cmd_submit(args) == 0

    rid = capsys.readouterr().out.strip()
    assert any("sbatch job.sbatch" in s for s in ssh_scripts), ssh_scripts

    receipt = json.loads((tmp_path / "hpckit" / "receipts" / f"{rid}.json").read_text())
    assert receipt["job_id"] == "98765"
    assert receipt["status"] == "submitted"
    assert receipt["submitted_at"] is not None


def test_submit_falls_back_to_raw_output_when_sbatch_is_unparseable(tmp_path, monkeypatch, capsys) -> None:
    """A changed sbatch banner must not silently produce job_id=None."""
    import argparse
    import json

    cli, _, _ = _submit_harness(tmp_path, monkeypatch, sbatch_stdout="queued as 4242\n")
    args = argparse.Namespace(workflow="process", case="c1", ref="abc1234", manual=False)
    assert cli.cmd_submit(args) == 0
    rid = capsys.readouterr().out.strip()

    receipt = json.loads((tmp_path / "hpckit" / "receipts" / f"{rid}.json").read_text())
    assert receipt["job_id"] == "queued as 4242"
    assert receipt["status"] == "submitted"


def test_submit_mirrors_kind_onto_case_for_plot_workflows(tmp_path, monkeypatch, capsys) -> None:
    """plot takes --kind, not a case, but the run_id layout must stay uniform."""
    import argparse
    import json

    cli, _, _ = _submit_harness(tmp_path, monkeypatch)
    args = argparse.Namespace(workflow="plot", case=None, kind="spectra", ref="abc1234", manual=True)
    assert cli.cmd_submit(args) == 0
    rid = capsys.readouterr().out.strip()
    assert rid.endswith("-plot-spectra-abc1234")

    receipt = json.loads((tmp_path / "hpckit" / "receipts" / f"{rid}.json").read_text())
    assert receipt["case"] == "spectra"
    # plot declares output_kind: figures, so the output path must follow it
    assert "/outputs/figures/" in receipt["remote_output_path"]


def test_read_receipt_falls_back_to_the_cluster_when_absent_locally(tmp_path, monkeypatch) -> None:
    """Receipts live on the cluster too; a fresh checkout must still resolve one."""
    import json
    import subprocess

    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()

    remote_receipt = {"run_id": "rid7", "status": "submitted"}
    seen: list[str] = []

    def fake_ssh(_cfg, script, *, check=True):
        seen.append(script)
        return subprocess.CompletedProcess(["ssh"], 0, json.dumps(remote_receipt), "")

    monkeypatch.setattr(cli, "ssh", fake_ssh)
    assert cli.read_receipt(cfg, "rid7") == remote_receipt
    assert seen and "receipts/rid7.json" in seen[0]


def test_read_receipt_raises_when_neither_side_has_it(tmp_path, monkeypatch) -> None:
    import subprocess

    import pytest

    import hpckit.cli as cli

    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    monkeypatch.setattr(
        cli, "ssh", lambda *a, **k: subprocess.CompletedProcess(["ssh"], 1, "", "no such file")
    )
    with pytest.raises(SystemExit, match="receipt not found: nope"):
        cli.read_receipt(cfg, "nope")
