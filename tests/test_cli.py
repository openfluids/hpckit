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
