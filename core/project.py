"""Estado actual del proyecto, calculado a partir del plan original y los eventos.

Reglas de negocio (todas en este archivo):
- Avance de una actividad con SOP = tareas terminadas ÷ tareas aplicables
  (las tareas condicionales marcadas N/A no cuentan).
- Avance de una actividad sin SOP = porcentaje que registra el supervisor.
- Mientras una actividad no tenga registros, se usa el avance importado del Gantt.
- Avance de un camión = promedio simple de sus actividades.
- Días de trabajo propio = días hábiles en que hay al menos una actividad
  propia programada (no cuenta la espera por el trabajo externo de trunnion).
- Visibilidad: un camión aparece cuando faltan `lookahead_days` días o menos
  para su inicio, o cuando ya empezó.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from core import config
from core.catalog import load_catalog
from core.events import read_baseline, read_events, read_settings
from core.workdays import WorkCalendar

VISIBLE_STATUSES = ("in_progress", "overdue", "upcoming", "no_dates")


def _d(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value or (isinstance(value, float) and value != value):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _f(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


@dataclass
class Project:
    settings: dict
    today: date
    activities: pd.DataFrame          # una fila por camión × actividad
    trucks: pd.DataFrame              # una fila por camión
    tasks: pd.DataFrame               # estado actual de cada tarea SOP por camión
    task_log: pd.DataFrame            # todas las actualizaciones registradas
    delays: pd.DataFrame              # notas de atraso de los supervisores
    comments: pd.DataFrame            # comentarios por actividad
    plan_log: pd.DataFrame            # cambios de fechas del administrador
    acks: dict[str, dict] = field(default_factory=dict)
    truck_cal: dict[str, WorkCalendar] = field(default_factory=dict)

    # ── Consultas frecuentes ────────────────────────────────────────────
    def calendar(self, truck: str) -> WorkCalendar:
        return self.truck_cal.get(truck) or WorkCalendar.build(False, False, self.settings.get("holidays", []))

    def truck_row(self, truck: str) -> pd.Series:
        return self.trucks.set_index("truck").loc[truck]

    def truck_activities(self, truck: str) -> pd.DataFrame:
        return self.activities[self.activities.truck == truck].sort_values("order")

    def visible_trucks(self) -> list[str]:
        return self.trucks[self.trucks.status.isin(VISIBLE_STATUSES)].truck.tolist()

    def alerts(self) -> list[dict]:
        """Alertas para el administrador, de la más a la menos urgente."""
        out: list[dict] = []
        for _, tr in self.trucks.iterrows():
            if tr.status not in VISIBLE_STATUSES:
                continue
            acts = self.truck_activities(tr.truck)
            ext = acts[acts.external & (acts.progress < 1)]
            if len(ext) and tr.truck not in self.acks:
                out.append({"type": "trunnion", "truck": tr.truck, "acts": ext.to_dict("records")})
            missing = acts[(acts.fc_start.isna() | acts.fc_end.isna()) & (acts.progress < 1)]
            if len(missing):
                out.append({"type": "missing_dates", "truck": tr.truck, "acts": missing.to_dict("records")})
            if tr.status == "overdue":
                out.append({"type": "overdue", "truck": tr.truck, "days": tr.delay_wd})
            if tr.over_limit:
                out.append({"type": "over_limit", "truck": tr.truck, "days": tr.work_days})
            late = acts[(acts.status == "overdue")]
            for _, a in late.iterrows():
                out.append({"type": "act_overdue", "truck": tr.truck, "act": a.act_key, "end": a.fc_end})
            idle = acts[acts.fc_start.notna() & acts.fc_end.notna() & (acts.work_days == 0) & (acts.progress < 1)]
            for _, a in idle.iterrows():
                out.append({"type": "non_workday", "truck": tr.truck, "act": a.act_key, "end": a.fc_end})
        order = {"trunnion": 0, "missing_dates": 1, "overdue": 2, "act_overdue": 3, "non_workday": 4, "over_limit": 5}
        return sorted(out, key=lambda a: order[a["type"]])


def today_in(settings: dict) -> date:
    try:
        tz = ZoneInfo(settings.get("timezone") or "UTC")
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()


def _activity_status(progress: float, start: date | None, end: date | None, today: date) -> str:
    if progress >= 1:
        return "completed"
    if start is None or end is None:
        return "no_dates"
    if today > end:
        return "overdue"
    if progress > 0 or today >= start:
        return "in_progress"
    return "not_started"


def build_project(snapshot: Mapping[str, bytes], today: date | None = None) -> Project:
    events = read_events(snapshot)
    settings = read_settings(snapshot, events["settings"])
    today = today or today_in(settings)
    lookahead = int(settings.get("lookahead_days", 14))
    max_wd = int(settings.get("max_working_days", 5))
    holidays = settings.get("holidays", [])

    # ── Plan: original + cambios del administrador ──────────────────────
    acts = read_baseline(snapshot)
    acts["fc_start"], acts["fc_end"] = acts["base_start"], acts["base_end"]
    idx = {(r.truck, r.act_key): i for i, r in acts.iterrows()}
    weekend: dict[str, dict] = {}
    plan_rows = []
    for ev in events["plan"]:
        truck = ev.get("truck")
        if "weekend" in ev:
            weekend[truck] = ev["weekend"]
        for ch in ev.get("changes", []):
            i = idx.get((truck, ch.get("act")))
            if i is None:
                continue
            for fld in ("fc_start", "fc_end", "assigned_to"):
                if fld in ch:
                    acts.at[i, fld] = ch[fld] or ""
            for fld in ("base_start", "base_end"):  # solo se completa si estaba vacía
                if ch.get(fld) and not acts.at[i, fld]:
                    acts.at[i, fld] = ch[fld]
            plan_rows.append({"ts": ev["ts"], "user": ev["user"], "truck": truck, "act_key": ch.get("act"),
                              "fc_start": ch.get("fc_start", ""), "fc_end": ch.get("fc_end", ""),
                              "reason": ev.get("reason", "")})

    truck_cal = {
        t: WorkCalendar.build(weekend.get(t, {}).get("sat", False), weekend.get(t, {}).get("sun", False), holidays)
        for t in acts.truck.unique()
    }

    # ── Registros de tareas: el último por tarea manda ──────────────────
    log_rows, comment_rows = [], []
    for ev in events["task"]:
        for up in ev.get("updates", []):
            log_rows.append({"ts": ev["ts"], "user": ev["user"], "truck": ev.get("truck"), "act_key": ev.get("act"), **up})
        if (ev.get("comment") or "").strip():
            comment_rows.append({"ts": ev["ts"], "user": ev["user"], "truck": ev.get("truck"),
                                 "act_key": ev.get("act"), "text": ev["comment"].strip()})
    log_cols = ["ts", "user", "truck", "act_key", "task_id", "status", "progress", "actual_mh", "supervisor",
                "technicians", "date", "qc_result", "remarks"]
    task_log = pd.DataFrame(log_rows, columns=log_cols) if log_rows else pd.DataFrame(columns=log_cols)
    latest = task_log.drop_duplicates(["truck", "act_key", "task_id"], keep="last")

    # Estado de cada tarea SOP en cada camión
    cat = load_catalog()
    task_frames = []
    for (truck, act_key) in idx:
        sops = config.ACTIVITY_BY_KEY[act_key].sops
        if not sops:
            continue
        t = cat[cat.sop.isin(sops)].copy()
        t["sop_order"] = t.sop.map({s: n for n, s in enumerate(sops)})
        t = t.sort_values(["sop_order", "seq"])
        t.insert(0, "truck", truck)
        t.insert(1, "act_key", act_key)
        task_frames.append(t)
    tasks = pd.concat(task_frames, ignore_index=True)
    rec = latest[latest.task_id != config.ACTIVITY_TASK_ID].drop(columns=["progress"])
    tasks = tasks.merge(rec, on=["truck", "act_key", "task_id"], how="left")
    tasks["status"] = tasks["status"].fillna("not_started")
    tasks["qc_result"] = tasks["qc_result"].where(tasks["qc_result"].notna() & (tasks["qc_result"] != ""), "pending")
    tasks["actual_mh"] = pd.to_numeric(tasks["actual_mh"], errors="coerce")
    for col in ("supervisor", "technicians", "date", "remarks", "user", "ts"):
        tasks[col] = tasks[col].fillna("")

    # ── Avance por actividad ────────────────────────────────────────────
    act_manual = latest[latest.task_id == config.ACTIVITY_TASK_ID].set_index(["truck", "act_key"])
    has_task_rec = set(map(tuple, rec[["truck", "act_key"]].drop_duplicates().values))
    progress, has_records, mh = [], [], []
    for _, a in acts.iterrows():
        key = (a.truck, a.act_key)
        if config.ACTIVITY_BY_KEY[a.act_key].sops:
            t = tasks[(tasks.truck == a.truck) & (tasks.act_key == a.act_key)]
            applicable = t[t.status != "na"]
            if key in has_task_rec:
                p = (applicable.status == "done").sum() / len(applicable) if len(applicable) else 1.0
                has_records.append(True)
            else:
                p = _f(a.imported_progress) or 0.0
                has_records.append(False)
            mh.append(float(t.actual_mh.sum(skipna=True)))
        else:
            if key in act_manual.index:
                row = act_manual.loc[key]
                p = (_f(row.progress) or 0.0) / 100
                has_records.append(True)
                mh.append(_f(row.actual_mh) or 0.0)
            else:
                p = _f(a.imported_progress) or 0.0
                has_records.append(False)
                mh.append(0.0)
        progress.append(min(max(p, 0.0), 1.0))
    acts["progress"] = progress
    acts["has_records"] = has_records
    acts["actual_mh"] = mh
    acts["order"] = acts.act_key.map(config.ACTIVITY_ORDER)
    acts["external"] = acts.act_key.isin(config.EXTERNAL_KEYS)
    acts["has_sop"] = acts.act_key.map(lambda k: bool(config.ACTIVITY_BY_KEY[k].sops))
    for col in ("base_start", "base_end", "fc_start", "fc_end"):
        acts[col] = acts[col].map(_d)
    acts["status"] = [
        _activity_status(r.progress, r.fc_start, r.fc_end, today) for r in acts.itertuples()
    ]
    acts["delay_wd"] = [truck_cal[r.truck].delay(r.base_end, r.fc_end) for r in acts.itertuples()]
    acts["work_days"] = [truck_cal[r.truck].count(r.fc_start, r.fc_end) for r in acts.itertuples()]

    # ── Resumen por camión ──────────────────────────────────────────────
    truck_rows = []
    for truck, g in acts.groupby("truck", sort=True):
        cal = truck_cal[truck]
        starts = [d for d in g.fc_start if d]
        ends = [d for d in g.fc_end if d]
        bends = [d for d in g.base_end if d]
        start, end = (min(starts) if starts else None), (max(ends) if ends else None)
        base_end = max(bends) if bends else None
        p = float(g.progress.mean())
        # Días hábiles con trabajo propio programado (unión de rangos)
        days: set[date] = set()
        for r in g[~g.external].itertuples():
            if r.fc_start and r.fc_end:
                d = r.fc_start
                while d <= r.fc_end:
                    if cal.is_workday(d):
                        days.add(d)
                    d += timedelta(days=1)
        if p >= 1:
            status = "completed"
        elif start is None:
            status = "no_dates"
        elif end and today > end:
            status = "overdue"
        elif today >= start or p > 0:
            status = "in_progress"
        elif (start - today).days <= lookahead:
            status = "upcoming"
        else:
            status = "future"
        truck_rows.append({
            "truck": truck, "start": start, "end": end, "base_end": base_end,
            "progress": p, "status": status, "work_days": len(days),
            "over_limit": len(days) > max_wd and p < 1,
            "delay_wd": cal.delay(base_end, end) if p < 1 else 0,
            "actual_mh": float(g.actual_mh.sum()),
            "sat": cal.saturday, "sun": cal.sunday,
            "days_to_start": (start - today).days if start else None,
        })
    trucks = pd.DataFrame(truck_rows)

    # ── Atrasos, comentarios y alertas atendidas ────────────────────────
    delay_cols = ["ts", "user", "truck", "act", "category", "impact_days", "description"]
    delays = pd.DataFrame([{c: ev.get(c, "") for c in delay_cols} for ev in events["delay"]], columns=delay_cols)
    comments = pd.DataFrame(comment_rows, columns=["ts", "user", "truck", "act_key", "text"])
    plan_log = pd.DataFrame(plan_rows, columns=["ts", "user", "truck", "act_key", "fc_start", "fc_end", "reason"])
    acks = {ev["truck"]: ev for ev in events["ack"] if ev.get("truck")}

    return Project(settings=settings, today=today, activities=acts, trucks=trucks, tasks=tasks,
                   task_log=task_log, delays=delays, comments=comments, plan_log=plan_log,
                   acks=acks, truck_cal=truck_cal)
