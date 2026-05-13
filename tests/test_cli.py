from __future__ import annotations

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
