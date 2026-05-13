from __future__ import annotations

import yaml

from jz_pilot.cli import build_parser, case_slug, run_id, short_ref


def test_case_slug_replaces_slashes() -> None:
    assert case_slug("mycase/340") == "mycase_340"


def test_short_ref_sanitizes_and_truncates() -> None:
    assert short_ref("feature/foo-abcdef123") == "feature"
    assert short_ref("!!!") == "unknown"


def test_run_id_shape() -> None:
    rid = run_id("process", "mycase/340", "abcdef123")
    assert rid.endswith("-process-mycase_340-abcdef1")


def test_parser_has_expected_commands() -> None:
    parser = build_parser()
    args = parser.parse_args(["submit", "process", "mycase/340", "--spipe-ref", "abcdef1", "--manual"])
    assert args.workflow == "process"
    assert args.case == "mycase/340"
    assert args.spipe_ref == "abcdef1"
    assert args.manual is True


def test_init_writes_config_with_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from jz_pilot.cli import main
    rc = main(["init"])
    assert rc == 0
    cfg_path = tmp_path / ".jz-manager.yaml"
    assert cfg_path.exists()
    data = yaml.safe_load(cfg_path.read_text())
    assert data["project"] == tmp_path.name
    assert data["remote"] == "jz"
    assert data["work_root"].startswith("/path/to/work")
    assert data["artifact_sync"]["receipts"] == "jz_manager/receipts"
    assert (tmp_path / "jz_manager" / "receipts").is_dir()
    assert (tmp_path / ".jz-manager").is_dir()


def test_init_refuses_overwrite_without_force(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text("project: sentinel\n")
    from jz_pilot.cli import main
    rc = main(["init"])
    assert rc != 0
    assert cfg_path.read_text() == "project: sentinel\n"


def test_init_force_overwrites(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text("project: garbage\n")
    from jz_pilot.cli import main
    rc = main(["init", "--force"])
    assert rc == 0
    data = yaml.safe_load(cfg_path.read_text())
    assert data["project"] == tmp_path.name
    assert "work_root" in data


def test_init_subcommand_in_parser() -> None:
    from jz_pilot.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["init", "--project", "myproject", "--force"])
    assert args.project == "myproject"
    assert args.force is True


def test_load_config_anchors_project_paths_to_config_parent(tmp_path, monkeypatch) -> None:
    from jz_pilot.cli import build_packet, load_config, local_receipt_dir

    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "remote": "jz",
                "work_root": "/work/demo",
                "artifact_sync": {"receipts": "jz_manager/receipts"},
            }
        )
    )
    subdir = tmp_path / "nested" / "dir"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)

    cfg = load_config()
    assert cfg.root == tmp_path
    assert local_receipt_dir(cfg) == tmp_path / "jz_manager" / "receipts"

    packet = build_packet(cfg, "rid", "process", "case/1", {}, {})
    assert packet == tmp_path / ".jz-manager" / "runs" / "rid"
    assert not (subdir / ".jz-manager").exists()


def test_publish_receipt_creates_temp_dir_from_fresh_project(tmp_path, monkeypatch) -> None:
    import subprocess
    import jz_pilot.cli as cli

    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "remote": "jz",
                "work_root": "/work/demo",
                "remote_state_root": "/work/demo/.jz-manager",
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    calls = []

    def fake_run(cmd, *, check=True, cwd=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    cli.publish_receipt(cfg, {"run_id": "rid", "status": "submitted"})

    assert (tmp_path / ".jz-manager" / "rid.receipt.json").exists()
    assert (tmp_path / "jz_manager" / "receipts" / "rid.json").exists()
    assert calls and calls[0][0] == "scp"


def test_sparse_subparser_accepts_dry_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["submit", "sparse", "cube_7/282", "--to", "5000", "--dry-run"])
    assert args.dry_run is True
    assert args.to == 5000.0


def test_submit_sparse_dry_run_skips_mutation_and_sbatch(monkeypatch, tmp_path) -> None:
    """Dry-run sparse must not mutate check_restart.py or call sbatch — only
    parse and report. The fake ssh records the script it received so we can
    assert no sbatch / sed-replace text leaks into a dry-run probe.
    """
    import subprocess
    import jz_pilot.cli as cli

    cfg = cli.Config(
        root=tmp_path, project="Demo", remote="jz", work_root="/work/demo",
        scratch_root=None, remote_repos_root="/work/demo/repos",
        remote_state_root="/work/demo/.jz-manager", ledger=tmp_path / "L",
        artifact_sync={},
    )
    captured = {}

    def fake_ssh(_cfg, script, *, check=True):
        captured["script"] = script
        # Simulate the probe printing the JZP_PROBE sentinel line
        return subprocess.CompletedProcess(
            ["ssh"], 0,
            "JZP_PROBE 10000 1000 5600 check_restart.py.preXXX_TS\n",
            "",
        )

    monkeypatch.setattr(cli, "ssh", fake_ssh)

    args = build_parser().parse_args(["submit", "sparse", "cube_7/282", "--to", "5500", "--dry-run"])
    assert cli.submit_sparse(cfg, args) == 0
    sent = captured["script"]
    # Dry-run script should contain probes...
    assert "old_target=" in sent
    assert "JZP_PROBE" in sent
    # ...but NEVER the mutation step or sbatch
    assert "cp check_restart.py" not in sent
    assert "sbatch jz.pbs" not in sent
    assert "p.write_text(s)" not in sent


def test_submit_sparse_uses_python_boolean_literals(monkeypatch, tmp_path) -> None:
    import subprocess
    import jz_pilot.cli as cli

    cfg = cli.Config(
        root=tmp_path,
        project="Demo",
        remote="jz",
        work_root="/work/demo",
        scratch_root=None,
        remote_repos_root="/work/demo/repos",
        remote_state_root="/work/demo/.jz-manager",
        ledger=tmp_path / "JZ_RUN_LOG.md",
        artifact_sync={},
    )
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


def test_build_packet_process_emits_sbatch_calling_venv(tmp_path, monkeypatch) -> None:
    import jz_pilot.cli as cli
    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "remote": "jz",
                "work_root": "/work/demo",
                "remote_state_root": "/work/demo/.jz-manager",
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid42", "process", "mycase/340", {"spipe": "abc1234"}, {})

    sbatch = (packet / "job.sbatch").read_text()
    assert "#SBATCH --job-name=rid42" in sbatch
    assert "#SBATCH --account=vpo@cpu" in sbatch
    assert "#SBATCH --partition=prepost" in sbatch
    assert "/work/demo/.venv/bin/python" in sbatch
    assert "spipe.cli process" in sbatch
    assert "/work/demo/.jz-manager/runs/rid42/registry.toml" in sbatch
    assert "/work/demo/.jz-manager/outputs/processed/rid42" in sbatch

    registry = (packet / "registry.toml").read_text()
    assert '[defaults]' in registry
    assert 'input_root = "/work/demo"' in registry
    assert '[cases.mycase_340]' in registry
    assert 'input_path = "mycase/340"' in registry
    assert 'signal_files = ["lift_drag.all"]' in registry


def test_build_packet_process_uses_user_registry(tmp_path, monkeypatch) -> None:
    import jz_pilot.cli as cli
    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"project": "Demo", "remote": "jz", "work_root": "/work/demo"}
        )
    )
    monkeypatch.chdir(tmp_path)
    user_reg = tmp_path / "custom_registry.toml"
    user_reg.write_text('[cases.custom]\ninput_path = "custom/path"\n')

    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid", "process", "custom/path", {}, {"registry": str(user_reg)})
    assert (packet / "registry.toml").read_text() == user_reg.read_text()


def test_build_packet_render_emits_neksnap_call(tmp_path, monkeypatch) -> None:
    import jz_pilot.cli as cli
    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "remote": "jz",
                "work_root": "/work/demo",
                "remote_state_root": "/work/demo/.jz-manager",
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    cfg = cli.load_config()
    packet = cli.build_packet(cfg, "rid", "render", "mycase/340", {"neksnap": "abc"}, {"pattern": "*0.f0*"})
    sbatch = (packet / "job.sbatch").read_text()
    assert "/work/demo/.venv/bin/neksnap" in sbatch
    assert "render-many" in sbatch
    assert "--case-dir /work/demo/mycase/340" in sbatch
    assert "--pattern '*0.f0*'" in sbatch  # asterisks force shlex.quote to wrap in single quotes
    assert "/work/demo/.jz-manager/outputs/renders/rid" in sbatch


def test_ssh_lstrips_and_quotes_script(tmp_path, monkeypatch) -> None:
    """ssh joins argv[2:] with spaces, so the script must be passed as a
    single shlex-quoted argument or only the first token reaches the inner
    bash -lc and the rest leak into the outer login shell.
    """
    import subprocess
    import jz_pilot.cli as cli
    cfg = cli.Config(
        root=tmp_path, project="x", remote="jz", work_root="/w", scratch_root=None,
        remote_repos_root="/r", remote_state_root="/s", ledger=tmp_path / "L",
        artifact_sync={},
    )
    captured = {}

    def fake_run(cmd, *, check=True, cwd=None):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    cli.ssh(cfg, "\n\n  set -e\nmkdir -p /tmp/X && echo done\n")

    # cmd is exactly: ['ssh', 'jz', "bash -lc '<quoted script>'"]
    assert captured["cmd"][:2] == ["ssh", "jz"], captured["cmd"]
    remote = captured["cmd"][2]
    assert remote.startswith("bash -lc "), remote
    # The leading whitespace/newlines must be stripped
    assert "lstrip" not in remote  # sanity: nothing weird in the string
    assert remote.startswith("bash -lc 'set -e")
    # The whole script must be inside a single quoted blob
    assert remote.endswith("'") and remote.count("'") >= 2
    # The script body must survive intact (mkdir command not split)
    assert "mkdir -p /tmp/X && echo done" in remote


def test_render_subparser_accepts_pattern() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "submit", "render", "mycase/340",
        "--neksnap-ref", "abc",
        "--pattern", "sphere0.f000*",
        "--manual",
    ])
    assert args.pattern == "sphere0.f000*"


def test_process_subparser_accepts_registry() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "submit", "process", "mycase/340",
        "--spipe-ref", "abc",
        "--registry", "case_registries/sphere.toml",
        "--manual",
    ])
    assert args.registry == "case_registries/sphere.toml"


def test_sync_artifacts_fails_closed_when_rsync_fails(tmp_path, monkeypatch) -> None:
    import subprocess
    import pytest
    import jz_pilot.cli as cli

    cfg_path = tmp_path / ".jz-manager.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "remote": "jz",
                "work_root": "/work/demo",
                "remote_state_root": "/work/demo/.jz-manager",
                "artifact_sync": {"processed": "data/processed", "receipts": "receipts"},
            }
        )
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
