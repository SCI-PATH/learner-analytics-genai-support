"""
Epic 4: Educator Insight Dashboard (Streamlit)

Classroom Mastery Heatmap:
- Calls FastAPI endpoint /api/v1/mastery/matrix for real mastery scores.
- Shows students (rows) vs topics (columns).
- Color bands:
  * Red    : < 0.50
  * Orange : 0.50 - 0.79
  * Green  : >= 0.80
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_API_TIMEOUT_S = 90.0

DEFAULT_STUDENTS = [
    "user_001",
    "user_002",
    "user_003",
    "user_004",
    "user_005",
]

DEFAULT_TOPICS = [
    "G6_S1_ORG_CHARS",
    "G6_S1_ORG_CLASS",
    "G6_S2_MAT_PROPS",
    "G6_S2_MAT_STATES",
    "G6_S4_ENE_SOURCES",
    "G6_S8_ELE_CIRCUITS",
    "G6_S8_ELE_CONDINS",
]


TOPIC_LABELS = {
    "G6_S1_ORG_CHARS": "Organisms: Characteristics",
    "G6_S1_ORG_CLASS": "Organisms: Classification",
    "G6_S2_MAT_PROPS": "Materials: Properties",
    "G6_S2_MAT_STATES": "Materials: States of Matter",
    "G6_S4_ENE_SOURCES": "Energy: Sources",
    "G6_S8_ELE_CIRCUITS": "Electricity: Circuits",
    "G6_S8_ELE_CONDINS": "Electricity: Conductors vs Insulators",
}


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
    # Keep teacher-selected column order.
    missing_cols = [t for t in topic_ids if t not in df.columns]
    for col in missing_cols:
        df[col] = 0.0
    df = df[topic_ids]
    df = df.apply(pd.to_numeric, errors="coerce")
    df.index.name = "student_id"
    return df


def _topic_label(topic_id: str) -> str:
    return TOPIC_LABELS.get(topic_id, topic_id)


def _risk_tier(score: int) -> tuple[str, str]:
    if score >= 80:
        return "Immediate Support", "#7f1d1d"
    if score >= 60:
        return "Needs Attention", "#9a3412"
    if score >= 40:
        return "Watchlist", "#854d0e"
    return "Monitor", "#14532d"


def build_heatmap(df: pd.DataFrame, title: str) -> go.Figure:
    # Teacher-facing percentage view (0-100) while preserving the same thresholds.
    z = (df * 100.0).to_numpy()
    x_ids = list(df.columns)
    x = [_topic_label(t) for t in x_ids]
    y = list(df.index)

    # Piecewise colors for richer teacher-facing bands:
    # [0,35) deep red, [35,50) light red,
    # [50,65) amber, [65,80) yellow-green, [80,100] green
    colorscale = [
        [0.00, "#991b1b"],
        [0.3499, "#991b1b"],
        [0.35, "#dc2626"],
        [0.4999, "#dc2626"],
        [0.50, "#f59e0b"],
        [0.6499, "#f59e0b"],
        [0.65, "#eab308"],
        [0.7999, "#eab308"],
        [0.80, "#16a34a"],
        [1.00, "#2ca02c"],
    ]

    text = [[f"{v:.0f}%" for v in row] for row in z]
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x,
            y=y,
            text=text,
            texttemplate="%{text}",
            colorscale=colorscale,
            zmin=0.0,
            zmax=100.0,
            colorbar=dict(
                title="Mastery (%)",
                tickvals=[18, 43, 58, 72, 90],
                ticktext=[
                    "🆘 Critical (0-34%)",
                    "🔴 High Risk (35-49%)",
                    "🟠 Support (50-64%)",
                    "🟡 Progressing (65-79%)",
                    "🟢 Strong (80-100%)",
                ],
            ),
            hovertemplate="Student: %{y}<br>Topic: %{x}<br>Mastery: %{z:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Science Topics",
        yaxis_title="Student IDs",
        margin=dict(l=60, r=40, t=70, b=60),
        height=max(420, 70 + 45 * max(1, len(y))),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#fffdf8",
        font=dict(size=14),
    )
    fig.update_xaxes(tickangle=-22, tickfont=dict(size=12))
    fig.update_yaxes(tickfont=dict(size=12))
    return fig


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
</style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="main-title">📘 Educator Insight Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Track mastery, at-risk alerts, and conversational engagement in one view.</div>',
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
        topics_text = st.text_area(
            "Topic IDs (one per line)",
            value="\n".join(DEFAULT_TOPICS),
            height=180,
        )
        run = st.button("🔄 Refresh Dashboard Data", type="primary")

    # Auto-load once on first render so the dashboard isn't blank.
    if "autoload_done" not in st.session_state:
        st.session_state.autoload_done = True
        run = True
    if "dashboard_data" not in st.session_state:
        st.session_state.dashboard_data = None

    student_ids = parse_lines(students_text)
    topic_ids = parse_lines(topics_text)
    if not student_ids or not topic_ids:
        st.error("Please provide at least one student ID and one topic ID.")
        return

    should_reload = bool(run) or st.session_state.dashboard_data is None
    if should_reload:
        try:
            with st.spinner("Loading mastery and at-risk analytics..."):
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

    c1, c2 = st.columns([2, 1])
    with c2:
        st.markdown(
            f'<div class="soft-card"><b>Mode:</b> {mode}<br/><b>Students:</b> {len(student_ids)} | <b>Topics:</b> {len(topic_ids)}</div>',
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
    st.subheader("🌡️ Classroom Mastery Heatmap")
    unknown = payload.get("unknown_topic_ids") or []
    if unknown:
        st.warning(
            "Some topic IDs are unknown to the BKT model and are shown as blank: "
            + ", ".join(map(str, unknown))
        )

    df = matrix_to_dataframe(payload["mastery_matrix"], topic_ids=topic_ids)
    fig = build_heatmap(df, title=f"Classroom Mastery Heatmap ({payload.get('mode')})")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown(
        """
**Legend**
- 🆘 **Critical Alert** (`0% - 34%`): Immediate intervention needed.
- 🔴 **High Risk** (`35% - 49%`): Strong support required this week.
- 🟠 **Support Zone** (`50% - 64%`): Reinforce concepts with guided practice.
- 🟡 **Progressing** (`65% - 79%`): Encourage continued practice and challenge.
- 🟢 **Strong Mastery** (`80% - 100%`): Student is on track for independent tasks.
"""
    )

    # Teacher-readable table in percentage format.
    st.dataframe((df * 100.0).style.format("{:.1f}%"), use_container_width=True)

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
            st.warning(f"Misconception Tracker: {len(flagged)} critical confusion turn(s) detected (interaction_score < 0.30).")


if __name__ == "__main__":
    main()
