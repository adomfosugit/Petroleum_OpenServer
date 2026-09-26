"""Port of the VBA `getResPres` function used by `EstimateResPress` (IPR matching).

`getResPres` was called as:

    getResPres(CDbl(PI), CDbl(Pb), CDbl(WC), CDbl(LiqRate), CDbl(BHP) - 14.7, 1000, 10000) + 14.7

i.e. `(PI, Pb, WC, Q, Pwf_gauge, Pr_min, Pr_max) -> Pr_gauge`, and its own body
was not part of the pasted VBA (it lived in another module). This
reimplements it as: given a liquid PI, bubble point pressure, water cut,
measured liquid rate and flowing bottomhole pressure, solve for the
reservoir pressure that reproduces that rate, using the standard combined
PI/Vogel IPR (Vogel, 1968), applied to the oil fraction only (water is
assumed to follow simple Darcy/PI behaviour - it doesn't evolve gas), and
bisection since the combined IPR isn't directly invertible in closed form.

This is a defensible, commonly used approximation, but it is a
reconstruction, not a transcription of the original `getResPres` - if the
source module turns up, prefer porting it directly instead.
"""

from __future__ import annotations


def ipr_rate(pr: float, pwf: float, pi: float, pb: float, wc_percent: float = 0.0) -> float:
    """Liquid rate produced at flowing pressure `pwf` given reservoir pressure `pr`.

    `pi` is the liquid productivity index (rate / dP). The oil fraction of
    that PI follows Vogel's IPR once pressure drops below the bubble point
    `pb`; the water fraction stays linear throughout.
    """
    fo = max(0.0, 1.0 - wc_percent / 100.0)
    fw = 1.0 - fo
    pi_o = pi * fo
    pi_w = pi * fw

    q_water = pi_w * max(pr - pwf, 0.0)

    if pr <= pb:
        if pr <= 0:
            return q_water
        qo_max = pi_o * pr / 1.8
        ratio = min(max(pwf / pr, 0.0), 1.0) if pr > 0 else 1.0
        q_oil = qo_max * (1 - 0.2 * ratio - 0.8 * ratio**2)
    else:
        if pwf >= pb:
            q_oil = pi_o * (pr - pwf)
        else:
            qb = pi_o * (pr - pb)
            qo_max = pi_o * pb / 1.8
            ratio = pwf / pb if pb > 0 else 1.0
            q_oil = qb + qo_max * (1 - 0.2 * ratio - 0.8 * ratio**2)

    return max(q_oil, 0.0) + q_water


def get_res_pres(
    pi: float,
    pb: float,
    wc_percent: float,
    q: float,
    pwf: float,
    pr_min: float = 1000.0,
    pr_max: float = 10000.0,
    tol: float = 1e-4,
    max_iter: int = 200,
) -> float:
    """Solve for the reservoir pressure `pr` in `[pr_min, pr_max]` that reproduces `q` at `pwf`.

    `ipr_rate(pr, ...)` is monotonically non-decreasing in `pr`, so a plain
    bisection is sufficient. If `q` can't be reached within the bracket the
    result is clamped to `pr_min`/`pr_max` (mirroring how the sheet is meant
    to be used with a bounded search range).
    """
    if pi <= 0 or q <= 0:
        return pr_min

    def f(pr: float) -> float:
        return ipr_rate(pr, pwf, pi, pb, wc_percent) - q

    lo, hi = pr_min, pr_max
    f_lo, f_hi = f(lo), f(hi)
    if f_lo >= 0:
        return lo
    if f_hi <= 0:
        return hi

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        if abs(f_mid) < tol:
            return mid
        if f_mid < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
