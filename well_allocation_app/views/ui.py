"""Shared look and helpers for the Streamlit pages."""
from __future__ import annotations

import calendar
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import load_settings, load_wells

# Phase colours follow the production-plot convention (oil green, gas red, water blue),
# stepped so the three stay distinct for colour-blind readers.
PHASE = {"oil": "#5AA83C", "gas": "#A8324F", "water": "#2C6DB5"}
PRESS = {"bhp": "#2B5C9E", "thp": "#D08A2A", "nodal": "#1E9A8A", "match": "#9B4FB5"}
INK, MUTED, LINE, ACCENT = "#16242C", "#5B6B73", "#D5DDE1", "#0F5E6E"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&display=swap');
:root { --ink:#16242C; --muted:#5B6B73; --line:#D5DDE1; --accent:#0F5E6E; --panel:#FFFFFF; --wash:#EAF0F2; --done:#1E7A46; }
.block-container, [data-testid="stMainBlockContainer"] { padding-top: 4.2rem; max-width: 1320px; }
h1, h2, h3, .wa-title, .wa-fact b, [data-testid="stMetricValue"] {
  font-family: 'Barlow Semi Condensed', 'Source Sans', 'Source Sans Pro', sans-serif !important; letter-spacing: .005em; }
h1 { font-weight: 700 !important; }
h2, h3 { font-weight: 600 !important; color: var(--ink); }
[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
[data-testid="stMetricValue"] { font-size: 1.9rem; font-weight: 600; }
[data-testid="stMetricLabel"] p { color: var(--muted); }

.wa-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1.5rem;
  border-bottom: 2px solid var(--ink); padding-bottom:.6rem; margin-bottom:1.2rem; flex-wrap:wrap; }
.wa-title { font-size: 2.6rem; line-height: 1.15; font-weight: 700; color: var(--ink); margin:0; }
.wa-sub { color: var(--muted); margin-top:.35rem; font-size: .98rem; }
.wa-facts { display:flex; gap:1.6rem; flex-wrap:wrap; }
.wa-fact { display:flex; flex-direction:column; font-size:.8rem; color:var(--muted); }
.wa-fact b { font-size: 1.15rem; color: var(--ink); font-weight:600; }

.wa-rail { display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:0; margin: .2rem 0 1.4rem; }
.wa-step { border-top: 4px solid var(--line); padding:.45rem .2rem 0 0; color: var(--muted); font-size:.9rem; }
.wa-step b { display:block; color: var(--ink); font-weight:600; font-size: .95rem; }
.wa-step.done { border-top-color: var(--done); }
.wa-step.done b::after { content: "  ✓"; color: var(--done); }
@media (max-width: 720px) { .wa-rail { grid-template-columns: repeat(2, minmax(0,1fr)) !important; row-gap:.8rem; } }

.wa-stephd { display:flex; align-items:center; gap:.7rem; margin:.1rem 0 .6rem; }
.wa-pill { display:inline-flex; align-items:center; gap:.3rem; padding:.18rem .7rem; border-radius:999px; flex:none;
  font-family:'Barlow Semi Condensed','Source Sans',sans-serif; font-weight:700; font-size:.82rem; letter-spacing:.08em;
  text-transform:uppercase; border:1.5px solid var(--accent); color:var(--accent); background:var(--panel); }
.wa-pill.done { background: var(--done); border-color: var(--done); color:#fff; }
.wa-steptitle { font-family:'Barlow Semi Condensed','Source Sans',sans-serif; font-weight:600; font-size:1.45rem; color:var(--ink); }
.wa-chip { display:inline-block; padding: .08rem .55rem; border-radius: 999px; font-size: .78rem;
  border:1px solid var(--line); color: var(--ink); background: var(--panel); }
.wa-chip.live { border-color:#1E7A46; color:#1E7A46; }
.wa-chip.demo { border-color:#9A6A12; color:#7A5410; background:#FFF8EA; }
.wa-note { color: var(--muted); font-size: .9rem; }
div[data-testid="stExpander"] details { border-radius: 6px; }
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def settings() -> dict:
    return load_settings()


@st.cache_data(show_spinner=False)
def _wells_cached(_mtime: float) -> pd.DataFrame:
    return load_wells()


def wells() -> pd.DataFrame:
    from core.config import WELLS_CSV
    mtime = WELLS_CSV.stat().st_mtime if WELLS_CSV.exists() else 0.0
    return _wells_cached(mtime)


def period() -> tuple[int, int, str]:
    y, m = st.session_state["year"], st.session_state["month"]
    return y, m, f"{y:04d}-{m:02d}"


def period_label() -> str:
    y, m, _ = period()
    return f"{calendar.month_name[m]} {y}"


def default_period() -> tuple[int, int]:
    t = date.today().replace(day=1)
    prev = (pd.Timestamp(t) - pd.offsets.MonthBegin(1))
    return prev.year, prev.month


def header(title: str, sub: str = "", facts: list[tuple[str, str]] | None = None):
    facts_html = "".join(f'<div class="wa-fact">{k}<b>{v}</b></div>' for k, v in (facts or []))
    st.markdown(
        f'<div class="wa-head"><div><div class="wa-title">{title}</div>'
        f'<div class="wa-sub">{sub}</div></div><div class="wa-facts">{facts_html}</div></div>',
        unsafe_allow_html=True,
    )


def rail(steps: list[tuple[str, str, bool]]):
    html = "".join(
        f'<div class="wa-step {"done" if done else ""}"><b>{name}</b>{note}</div>' for name, note, done in steps
    )
    st.markdown(f'<div class="wa-rail" style="grid-template-columns: repeat({len(steps)}, minmax(0,1fr))">{html}</div>',
                unsafe_allow_html=True)


def mode_chip(mode: str) -> str:
    return ('<span class="wa-chip live">Live: PI + PROSPER</span>' if mode == "live"
            else '<span class="wa-chip demo">Demo data</span>')


def base_layout(fig: go.Figure, height=340, ytitle="", legend=True) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=8, r=8, t=30, b=8),
        font=dict(family="Source Sans Pro, sans-serif", size=13, color=INK),
        hovermode="x unified", showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
        yaxis=dict(title=ytitle, gridcolor="#EEF1F3", zeroline=False, tickformat=",.0f"),
        xaxis=dict(gridcolor="#F4F6F7", tickformat="%d %b"),
        hoverlabel=dict(bgcolor="white", bordercolor=LINE, font=dict(color=INK)),
    )
    return fig


def line(fig, x, y, name, color, dash=None, width=2, hover_fmt=",.0f", unit=""):
    fig.add_trace(go.Scatter(
        x=x, y=y, name=name, mode="lines+markers",
        line=dict(color=color, width=width, dash=dash), marker=dict(size=6, color=color),
        hovertemplate=f"%{{y:{hover_fmt}}} {unit}<extra>{name}</extra>", connectgaps=False,
    ))
    return fig


def fmt(v, digits=0, suffix=""):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f"{v:,.{digits}f}{suffix}"


def band(fig, x, lo, hi, name, fill):
    """Shaded band drawn per gap-free run of days, so missing days leave a clean break."""
    s = pd.DataFrame({"lo": lo, "hi": hi}, index=x)
    ok = s.notna().all(axis=1)
    seg_id = (ok != ok.shift()).cumsum()[ok]
    first = True
    for _, seg in s[ok].groupby(seg_id):
        xs = list(seg.index) + list(seg.index[::-1])
        ys = list(seg["hi"]) + list(seg["lo"][::-1])
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor=fill, line=dict(width=0),
                                 hoverinfo="skip", name=name, legendgroup=name, showlegend=first))
        first = False
    return fig


def step(n: int, title: str, done: bool = False):
    pill = '<span class="wa-pill done">Done ✓</span>' if done else f'<span class="wa-pill">Step {n}</span>'
    st.markdown(f'<div class="wa-stephd">{pill}<span class="wa-steptitle">{title}</span></div>',
                unsafe_allow_html=True)
