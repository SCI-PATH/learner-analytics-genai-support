"""
Simple Streamlit UI to test the Socratic tutor API.

Run:
    streamlit run tutor-chatbot.py
"""

from __future__ import annotations

import html
import os
from typing import Any

import requests
import streamlit as st


DEFAULT_API_BASE = os.environ.get("TUTOR_API_BASE", "http://127.0.0.1:8000")
API_ENDPOINTS = ["/tutor/hint-auto-topic", "/tutor/hint"]


def _call_tutor_api(
    api_base: str,
    user_id: str,
    message: str,
    topic_id: str | None,
    *,
    conversation_history: list[dict[str, str]] | None = None,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """
    Try the exact FastAPI endpoints defined in main.py.
    """
    api_base = api_base.rstrip("/")
    endpoints = API_ENDPOINTS

    last_error = "No response."
    for ep in endpoints:
        url = f"{api_base}{ep}"

        if ep == "/tutor/hint":
            payload = {
                "user_id": user_id,
                "topic_id": topic_id or "G6_S8_ELE_CIRCUITS",
                "student_answer": message,
                "context_k": 4,
            }
        else:
            payload = {
                "user_id": user_id,
                "student_answer": message,
                "context_k": 4,
            }
            if topic_id:
                payload["topic_id"] = topic_id
        if conversation_history:
            payload["conversation_history"] = conversation_history

        try:
            r = requests.post(url, json=payload, timeout=timeout_sec)
            if r.status_code == 404:
                # Try next compatible endpoint.
                last_error = f"{url} -> 404 Not Found"
                continue
            r.raise_for_status()
            out = r.json()
            out["_used_endpoint"] = ep
            return out
        except requests.RequestException as exc:
            last_error = f"{url} -> {exc}"

    return {"success": False, "error": last_error}


def _render_bubble(role: str, content: str) -> None:
    is_user = role == "user"
    css_role = "user" if is_user else "assistant"
    avatar = "🧑‍🎓" if is_user else "🧠🤖"
    label = "Student" if is_user else "Socratic Tutor"
    safe = html.escape(str(content))
    st.markdown(
        f"""
<div class="msg-row {css_role}">
  <div class="msg-bubble {css_role}">
    <div class="msg-head">{avatar} {label}</div>
    <div>{safe}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="Socratic Tutor Chatbot", page_icon="🧪", layout="wide")
    st.markdown(
        """
<style>
.chat-shell {
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f9fafb 100%);
  padding: 12px 14px;
}
.msg-row {
  display: flex;
  margin: 8px 0;
  width: 100%;
}
.msg-row.user { justify-content: flex-end; }
.msg-row.assistant { justify-content: flex-start; }
.msg-bubble {
  max-width: 78%;
  border-radius: 14px;
  padding: 10px 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  font-size: 0.96rem;
  line-height: 1.4;
}
.msg-bubble.user {
  background: #1d4ed8;
  color: #ffffff;
  border-bottom-right-radius: 6px;
}
.msg-bubble.assistant {
  background: #ffffff;
  color: #111827;
  border: 1px solid #e5e7eb;
  border-bottom-left-radius: 6px;
}
.msg-head {
  font-size: 0.80rem;
  font-weight: 700;
  margin-bottom: 5px;
  opacity: 0.95;
}
.chat-note {
  color: #4b5563;
  font-size: 0.84rem;
  margin-top: 6px;
}
</style>
        """,
        unsafe_allow_html=True,
    )
    st.title("🧪 SCI-PATH Socratic Tutor Chatbot")
    st.caption("Local test UI for FastAPI + BKT + RAG Socratic hints")

    # Session state init
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "latest_mastery" not in st.session_state:
        st.session_state.latest_mastery = None
    if "latest_mode" not in st.session_state:
        st.session_state.latest_mode = None
    if "latest_topic" not in st.session_state:
        st.session_state.latest_topic = None
    if "latest_endpoint" not in st.session_state:
        st.session_state.latest_endpoint = None
    if "conversation_topic_id" not in st.session_state:
        st.session_state.conversation_topic_id = None
    if "last_tutor_debug" not in st.session_state:
        st.session_state.last_tutor_debug = None

    with st.sidebar:
        st.header("Learner State")
        user_id = st.text_input("user_id", value="student_demo")
        topic_id = st.text_input("topic_id (optional)", value="")
        lock_topic = st.toggle("Lock topic for this chat", value=True)
        api_base = st.text_input("API Base URL", value=DEFAULT_API_BASE)
        if st.button("Clear chat / New conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.latest_mastery = None
            st.session_state.latest_mode = None
            st.session_state.latest_topic = None
            st.session_state.latest_endpoint = None
            st.session_state.conversation_topic_id = None
            st.session_state.last_tutor_debug = None
            st.rerun()

        st.divider()
        mastery = st.session_state.latest_mastery
        mode = st.session_state.latest_mode
        resolved_topic = st.session_state.latest_topic
        used_ep = st.session_state.latest_endpoint

        if mastery is None:
            st.info("Send a message to see mastery.")
        else:
            st.metric("BKT Mastery", f"{float(mastery):.4f}")
            st.write(f"Hint mode: `{mode}`")
            st.write(f"Topic: `{resolved_topic}`")
            if used_ep:
                st.caption(f"Endpoint used: `{used_ep}`")

        with st.expander("Developer · BKT / LLM diagnostics", expanded=False):
            st.caption(
                "`interaction_score` is **chosen by the LLM** using the prompt rubric "
                "(comparing your message + retrieved textbook excerpts)—it is **not** a formula in Python."
            )
            st.caption(
                "**BKT from chat:** default `strict` policy only updates mastery on clear "
                "high/low scores; `quiz_only` disables dialogue updates entirely. "
                "Quiz always updates via `/api/v1/assessment-submit`."
            )
            dbg = st.session_state.last_tutor_debug
            if not dbg:
                st.info("Send a successful message to see `bkt_updated`, notes, and scores.")
            else:
                if dbg.get("error"):
                    st.error(str(dbg["error"]))
                else:
                    st.write("**Policy:** ", f"`{dbg.get('tutor_bkt_policy', 'unknown')}`")
                    st.write("**bkt_updated:** ", dbg.get("bkt_updated"))
                    st.write(
                        "**bkt_observation_label:** ",
                        dbg.get("bkt_observation_label"),
                        "(0/1 if applied for BKT step)",
                    )
                    note = dbg.get("bkt_update_note")
                    st.write("**bkt_update_note:** ", f"`{note}`" if note else "`None`")
                    st.write("**interaction_score** (model): ", dbg.get("interaction_score"))
                    st.write(
                        "**mastery_probability_before → after:** ",
                        f"{dbg.get('mastery_probability_before')} → "
                        f"{dbg.get('updated_mastery_probability', dbg.get('mastery_probability'))}",
                    )
                    risk = dbg.get("risk_flag")
                    if risk is not None:
                        st.write("**risk_flag:** ", risk)
                    ff = dbg.get("frustration_level_used")
                    if ff:
                        st.caption(
                            f"Frustration cue used: `{ff}` ({dbg.get('frustration_score_used')})"
                        )

    # Render chat history with custom two-sided bubble UI.
    st.markdown('<div class="chat-shell">', unsafe_allow_html=True)
    if not st.session_state.messages:
        st.markdown(
            '<div class="chat-note">💬 Start by asking a science question.</div>',
            unsafe_allow_html=True,
        )
    for msg in st.session_state.messages:
        _render_bubble(str(msg.get("role") or "assistant"), str(msg.get("content") or ""))
    st.markdown("</div>", unsafe_allow_html=True)

    user_msg = st.chat_input("Ask your science question...")
    if user_msg:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        # Keep the just-submitted student message visible immediately while spinner runs.
        st.markdown('<div class="chat-shell">', unsafe_allow_html=True)
        _render_bubble("user", user_msg)
        st.markdown("</div>", unsafe_allow_html=True)
        with st.spinner("Tutor is thinking..."):
            hist: list[dict[str, str]] = [
                {"role": str(m["role"]), "content": str(m["content"])}
                for m in st.session_state.messages[:-1]
            ]
            response = _call_tutor_api(
                api_base=api_base,
                user_id=user_id.strip() or "student_demo",
                message=user_msg,
                topic_id=topic_id.strip()
                or (st.session_state.conversation_topic_id if lock_topic else None),
                conversation_history=hist or None,
            )

            if not response.get("success"):
                err = response.get("error", "Unknown error")
                assistant_text = f"API error: {err}"
                st.session_state.last_tutor_debug = {"success": False, "error": err}
            else:
                assistant_text = response.get("hint_text", "(No hint returned)")
                st.session_state.latest_mastery = response.get("mastery_probability")
                st.session_state.latest_mode = response.get("hint_mode")
                st.session_state.latest_topic = (
                    response.get("topic_id_resolved")
                    or response.get("topic_id")
                    or topic_id
                    or "unknown"
                )
                if topic_id.strip():
                    st.session_state.conversation_topic_id = topic_id.strip()
                elif lock_topic and st.session_state.latest_topic and st.session_state.latest_topic != "unknown":
                    st.session_state.conversation_topic_id = st.session_state.latest_topic
                st.session_state.latest_endpoint = response.get("_used_endpoint")
                st.session_state.last_tutor_debug = {
                    "success": True,
                    "tutor_bkt_policy": response.get("tutor_bkt_policy"),
                    "bkt_updated": response.get("bkt_updated"),
                    "bkt_update_note": response.get("bkt_update_note"),
                    "bkt_observation_label": response.get("bkt_observation_label"),
                    "interaction_score": response.get("interaction_score"),
                    "interaction_score_effective": response.get("interaction_score_effective"),
                    "mastery_probability_before": response.get("mastery_probability_before"),
                    "updated_mastery_probability": response.get("updated_mastery_probability"),
                    "mastery_probability": response.get("mastery_probability"),
                    "risk_flag": response.get("risk_flag"),
                    "frustration_level_used": response.get("frustration_level_used"),
                    "frustration_score_used": response.get("frustration_score_used"),
                }

        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        st.rerun()


if __name__ == "__main__":
    main()

