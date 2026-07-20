"""
Epic 4: Educator Insight Dashboard (Streamlit)

Classroom Mastery Heatmap (high-density G6–G9):
- Calls FastAPI endpoint /api/v1/mastery/matrix for real mastery scores.
- Dynamically loads all topic columns from Data/Skill-Heirarchies-G6-G9.xlsx.
- Horizontal overflow for 57-topic grids (no crushed / overlapping headers).
- Strict BKT color bands:
  * Red    : < 0.50  (At Risk)
  * Orange : 0.50 - 0.79  (Learning)
  * Green  : >= 0.80  (Mastered)
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_API_TIMEOUT_S = 180.0
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_HIERARCHY_XLSX = PROJECT_ROOT / "Data" / "Skill-Heirarchies-G6-G9.xlsx"
_TOPIC_ID_RE = re.compile(r"^G[6-9]_", re.IGNORECASE)

# Strict BKT mastery boundaries (probability scale).
BKT_MASTERED = 0.80
BKT_LEARNING = 0.50

DEFAULT_STUDENTS = [
    "user_001",
    "user_002",
    "user_003",
    "user_004",
    "user_005",
]


@lru_cache(maxsize=1)
def _load_skill_hierarchy() -> tuple[tuple[str, ...], dict[str, str]]:
    """Load topic IDs and display labels from the merged G6–G9 skill hierarchy."""
    fallback_topics = (
        "G6_S1_ORG_CHARS",
        "G6_S1_ORG_CLASS",
        "G6_S2_MAT_PROPS",
        "G6_S2_MAT_STATES",
        "G6_S4_ENE_SOURCES",
        "G6_S8_ELE_CIRCUITS",
        "G6_S8_ELE_CONDINS",
    )
    fallback_labels = {tid: tid for tid in fallback_topics}
    if not SKILL_HIERARCHY_XLSX.is_file():
        return fallback_topics, fallback_labels

    df = pd.read_excel(SKILL_HIERARCHY_XLSX, sheet_name=0)
    topic_col = "Topic ID (Mocked for Assessment Module)"
    ref_col = "Curriculum Reference"
    if topic_col not in df.columns:
        return fallback_topics, fallback_labels

    topics: list[str] = []
    labels: dict[str, str] = {}
    for _, row in df.iterrows():
        tid = str(row.get(topic_col) or "").strip()
        if not tid or not _TOPIC_ID_RE.match(tid):
            continue
        topics.append(tid)
        ref = str(row.get(ref_col) or "").strip() if ref_col in df.columns else ""
        labels[tid] = ref if ref else tid

    unique_topics = list(dict.fromkeys(topics))
    if not unique_topics:
        return fallback_topics, fallback_labels
    return tuple(unique_topics), labels


DEFAULT_TOPICS: list[str] = list(_load_skill_hierarchy()[0])
TOPIC_LABELS: dict[str, str] = dict(_load_skill_hierarchy()[1])


def fetch_mastery_matrix(
    api_base: str,
    student_ids: list[str],
    topic_ids: list[str],
    mode: str,
    timeout_s: float = DEFAULT_API_TIMEOUT_S,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/api/v1/mastery/matrix"
    payload = {
        "student_ids": student_ids,
        "topic_ids": topic_ids,
        "mode": mode,
    }
    resp = requests.post(url, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def fetch_at_risk_students(
    api_base: str,
    student_ids: list[str],
    topic_ids: list[str],
    mode: str,
    timeout_s: float = DEFAULT_API_TIMEOUT_S,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/api/v1/analytics/at-risk-students"
    payload = {
        "student_ids": student_ids,
        "topic_ids": topic_ids,
        "mode": mode,
    }
    resp = requests.post(url, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def fetch_student_profile(
    api_base: str,
    user_id: str,
    mode: str,
    timeout_s: float = DEFAULT_API_TIMEOUT_S,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/api/v1/analytics/student-profile/{user_id}"
    resp = requests.get(url, params={"mode": mode}, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def matrix_to_dataframe(
    mastery_matrix: dict[str, dict[str, float | None]],
    topic_ids: list[str],
) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(mastery_matrix, orient="index")
    # Keep teacher-selected column order (Excel hierarchy order).
    missing_cols = [t for t in topic_ids if t not in df.columns]
    for col in missing_cols:
        df[col] = 0.0
    df = df[topic_ids]
    df = df.apply(pd.to_numeric, errors="coerce")
    df.index.name = "student_id"
    return df


def _topic_label(topic_id: str) -> str:
    return TOPIC_LABELS.get(topic_id, topic_id)


def _header_label(topic_id: str, *, dense: bool) -> str:
    """
    Dense grids use compact topic IDs on the axis; full curriculum names live in hover.
    """
    if dense:
        return topic_id
    label = _topic_label(topic_id)
    if len(label) > 28:
        return label[:25] + "…"
    return label


def _risk_tier(score: int) -> tuple[str, str]:
    if score >= 80:
        return "Immediate Support", "#7f1d1d"
    if score >= 60:
        return "Needs Attention", "#9a3412"
    if score >= 40:
        return "Watchlist", "#854d0e"
    return "Monitor", "#14532d"


def build_heatmap(df: pd.DataFrame, title: str) -> go.Figure:
    """
    High-density mastery heatmap with strict 3-band BKT coloring.

    Column headers are topic IDs (from Excel) to prevent overlap; curriculum
    references appear in hover text. Chart width scales with column count so the
    Streamlit scroll wrapper can pan horizontally.
    """
    n_topics = max(1, len(df.columns))
    dense = n_topics >= 12
    z = df.to_numpy(dtype=float)
    x_ids = list(df.columns)
    x = [_header_label(t, dense=dense) for t in x_ids]
    y = list(df.index)
    custom = [[_topic_label(t) for t in x_ids] for _ in y]

    # Strict piecewise scale on probability [0, 1]:
    # <0.50 red | 0.50–0.79 orange | >=0.80 green
    colorscale = [
        [0.00, "#dc2626"],
        [0.4999, "#dc2626"],
        [0.50, "#f59e0b"],
        [0.7999, "#f59e0b"],
        [0.80, "#16a34a"],
        [1.00, "#16a34a"],
    ]

    text = [[f"{v * 100:.0f}" for v in row] for row in z]
    col_px = 78 if dense else 110
    chart_width = max(960, 140 + col_px * n_topics)
    chart_height = max(360, 110 + 42 * max(1, len(y)))

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x,
            y=y,
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=10 if dense else 12, color="#111827"),
            customdata=custom,
            colorscale=colorscale,
            zmin=0.0,
            zmax=1.0,
            xgap=1,
            ygap=1,
            colorbar=dict(
                title="BKT P(L)",
                tickvals=[0.25, 0.65, 0.90],
                ticktext=[
                    "🔴 At Risk (<50%)",
                    "🟠 Learning (50–79%)",
                    "🟢 Mastered (≥80%)",
                ],
                len=0.85,
            ),
            hovertemplate=(
                "Student: %{y}<br>"
                "Topic ID: %{x}<br>"
                "Curriculum: %{customdata}<br>"
                "Mastery: %{z:.1%}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Science Topics (from Skill-Heirarchies-G6-G9.xlsx)",
        yaxis_title="Student IDs",
        margin=dict(l=90, r=30, t=60, b=160 if dense else 100),
        width=chart_width,
        height=chart_height,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        font=dict(size=12),
    )
    fig.update_xaxes(
        tickangle=-90 if dense else -35,
        tickfont=dict(size=9 if dense else 11),
        automargin=True,
        side="bottom",
        type="category",
        categoryorder="array",
        categoryarray=x,
    )
    fig.update_yaxes(
        tickfont=dict(size=11),
        automargin=True,
        type="category",
        categoryorder="array",
        categoryarray=y,
        autorange="reversed",
    )
    return fig


def style_mastery_dataframe(df_prob: pd.DataFrame) -> Any:
    """Percentage table with strict BKT cell background / text colors."""
    df_pct = (df_prob * 100.0).copy()
    df_pct.index.name = "student_id"

    def _cell_style(val: Any) -> str:
        try:
            score = float(val)
        except (TypeError, ValueError):
            return "background-color: #e5e7eb; color: #111827;"
        if score >= BKT_MASTERED * 100:
            return "background-color: #16a34a; color: #ffffff; font-weight: 600;"
        if score >= BKT_LEARNING * 100:
            return "background-color: #f59e0b; color: #111827; font-weight: 600;"
        return "background-color: #dc2626; color: #ffffff; font-weight: 600;"

    styler = (
        df_pct.style.format("{:.0f}%")
        .map(_cell_style)
        .set_table_styles(
            [
                {
                    "selector": "th.col_heading",
                    "props": [
                        ("writing-mode", "vertical-rl"),
                        ("transform", "rotate(180deg)"),
                        ("white-space", "nowrap"),
                        ("font-size", "0.72rem"),
                        ("max-width", "2.2rem"),
                        ("min-width", "2.0rem"),
                        ("vertical-align", "bottom"),
                        ("padding", "6px 2px"),
                        ("background", "#f1f5f9"),
                    ],
                },
                {
                    "selector": "th.row_heading",
                    "props": [
                        ("position", "sticky"),
                        ("left", "0"),
                        ("z-index", "2"),
                        ("background", "#f8fafc"),
                        ("font-size", "0.85rem"),
                        ("white-space", "nowrap"),
                    ],
                },
                {
                    "selector": "td",
                    "props": [
                        ("min-width", "3.1rem"),
                        ("text-align", "center"),
                        ("font-size", "0.78rem"),
                        ("padding", "4px 2px"),
                    ],
                },
                {
                    "selector": "table",
                    "props": [("border-collapse", "separate"), ("border-spacing", "1px")],
                },
            ]
        )
    )
    return styler


def parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def main() -> None:
    st.set_page_config(page_title="Educator Insight Dashboard", layout="wide")
    st.markdown(
        """
<style>
.main-title {
  font-size: 2rem;
  font-weight: 800;
  color: #111827;
  margin-bottom: 0.2rem;
}
.subtitle {
  color: #374151;
  margin-bottom: 0.8rem;
}
.soft-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 10px 12px;
  background: linear-gradient(180deg, #ffffff 0%, #f9fafb 100%);
}
.band-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 8px 0 12px 0;
}
.band-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 0.85rem;
  font-weight: 700;
  color: #fff;
}
.matrix-scroll {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  padding: 8px 8px 4px 8px;
  box-shadow: inset 0 1px 0 rgba(15, 23, 42, 0.04);
}
.matrix-scroll::-webkit-scrollbar {
  height: 10px;
}
.matrix-scroll::-webkit-scrollbar-thumb {
  background: #94a3b8;
  border-radius: 999px;
}
.matrix-hint {
  color: #64748b;
  font-size: 0.84rem;
  margin: 4px 0 8px 0;
}
.risk-card {
  border: 1px solid #fca5a5;
  border-left: 6px solid #ef4444;
  border-radius: 14px;
  padding: 14px 14px 12px 14px;
  background: linear-gradient(180deg, #fff5f5 0%, #fff1f2 100%);
  box-shadow: 0 6px 16px rgba(127, 29, 29, 0.12);
  transition: transform .15s ease, box-shadow .15s ease;
  min-height: 220px;
}
.risk-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(127, 29, 29, 0.18);
}
.risk-student {
  font-weight: 800;
  font-size: 1.20rem;
  line-height: 1.2;
  color: #7f1d1d;
}
.risk-topic {
  margin-top: 3px;
  font-size: 1.00rem;
  font-weight: 700;
  color: #991b1b;
}
.risk-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.risk-pill {
  display: inline-block;
  color: #fff;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.2px;
}
.risk-score {
  font-size: 1.05rem;
  font-weight: 800;
  color: #7f1d1d;
}
.risk-reason {
  margin-top: 10px;
  color: #111827;
  font-size: 0.97rem;
}
.risk-metrics {
  margin-top: 10px;
  color: #374151;
  font-size: 0.94rem;
  line-height: 1.35;
}
/* Keep Streamlit dataframe / HTML tables horizontally scrollable */
div[data-testid="stDataFrame"] {
  overflow-x: auto !important;
}
div[data-testid="stDataFrame"] table {
  width: max-content !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="main-title">📘 Educator Insight Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">High-density G6–G9 mastery matrix (57 topics), at-risk alerts, and conversational engagement.</div>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("⚙️ Data Source")
        api_base = st.text_input("FastAPI Base URL", value=DEFAULT_API_BASE)
        api_timeout_s = st.number_input(
            "API timeout (seconds)",
            min_value=10.0,
            max_value=300.0,
            value=DEFAULT_API_TIMEOUT_S,
            step=5.0,
            help="Increase this if replay_logs requests are slow.",
        )
        mode = st.selectbox(
            "Mastery source mode",
            options=["replay_logs", "live_state"],
            index=0,
            help=(
                "replay_logs = recompute mastery by replaying synthetic logs "
                "(recommended baseline). "
                "live_state = current in-memory engine state since server start."
            ),
        )

        st.header("🧪 Classroom Slice")
        students_text = st.text_area(
            "Student IDs (one per line)",
            value="\n".join(DEFAULT_STUDENTS),
            height=150,
        )
        use_all_topics = st.checkbox(
            f"Use all hierarchy topics ({len(DEFAULT_TOPICS)} from Excel)",
            value=True,
            help="Loads topic columns from Data/Skill-Heirarchies-G6-G9.xlsx in curriculum order.",
        )
        if use_all_topics:
            topic_ids_ui = list(DEFAULT_TOPICS)
            st.caption(f"Loaded `{SKILL_HIERARCHY_XLSX.name}` → {len(topic_ids_ui)} topic columns.")
            with st.expander("Preview topic IDs", expanded=False):
                st.code("\n".join(topic_ids_ui), language="text")
        else:
            topics_text = st.text_area(
                "Topic IDs (one per line)",
                value="\n".join(DEFAULT_TOPICS[:12]),
                height=180,
            )
            topic_ids_ui = parse_lines(topics_text)
        run = st.button("🔄 Refresh Dashboard Data", type="primary")

    # Auto-load once on first render so the dashboard isn't blank.
    if "autoload_done" not in st.session_state:
        st.session_state.autoload_done = True
        run = True
    if "dashboard_data" not in st.session_state:
        st.session_state.dashboard_data = None

    student_ids = parse_lines(students_text)
    topic_ids = topic_ids_ui
    if not student_ids or not topic_ids:
        st.error("Please provide at least one student ID and one topic ID.")
        return

    should_reload = bool(run) or st.session_state.dashboard_data is None
    if should_reload:
        try:
            with st.spinner(
                "Loading mastery and at-risk analytics… "
                "(first load with 57 topics in replay_logs mode can take 1–2 minutes)"
            ):
                payload = fetch_mastery_matrix(
                    api_base,
                    student_ids,
                    topic_ids,
                    mode=mode,
                    timeout_s=float(api_timeout_s),
                )
                risk_payload = fetch_at_risk_students(
                    api_base,
                    student_ids,
                    topic_ids,
                    mode=mode,
                    timeout_s=float(api_timeout_s),
                )
        except requests.RequestException as exc:
            st.error(
                "Could not fetch mastery data from FastAPI. "
                "Make sure your API server is running (e.g., uvicorn main:app --reload)."
            )
            st.exception(exc)
            return
        st.session_state.dashboard_data = {
            "payload": payload,
            "risk_payload": risk_payload,
            "student_ids": student_ids,
            "topic_ids": topic_ids,
            "mode": mode,
            "api_base": api_base,
            "api_timeout_s": float(api_timeout_s),
        }
    else:
        data = st.session_state.dashboard_data
        payload = data["payload"]
        risk_payload = data["risk_payload"]
        student_ids = data["student_ids"]
        topic_ids = data["topic_ids"]
        mode = data["mode"]
        api_base = data["api_base"]
        api_timeout_s = data["api_timeout_s"]

    if not payload.get("success"):
        st.error(f"API returned an error: {payload}")
        return
    if not risk_payload.get("success"):
        st.error(f"At-risk analytics API returned an error: {risk_payload}")
        return

    df = matrix_to_dataframe(payload["mastery_matrix"], topic_ids=topic_ids)
    mastered_n = int((df >= BKT_MASTERED).sum().sum())
    learning_n = int(((df >= BKT_LEARNING) & (df < BKT_MASTERED)).sum().sum())
    at_risk_n = int((df < BKT_LEARNING).sum().sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students × Topics", f"{len(student_ids)} × {len(topic_ids)}")
    c2.metric("🟢 Mastered cells", mastered_n)
    c3.metric("🟠 Learning cells", learning_n)
    c4.metric("🔴 At-Risk cells", at_risk_n)
    st.markdown(
        f'<div class="soft-card"><b>Mode:</b> {mode} &nbsp;|&nbsp; '
        f"<b>Hierarchy source:</b> <code>{SKILL_HIERARCHY_XLSX.name}</code></div>",
        unsafe_allow_html=True,
    )

    st.markdown("## ⚠️ Priority Alerts: Students At-Risk")
    alerts = list(risk_payload.get("students") or [])
    if not alerts:
        st.success("No at-risk students detected for the selected slice.")
    else:
        immediate_n = sum(1 for a in alerts if int(a.get("risk_score") or 0) >= 80)
        high_n = sum(1 for a in alerts if 60 <= int(a.get("risk_score") or 0) < 80)
        watch_n = sum(1 for a in alerts if 40 <= int(a.get("risk_score") or 0) < 60)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Students flagged", len(alerts))
        k2.metric("Immediate Support", immediate_n)
        k3.metric("Needs Attention", high_n)
        k4.metric("Watchlist", watch_n)

        cols = st.columns(min(3, max(1, len(alerts))), gap="medium")
        for idx, alert in enumerate(alerts):
            col = cols[idx % len(cols)]
            with col:
                student = str(alert.get("student_id"))
                topic = str(alert.get("topic_id"))
                topic_lbl = _topic_label(topic)
                reason = str(alert.get("reason") or "At-Risk")
                risk_score = int(alert.get("risk_score") or 0)
                tier, tier_color = _risk_tier(risk_score)
                mastery_pct = float(alert.get("mastery_probability") or 0.0) * 100.0
                recent_perf_pct = (
                    float(alert.get("recent_performance_avg") or 0.0) * 100.0
                    if alert.get("recent_performance_avg") is not None
                    else None
                )
                if recent_perf_pct is None:
                    recent_status = "No recent quiz trend yet"
                elif recent_perf_pct < 40:
                    recent_status = "Recent quiz performance is weak"
                elif recent_perf_pct < 60:
                    recent_status = "Recent quiz performance is mixed"
                else:
                    recent_status = "Recent quiz performance is steady"
                if risk_score >= 80:
                    action_note = "Action now: teacher check-in and targeted support session."
                elif risk_score >= 60:
                    action_note = "Action this week: focused practice and quick follow-up."
                else:
                    action_note = "Watch closely: continue monitoring and guided practice."
                st.markdown(
                    f"""
<div class="risk-card">
  <div class="risk-student">{student}</div>
  <div class="risk-topic">{topic_lbl}</div>
  <div class="risk-row">
    <span class="risk-pill" style="background:{tier_color};">{tier} Risk</span>
    <span class="risk-score">Risk Score: {risk_score}%</span>
  </div>
  <div class="risk-reason"><b>Why flagged:</b> {reason}</div>
  <div class="risk-metrics">
    Current mastery: <b>{mastery_pct:.1f}%</b><br/>
    Recent quiz status: <b>{recent_status}</b><br/>
    Suggested action: <b>{action_note}</b>
  </div>
</div>
                    """,
                    unsafe_allow_html=True,
                )

    st.divider()
    st.subheader("🌡️ Classroom Mastery Matrix (High-Density)")
    unknown = payload.get("unknown_topic_ids") or []
    if unknown:
        st.warning(
            "Some topic IDs are unknown to the BKT model and are shown as blank: "
            + ", ".join(map(str, unknown))
        )

    st.markdown(
        """
<div class="band-legend">
  <span class="band-pill" style="background:#dc2626;">🔴 At Risk — P(L) &lt; 0.50</span>
  <span class="band-pill" style="background:#f59e0b; color:#111827;">🟠 Learning — 0.50 ≤ P(L) ≤ 0.79</span>
  <span class="band-pill" style="background:#16a34a;">🟢 Mastered — P(L) ≥ 0.80</span>
</div>
<div class="matrix-hint">Scroll horizontally inside the frames below to inspect all topic columns without overlapping headers.</div>
        """,
        unsafe_allow_html=True,
    )

    fig = build_heatmap(
        df,
        title=f"Classroom Mastery Heatmap · {len(topic_ids)} topics · mode={payload.get('mode')}",
    )
    st.markdown('<div class="matrix-scroll">', unsafe_allow_html=True)
    st.plotly_chart(
        fig,
        use_container_width=False,
        config={
            "displayModeBar": True,
            "scrollZoom": True,
            "responsive": False,
        },
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("#### Mastery grid (scrollable)")
    st.caption(
        "Cell colors follow the same strict BKT bands. Column headers are topic IDs from "
        "`Skill-Heirarchies-G6-G9.xlsx` (rotated to fit 57 columns)."
    )
    st.dataframe(
        style_mastery_dataframe(df),
        use_container_width=False,
        height=min(520, 80 + 36 * max(1, len(df.index))),
    )

    with st.expander("Curriculum reference key (topic_id → label)", expanded=False):
        key_df = pd.DataFrame(
            {
                "topic_id": topic_ids,
                "curriculum_reference": [_topic_label(t) for t in topic_ids],
                "band_counts_mastered": [(df[t] >= BKT_MASTERED).sum() for t in topic_ids],
                "band_counts_learning": [
                    ((df[t] >= BKT_LEARNING) & (df[t] < BKT_MASTERED)).sum() for t in topic_ids
                ],
                "band_counts_at_risk": [(df[t] < BKT_LEARNING).sum() for t in topic_ids],
            }
        )
        st.dataframe(key_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🧠 Student Deep-Dive (Micro-Interaction Logs)")
    selected_student = st.selectbox(
        "Select a student for drill-down",
        options=student_ids,
        index=0,
        help="Choose one learner to inspect mastery timeline, misconceptions, and recent tutoring transcript.",
    )
    if not selected_student:
        return

    try:
        with st.spinner("Loading student profile..."):
            profile = fetch_student_profile(
                api_base=api_base,
                user_id=str(selected_student),
                mode=mode,
                timeout_s=float(api_timeout_s),
            )
    except requests.RequestException as exc:
        st.error("Could not fetch student profile from FastAPI.")
        st.exception(exc)
        return

    if not profile.get("success"):
        st.error(f"Student profile API returned an error: {profile}")
        return

    e1, e2, e3 = st.columns(3)
    e1.metric("Student", str(profile.get("user_id")))
    e2.metric("Assessment attempts", int(profile.get("assessment_insights", {}).get("attempts_count") or 0))
    f_avg = profile.get("engagement_metrics", {}).get("average_frustration_cue")
    e3.metric("Avg frustration cue", f"{float(f_avg):.2f}" if f_avg is not None else "N/A")

    # Per-selected-student band summary across the dense matrix row
    if selected_student in df.index:
        row = df.loc[selected_student]
        s1, s2, s3 = st.columns(3)
        s1.metric("Topics mastered", int((row >= BKT_MASTERED).sum()))
        s2.metric("Topics learning", int(((row >= BKT_LEARNING) & (row < BKT_MASTERED)).sum()))
        s3.metric("Topics at risk", int((row < BKT_LEARNING).sum()))

    timeline = list(profile.get("mastery_timeline_last_10_attempts") or [])
    engagement_timeline = list(profile.get("engagement_timeline_last_10_turns") or [])
    if timeline:
        t_df = pd.DataFrame(timeline)
        t_df["attempt_no"] = list(range(1, len(t_df) + 1))
        t_df["mastery_pct"] = pd.to_numeric(t_df["mastery_probability"], errors="coerce") * 100.0
        t_df["topic_label"] = t_df["topic_id"].map(_topic_label)
        timeline_fig = go.Figure()
        timeline_fig.add_trace(
            go.Scatter(
                x=t_df["attempt_no"],
                y=t_df["mastery_pct"],
                mode="lines+markers",
                marker=dict(size=8, color="#2563eb"),
                line=dict(width=2.5, color="#2563eb"),
                text=t_df["topic_label"],
                hovertemplate=(
                    "Attempt %{x}<br>Topic: %{text}<br>"
                    "Mastery: %{y:.1f}%<extra></extra>"
                ),
            )
        )
        timeline_fig.update_layout(
            title="Mastery Timeline (Last 10 Attempts)",
            xaxis_title="Attempt (oldest -> latest)",
            yaxis_title="Mastery (%)",
            yaxis=dict(range=[0, 100]),
            height=340,
            margin=dict(l=50, r=20, t=55, b=45),
        )
        st.plotly_chart(timeline_fig, use_container_width=True)
    else:
        st.info("No mastery timeline available for this student yet.")

    # Process analytics: chatbot conversational performance vs formal mastery trajectory.
    if timeline or engagement_timeline:
        compare_fig = go.Figure()
        if timeline:
            m_df = pd.DataFrame(timeline)
            m_df["idx"] = list(range(1, len(m_df) + 1))
            m_df["mastery_pct"] = pd.to_numeric(m_df["mastery_probability"], errors="coerce") * 100.0
            compare_fig.add_trace(
                go.Scatter(
                    x=m_df["idx"],
                    y=m_df["mastery_pct"],
                    mode="lines+markers",
                    name="Official Mastery (Assessment/BKT)",
                    line=dict(color="#1d4ed8", width=2.5),
                    marker=dict(size=7),
                    hovertemplate="Step %{x}<br>Mastery: %{y:.1f}%<extra></extra>",
                )
            )
        if engagement_timeline:
            e_df = pd.DataFrame(engagement_timeline)
            e_df["idx"] = list(range(1, len(e_df) + 1))
            e_df["engagement_pct"] = pd.to_numeric(e_df["interaction_score"], errors="coerce") * 100.0
            compare_fig.add_trace(
                go.Scatter(
                    x=e_df["idx"],
                    y=e_df["engagement_pct"],
                    mode="lines+markers",
                    name="Engagement (interaction_score)",
                    line=dict(color="#f97316", width=2.5, dash="dot"),
                    marker=dict(size=7),
                    hovertemplate="Turn %{x}<br>Engagement: %{y:.1f}%<extra></extra>",
                )
            )
        compare_fig.update_layout(
            title="Conversational Accuracy vs. Official Mastery",
            xaxis_title="Recent sequence index",
            yaxis_title="Percentage (%)",
            yaxis=dict(range=[0, 100]),
            height=340,
            margin=dict(l=50, r=20, t=55, b=45),
        )
        st.plotly_chart(compare_fig, use_container_width=True)

        mastery_avg = (
            float(pd.to_numeric(pd.DataFrame(timeline)["mastery_probability"], errors="coerce").mean())
            if timeline
            else None
        )
        engagement_avg = profile.get("engagement_average_last_10")
        if (
            mastery_avg is not None
            and isinstance(engagement_avg, (int, float))
            and mastery_avg < 0.50
            and float(engagement_avg) >= 0.70
        ):
            st.info(
                "Student is participating well in dialogue but struggling with formal assessments."
            )

    misconceptions_df = pd.DataFrame(profile.get("assessment_insights", {}).get("most_frequent_distractor_tags") or [])
    if not misconceptions_df.empty:
        misconceptions_df = misconceptions_df.sort_values("count", ascending=False)
        m_fig = go.Figure(
            data=[
                go.Bar(
                    x=misconceptions_df["count"],
                    y=misconceptions_df["tag"],
                    orientation="h",
                    marker_color="#ef4444",
                    text=misconceptions_df["count"],
                    textposition="outside",
                    hovertemplate="Tag: %{y}<br>Count: %{x}<extra></extra>",
                )
            ]
        )
        m_fig.update_layout(
            title="Misconception Cloud (Frequent Distractor Tags)",
            xaxis_title="Frequency",
            yaxis_title="Distractor Tag",
            yaxis=dict(autorange="reversed"),
            height=360,
            margin=dict(l=80, r=20, t=55, b=45),
        )
        st.plotly_chart(m_fig, use_container_width=True)
    else:
        st.info("No distractor tags available yet (no incorrect attempts detected).")

    with st.expander("Chat Review: Last 5 Socratic interactions", expanded=False):
        chat_rows = list(profile.get("chat_history_last_5") or [])
        if not chat_rows:
            st.caption("No chat transcript available yet for this student in current server session.")
        else:
            for i, row in enumerate(chat_rows, start=1):
                confusion_flag = " 🚩 Critical Confusion" if bool(row.get("critical_confusion")) else ""
                score_val = row.get("interaction_score")
                score_txt = f"{float(score_val):.2f}" if isinstance(score_val, (int, float)) else "N/A"
                st.markdown(
                    f"**Turn {i}** | Topic: `{_topic_label(str(row.get('topic_id') or ''))}` | "
                    f"Score: `{score_txt}`{confusion_flag} | Time: `{row.get('timestamp') or 'n/a'}`"
                )
                st.markdown(f"- Student: {row.get('student_message') or ''}")
                st.markdown(f"- Tutor: {row.get('tutor_hint') or ''}")
                st.divider()
        flagged = list(profile.get("critical_confusion_turns") or [])
        if flagged:
            st.warning(
                f"Misconception Tracker: {len(flagged)} critical confusion turn(s) detected "
                "(interaction_score < 0.30)."
            )


if __name__ == "__main__":
    main()
