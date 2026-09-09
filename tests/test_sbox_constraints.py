import math

from splight.sbox_constraints import compute_ddt, ddt_support_points, ddt_weight, weight_table
from splight.splight_spec import SBOX_SPLIGHT_S3


def test_sbox_is_permutation_and_ddt_rows_sum_to_16():
    assert sorted(SBOX_SPLIGHT_S3) == list(range(16))
    ddt = compute_ddt(SBOX_SPLIGHT_S3)
    assert all(sum(row) == 16 for row in ddt)
    assert ddt[0][0] == 16
    assert all(ddt[0][dy] == 0 for dy in range(1, 16))


def test_support_points_match_nonzero_ddt():
    ddt = compute_ddt(SBOX_SPLIGHT_S3)
    points = ddt_support_points(SBOX_SPLIGHT_S3)
    assert len(points) == sum(1 for dx in range(16) for dy in range(16) if ddt[dx][dy])
    assert all(len(point) == 8 for point in points)


def test_weight_table():
    weights = weight_table(SBOX_SPLIGHT_S3)
    assert weights[0][0] == 0
    assert ddt_weight(1, 1) == 2
    assert weights[1][2] is None
