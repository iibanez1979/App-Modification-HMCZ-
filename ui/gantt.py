"""Gantt interactivo (Plotly): plan original (barra gris delgada) y pronóstico
(barra de color según el estado), con la línea de hoy."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go

from core import config
from core.project import Project
from ui.common import T, act_name, fmt_date, fmt_pct

DAY_MS = 86_400_000
ACT_COLORS = {
    "completed": "#2E7D32", "in_progress": config.ORANGE, "overdue": "#C62828",
    "not_started": "#1565C0", "no_dates": "#6D4C41",
}


def gantt_figure(p: Project, t: T, trucks: list[str], show_baseline: bool = True) -> go.Figure:
    acts = p.activities[p.activities.truck.isin(trucks)].sort_values(["truck", "order"])
    rows = [f"{r.truck} · {act_name(t, r.act_key)}" for r in acts.itertuples()]
    fig = go.Figure()

    def bars(start_col: str, end_col: str) -> pd.DataFrame:
        df = acts.copy()
        df["row"] = rows
        df = df[df[start_col].notna() & df[end_col].notna()]
        df["x0"] = pd.to_datetime(df[start_col])
        df["dur"] = (pd.to_datetime(df[end_col]) + timedelta(days=1) - df["x0"]).dt.days * DAY_MS
        return df

    if show_baseline:
        b = bars("base_start", "base_end")
        fig.add_trace(go.Bar(
            y=b.row, x=b.dur, base=b.x0, orientation="h", name=t("original_plan"),
            marker=dict(color="#BDBDBD"), width=0.28, offset=-0.42,
            customdata=[[fmt_date(r.base_start), fmt_date(r.base_end)] for r in b.itertuples()],
            hovertemplate="<b>%{y}</b><br>" + t("original_plan") + ": %{customdata[0]} → %{customdata[1]}<extra></extra>",
        ))
    f = bars("fc_start", "fc_end")
    for status, color in ACT_COLORS.items():
        g = f[f.status == status]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            y=g.row, x=g.dur, base=g.x0, orientation="h", name=t("st_" + status),
            marker=dict(color=color, line=dict(color="#1A1A1A", width=0.5)),
            width=0.5, offset=-0.1 if show_baseline else -0.25,
            text=[fmt_pct(v) for v in g.progress], textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=11),
            customdata=[[fmt_date(r.fc_start), fmt_date(r.fc_end), fmt_pct(r.progress), r.delay_wd,
                         t("external") if r.external else ""] for r in g.itertuples()],
            hovertemplate=("<b>%{y}</b> %{customdata[4]}<br>" + t("forecast") + ": %{customdata[0]} → %{customdata[1]}"
                           "<br>" + t("progress") + ": %{customdata[2]}<br>" + t("delay_wd") + ": %{customdata[3]}<extra></extra>"),
        ))

    fig.add_vline(x=pd.Timestamp(p.today).value / 1e6, line=dict(color=config.ORANGE, width=2, dash="dash"))
    fig.add_annotation(x=pd.Timestamp(p.today), y=1.0, yref="paper", text=t("today"), showarrow=False, xanchor="left",
                       font=dict(color=config.ORANGE, size=11), xshift=4, yshift=-8)
    # Separadores entre camiones
    for n in range(1, len(trucks)):
        count = (acts.truck.isin(trucks[:n])).sum()
        fig.add_hline(y=count - 0.5, line=dict(color="#DDDDDD", width=1))

    fig.update_layout(
        barmode="overlay", height=max(320, 26 * len(rows) + 120),
        margin=dict(l=10, r=10, t=50, b=40), plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="top", y=-0.01, x=0),
        font=dict(family="Barlow, sans-serif", size=12, color="#1A1A1A"),
        xaxis=dict(type="date", gridcolor="#EEEEEE", tickformat="%d-%b", dtick=7 * DAY_MS,
                   showgrid=True, side="top"),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(rows)), autorange=True),
        hoverlabel=dict(bgcolor="white"),
    )
    return fig
