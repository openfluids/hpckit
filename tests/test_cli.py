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
