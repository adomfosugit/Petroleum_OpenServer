"""
Composite IPR (straight line above Pb, Vogel below, water-cut blended) -
Python port of the VBA IPR module.

All pressures are gauge (psig), rates stb/d, PI stb/d/psi, watercut in %.

Public functions (same names/argument order as VBA, snake_case):
    get_ipr_q(pws, pb, pi, wc, pwf)         -> liquid rate at pwf
    get_ipr_p(pws, pb, pi, wc, q)           -> flowing pressure at rate q
    get_ipr_aofp(pws, pb, pi, wc)           -> absolute open flow potential
    ipr_binary_chop(pws, pb, wc, q, p, min_pi, max_pi)     -> PI matching (q, p)
    get_res_pres(pi, pb, wc, q, p, min_pws, max_pws)       -> Pws matching (q, p)

The two solvers return NO_SOLUTION (-7777) when they fail, exactly like the
VBA. Use the *_detail variants to get the status message as well.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

NO_SOLUTION = -7777.0

MSG_OK = "OK: Solved"
MSG_NO_SOLUTION = "WARNING: No Solution Exists Between Specified Limits"
MSG_MAX_ITER = "WARNING: Maximum Number Of Iterations Reached"


@dataclass(frozen=True)
class _Ipr:
    pws: float
    pb: float
    j: float
    qb: float
    qo_max: float
    fw: float
    fo: float
    bb: float
    tan_beta: float
    qt_max: float
    pwf_g: float
    min_pws_pb: float


def _intermediates(pws: float, pb: float, j: float, wc: float,
                   bo: float = 1.0, bw: float = 1.0) -> _Ipr:
    """IprIntermediates."""
    min_pws_pb = min(pws, pb)
    max_pws_pb = max(pws, pb)

    qb = j * (max_pws_pb - pb)
    qo_max = qb + j * min_pws_pb / 1.8
    if wc == 0:
        fw = 0.0
    elif wc == 100:
        fw = 0.9999999
    else:
        fw = 1 / ((bo / bw) * (1 / (wc / 100) - 1) + 1)
    fo = 1 - fw
    bb = fw / (0.125 * fo * min_pws_pb * j)
    cd = (fw * (0.001 * qo_max / j)
          + fo * 0.125 * min_pws_pb * (-1 + math.sqrt(81 - 80 * ((0.999 * qo_max - qb) / (qo_max - qb)))))
    cg = 0.001 * qo_max
    tan_alpha = cg / cd
    tan_beta = cd / cg
    pwf_g = fw * (pws - qo_max / j)
    qt_max = qo_max + fw * (pws - qo_max / j) * tan_alpha
    return _Ipr(pws, pb, j, qb, qo_max, fw, fo, bb, tan_beta, qt_max, pwf_g, min_pws_pb)


def _q_calc(c: _Ipr, pwf: float) -> float:
    """IprQCalc."""
    if pwf >= c.pws:
        return 0.0
    if pwf <= 0:
        return c.qt_max
    if pwf >= c.pb:
        return c.j * (c.pws - pwf)
    if pwf <= c.pwf_g:
        return (c.pwf_g + c.qo_max * c.tan_beta - pwf) / c.tan_beta
    aa = (pwf + 0.125 * c.fo * c.min_pws_pb - c.fw * c.pws) / (0.125 * c.fo * c.min_pws_pb)
    cc = 2 * aa * c.bb + 80 / (c.qo_max - c.qb)
    dd = aa * aa - 80 * c.qb / (c.qo_max - c.qb) - 81
    if c.bb == 0:
        return -dd / cc
    return (-cc + math.sqrt(cc * cc - 4 * c.bb * c.bb * dd)) / (2 * c.bb * c.bb)


def _p_calc(c: _Ipr, q: float) -> float:
    """IprPCalc."""
    if q <= 0:
        return c.pws
    if q >= c.qt_max:
        return 0.0
    if q <= c.qb:
        return c.pws - q / c.j
    if q > c.qo_max:
        return c.fw * (c.pws - c.qo_max / c.j) - (q - c.qo_max) * c.tan_beta
    return (c.fo * (0.125 * c.min_pws_pb * (-1 + math.sqrt(81 - 80 * ((q - c.qb) / (c.qo_max - c.qb)))))
            + c.fw * (c.pws - q / c.j))


def get_ipr_q(pws_psig: float, pb_psig: float, pi_stbdpsi: float, wc_perc: float,
              pwf_psig: float, bo_rbblstb: float = 1.0, bw_rbblstb: float = 1.0) -> float:
    """GetIprQ: liquid rate (stb/d) at flowing pressure pwf."""
    return _q_calc(_intermediates(pws_psig, pb_psig, pi_stbdpsi, wc_perc, bo_rbblstb, bw_rbblstb), pwf_psig)


def get_ipr_p(pws_psig: float, pb_psig: float, pi_stbdpsi: float, wc_perc: float,
              q_stbd: float, bo_rbblstb: float = 1.0, bw_rbblstb: float = 1.0) -> float:
    """GetIprP: flowing pressure (psig) at liquid rate q."""
    return _p_calc(_intermediates(pws_psig, pb_psig, pi_stbdpsi, wc_perc, bo_rbblstb, bw_rbblstb), q_stbd)


def get_ipr_aofp(pws_psig: float, pb_psig: float, pi_stbdpsi: float, wc_perc: float,
                 bo_rbblstb: float = 1.0, bw_rbblstb: float = 1.0) -> float:
    """GetIprAofp: absolute open flow potential (stb/d)."""
    return _intermediates(pws_psig, pb_psig, pi_stbdpsi, wc_perc, bo_rbblstb, bw_rbblstb).qt_max


# --------------------------------------------------------------------------
# Binary chop (shared by IprBinaryChop and getResPres - same algorithm)
# --------------------------------------------------------------------------
def _binary_chop(err_fn: Callable[[float], float], x_min: float, x_max: float,
                 tol: float, iter_max: int) -> tuple[float, str]:
    have_lo = have_hi = False
    x_lo = x_hi = 0.0
    err_lo = err_hi = 0.0
    n = 0
    while True:
        n += 1
        if n == 1:
            x = x_min
        elif n == 2:
            x = x_max
        else:
            x = (x_hi + x_lo) / 2

        err = err_fn(x)

        if n == 1:
            # First guess: note which side of the target we landed on
            if err < 0:
                err_lo, x_lo, have_lo = err, x, True
            else:
                err_hi, x_hi, have_hi = err, x, True
        elif n == 2:
            # Both limits on the same side: no root in the bracket
            if err < 0:
                if have_lo:
                    return NO_SOLUTION, MSG_NO_SOLUTION
                err_lo, x_lo = err, x
            else:
                if have_hi:
                    return NO_SOLUTION, MSG_NO_SOLUTION
                err_hi, x_hi = err, x
        elif err <= 0:
            x_lo, err_lo = x, err
        else:
            x_hi, err_hi = x, err

        if n > 2 and abs(err) < tol:
            return x, MSG_OK
        if n >= iter_max:
            return NO_SOLUTION, MSG_MAX_ITER


def ipr_binary_chop_detail(pws_psig: float, pb_psig: float, wc_perc: float, q_stbd: float, p_psig: float,
                           min_pi_stbdpsi: float, max_pi_stbdpsi: float, output_tol: float = 0.01,
                           iter_max: int = 50, bo_rbblstb: float = 1.0, bw_rbblstb: float = 1.0
                           ) -> tuple[float, str]:
    """Find the PI that gives flowing pressure p at rate q. Returns (PI, message)."""
    return _binary_chop(
        lambda pi: get_ipr_p(pws_psig, pb_psig, pi, wc_perc, q_stbd, bo_rbblstb, bw_rbblstb) - p_psig,
        min_pi_stbdpsi, max_pi_stbdpsi, output_tol, iter_max)


def ipr_binary_chop(*args, **kwargs) -> float:
    """IprBinaryChop: PI matching (q, p), or -7777 if not solved."""
    return ipr_binary_chop_detail(*args, **kwargs)[0]


def get_res_pres_detail(pi_stbdpsi: float, pb_psig: float, wc_perc: float, q_stbd: float, p_psig: float,
                        min_pws_psig: float, max_pws_psig: float, output_tol: float = 0.01,
                        iter_max: int = 50, bo_rbblstb: float = 1.0, bw_rbblstb: float = 1.0
                        ) -> tuple[float, str]:
    """Find the reservoir pressure that gives flowing pressure p at rate q. Returns (Pws, message)."""
    return _binary_chop(
        lambda pws: get_ipr_p(pws, pb_psig, pi_stbdpsi, wc_perc, q_stbd, bo_rbblstb, bw_rbblstb) - p_psig,
        min_pws_psig, max_pws_psig, output_tol, iter_max)


def get_res_pres(*args, **kwargs) -> float:
    """getResPres: reservoir pressure (psig) matching (q, p), or -7777 if not solved."""
    return get_res_pres_detail(*args, **kwargs)[0]


if __name__ == "__main__":
    # Quick check: build a point from a known Pws/PI, then solve back for them
    pws, pb, pi, wc = 4500.0, 3200.0, 25.0, 40.0
    q = 30000.0
    pwf = get_ipr_p(pws, pb, pi, wc, q)
    print(f"Pwf at {q:.0f} stb/d  = {pwf:.2f} psig")
    print(f"Q back at that Pwf  = {get_ipr_q(pws, pb, pi, wc, pwf):.1f} stb/d")
    print(f"AOFP                = {get_ipr_aofp(pws, pb, pi, wc):.0f} stb/d")
    print("Pws solved          =", get_res_pres_detail(pi, pb, wc, q, pwf, 1000, 10000))
    print("PI solved           =", ipr_binary_chop_detail(pws, pb, wc, q, pwf, 1, 100))
