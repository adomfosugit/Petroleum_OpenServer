import pytest

from petroleum_openserver.ipr import (
    NO_SOLUTION,
    get_ipr_aofp,
    get_ipr_p,
    get_ipr_q,
    get_res_pres,
    ipr_binary_chop,
)


def test_get_ipr_p_linear_above_bubble_point():
    # Fully above bubble point, no water: plain PI behaviour (Pws - q/PI).
    assert get_ipr_p(pws_psig=5000, pb_psig=1000, pi_stbdpsi=2.0, wc_perc=0, q_stbd=2000) == 4000.0


def test_get_ipr_q_zero_at_pwf_equal_pws():
    assert get_ipr_q(pws_psig=2500, pb_psig=2000, pi_stbdpsi=1.5, wc_perc=10, pwf_psig=2500) == 0.0


def test_get_ipr_q_increases_as_pwf_drops():
    high_pwf = get_ipr_q(pws_psig=6000, pb_psig=2000, pi_stbdpsi=1.5, wc_perc=20, pwf_psig=4000)
    low_pwf = get_ipr_q(pws_psig=6000, pb_psig=2000, pi_stbdpsi=1.5, wc_perc=20, pwf_psig=1000)
    assert low_pwf > high_pwf


def test_get_ipr_p_and_get_ipr_q_are_inverses():
    pws, pb, pi, wc = 4500.0, 3200.0, 25.0, 40.0
    q = 30000.0
    pwf = get_ipr_p(pws, pb, pi, wc, q)
    assert get_ipr_q(pws, pb, pi, wc, pwf) == pytest.approx(q, rel=1e-6)


def test_get_ipr_aofp_is_rate_at_zero_pwf():
    pws, pb, pi, wc = 4500.0, 3200.0, 25.0, 40.0
    aofp = get_ipr_aofp(pws, pb, pi, wc)
    assert get_ipr_p(pws, pb, pi, wc, aofp) == pytest.approx(0.0, abs=1e-6)


def test_get_res_pres_round_trips_get_ipr_p():
    pi, pb, wc, pwf = 1.8, 2200.0, 15.0, 1200.0
    true_pws = 4300.0
    q = get_ipr_q(true_pws, pb, pi, wc, pwf)

    solved_pws = get_res_pres(pi, pb, wc, q, pwf, 1000, 10000)

    assert solved_pws == pytest.approx(true_pws, abs=0.05)


def test_get_res_pres_returns_no_solution_sentinel_when_unreachable():
    # No Pws in [1000, 10000] can produce this absurd rate at this Pwf.
    assert (
        get_res_pres(
            pi_stbdpsi=0.001, pb_psig=2000, wc_perc=0, q_stbd=1e9, p_psig=1500,
            min_pws_psig=1000, max_pws_psig=10000,
        )
        == NO_SOLUTION
    )


def test_ipr_binary_chop_solves_for_pi():
    pws, pb, wc, pwf = 4500.0, 3200.0, 40.0, 1500.0
    true_pi = 12.5
    q = get_ipr_q(pws, pb, true_pi, wc, pwf)

    solved_pi = ipr_binary_chop(pws, pb, wc, q, pwf, 1, 100)

    assert solved_pi == pytest.approx(true_pi, abs=0.01)
