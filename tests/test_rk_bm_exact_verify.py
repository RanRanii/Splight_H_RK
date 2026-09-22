from pathlib import Path

from tools.rk_bm_exact_verify import (
    load_boomerang_input_from_result_dir,
    verify_boomerang,
    verify_boomerang_result_dir,
    write_verification_artifacts,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_four_data_boomerang_sat_and_replay_pass(tmp_path):
    """A closed four-data instance is accepted and concretely replayed."""
    result = verify_boomerang(
        r0=1,
        rm=1,
        r1=1,
        upper_fixed_diffs={
            "dK": "0" * 32,
            "dX0": "0000000000000001",
        },
        lower_fixed_diffs={
            "dK": "0" * 32,
            "dX0": "0" * 16,
            "dX1": "0" * 16,
        },
        timeout_ms=30_000,
    )

    assert result["status"] == "SAT"
    assert result["witness"]["concrete_replay"] == "PASS"
    relations = result["witness"]["relationships"]
    assert relations["delta_input"] == relations["delta_input_closure"]
    assert relations["nabla_output"] == relations["nabla_output_closure"]
    artifacts = write_verification_artifacts(result, tmp_path / "bm_exact_verify")
    assert Path(artifacts["witness_json"]).is_file()


def test_inconsistent_lower_boundary_is_unsat():
    """Equal lower inputs and keys cannot evolve to a non-zero output difference."""
    result = verify_boomerang(
        r0=1,
        rm=1,
        r1=1,
        upper_fixed_diffs={
            "dK": "0" * 32,
            "dX0": "0000000000000001",
        },
        lower_fixed_diffs={
            "dK": "0" * 32,
            "dX0": "0" * 16,
            "dX1": "0000000000000001",
        },
        timeout_ms=30_000,
    )

    assert result["status"] == "UNSAT"


def test_result_directory_loader_uses_common_accepted_path():
    loaded = load_boomerang_input_from_result_dir(
        PROJECT_DIR / "results" / "2-3-2_636"
    )

    assert loaded["truncated_id"] == 1
    assert loaded["parameters"] == {"r0": 2, "rm": 3, "r1": 2}
    assert "dK" in loaded["upper_fixed_diffs"]
    assert "dK" in loaded["lower_fixed_diffs"]
    assert "middle_part" in loaded["truncated_path"]


def test_result_directory_writes_boomerang_verification_artifacts(tmp_path):
    result = verify_boomerang_result_dir(
        PROJECT_DIR / "results" / "2-3-2_636",
        timeout_ms=30_000,
        output_dir=tmp_path / "bm_exact_verify",
    )

    assert result["status"] == "UNSAT"
    assert result["support_constraint_count"] > 0
    assert Path(result["artifacts"]["summary_json"]).is_file()
    assert Path(result["artifacts"]["witness_markdown"]).is_file()
    assert Path(result["artifacts"]["terminal_print"]).is_file()
