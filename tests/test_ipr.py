import pytest

from petroleum_openserver.ipr import get_res_pres, ipr_rate


def test_ipr_rate_linear_above_bubble_point():
    # Fully above bubble point, no water: plain PI behaviour.
    assert ipr_rate(pr=5000, pwf=4000, pi=2.0, pb=1000, wc_percent=0) == 2000.0


def test_ipr_rate_increases_with_reservoir_pressure():
    low = ipr_rate(pr=3000, pwf=1500, pi=1.5, pb=2000, wc_percent=20)
    high = ipr_rate(pr=6000, pwf=1500, pi=1.5, pb=2000, wc_percent=20)
    assert high > low


def test_ipr_rate_zero_at_pr_equal_pwf():
    assert ipr_rate(pr=2500, pwf=2500, pi=1.5, pb=2000, wc_percent=10) == 0.0


def test_get_res_pres_round_trips_ipr_rate():
    pi, pb, wc, pwf = 1.8, 2200.0, 15.0, 1200.0
    true_pr = 4300.0
    q = ipr_rate(true_pr, pwf, pi, pb, wc)

    solved_pr = get_res_pres(pi, pb, wc, q, pwf, pr_min=1000, pr_max=10000, tol=1e-6)

    assert solved_pr == pytest.approx(true_pr, abs=0.05)


def test_get_res_pres_clamps_to_bracket_when_unreachable():
    # No PI can produce this from within [1000, 10000] at this Pwf - should clamp high.
    assert get_res_pres(pi=0.001, pb=2000, wc_percent=0, q=1e9, pwf=1500, pr_min=1000, pr_max=10000) == 10000
