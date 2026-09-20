import json
import os

import httpx
import streamlit as st

API_BASE_URL = os.getenv("HASAMEX_API_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(600.0, connect=10.0)

GUIDE_SESSION_KEY = "guide_state"
THEMES_SESSION_KEY = "themes_state"
CHAT_SESSION_KEY = "chat_messages"
CHAT_SCROLL_HEIGHT = 420

THEME_EMOJI = {
    "Consensus": "\u2705",
    "Disagreement": "\U0001f504",
    "Emphasis": "\u2696\ufe0f",
}


def api_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_URL, timeout=TIMEOUT)


def get_json(path: str) -> dict | list:
    with api_client() as client:
        response = client.get(path)
        response.raise_for_status()
        return response.json()


def post_json(path: str, payload: dict) -> dict:
    with api_client() as client:
        response = client.post(path, json=payload)
        response.raise_for_status()
        return response.json()


def fetch_or_error(callback):
    try:
        return callback(), None
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        return None, f"Backend error ({exc.response.status_code}): {detail}"
    except httpx.HTTPError as exc:
        return None, f"Cannot reach backend at {API_BASE_URL}: {exc}"


def set_page() -> None:
    st.set_page_config(
        page_title="Hasamex Transcript Analysis",
        page_icon="\U0001f50d",
        layout="wide",
    )
    st.markdown(
        """
        <style>
            [data-testid="stToolbar"] button[kind="headerButton"] {
                display: none;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_citations(citations: list[dict]) -> None:
    if not citations:
        return
    for citation in citations:
        st.markdown(
            f"**{citation['expert_name']}** ({citation['market']}) \u2014 @{citation['timestamp']}\n"
            f"`{citation['transcript_file']}`\n\n"
            f"> \"{citation['quote']}\""
        )
        st.divider()


def render_answer_mode(data: dict) -> None:
    st.markdown(f"**{data['answer']}**")
    if data.get("citations"):
        with st.expander("Sources"):
            render_citations(data["citations"])


def render_quote_mode(data: dict) -> None:
    quotes = data.get("quotes") or []
    if not quotes:
        st.info(data.get("answer") or "No exact quote found.")
        return
    for quote in quotes:
        status = quote.get("verification_status", "verified")
        icon = "\u2705" if status == "verified" else "\u26a0\ufe0f"
        st.markdown(
            f"> {quote['quote']}\n\n"
            f"{icon} **{quote['expert_name']}** ({quote['market']}) \u2014 @{quote['timestamp']}\n\n"
            f"`{quote['transcript_file']}`"
        )
        st.divider()


def render_chat_message(message: dict) -> None:
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
        return
    if message.get("mode") == "error":
        st.chat_message("assistant").error(message["content"])
        return
    if message.get("mode") == "quote":
        with st.chat_message("assistant"):
            render_quote_mode(message["data"])
    else:
        with st.chat_message("assistant"):
            render_answer_mode(message["data"])


def render_guide_entries(entries: list[dict]) -> None:
    for entry in entries:
        with st.expander(f"Q{entry['question_id']}. {entry['question']}"):
            for answer in entry["answers"]:
                if answer.get("citations"):
                    summary = f"{answer['expert']} \u2014 {answer['answer']}"
                    with st.expander(summary):
                        render_citations(answer["citations"])
                else:
                    st.markdown(f"**{answer['expert']}:** {answer['answer']}")


def render_progressive_question(
    qid: int, label: str, answers: list[dict], placeholder
) -> None:
    lines = [f"#### Q{qid}. {label}"]
    if not answers:
        lines.append("_Waiting for expert answers…_")
    else:
        for answer in answers:
            lines.append(f"**{answer['expert']}:** {answer['answer']}")
            for citation in answer.get("citations", []):
                citation_line = (
                    f"> \u201c{citation['quote']}\u201d \u2014 {citation['expert_name']} "
                    f"({citation['market']}) @{citation['timestamp']} "
                    f"`{citation['transcript_file']}`"
                )
                lines.append(citation_line)
    placeholder.markdown("\n\n".join(lines))


def stream_guide() -> list[dict]:
    """Stream the interview guide, rendering answers as each batch arrives."""
    placeholders: dict[int, object] = {}
    labels: dict[int, str] = {}
    answers_by_q: dict[int, list[dict]] = {}
    error: str | None = None

    with api_client() as client, client.stream(
        "GET", "/api/v1/analysis/interview-guide/stream"
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["type"] == "meta":
                    for question in event["questions"]:
                        qid = question["question_id"]
                        labels[qid] = question["question"]
                        answers_by_q[qid] = []
                        with st.expander(f"Q{qid}. {question['question']}"):
                            placeholders[qid] = st.empty()
                            render_progressive_question(qid, labels[qid], [], placeholders[qid])
                elif event["type"] == "batch":
                    for answer in event["answers"]:
                        qid = answer["question_id"]
                        if qid in answers_by_q:
                            answers_by_q[qid].append(answer)
                            placeholder = placeholders[qid]
                            if placeholder is not None:
                                render_progressive_question(
                                    qid, labels.get(qid, ""), answers_by_q[qid], placeholder
                                )
                elif event["type"] == "error":
                    error = event.get("detail", "An error occurred during streaming.")
                    break
                elif event["type"] == "done":
                    break

    if error:
        st.error(f"Backend error: {error}")
        return []

    st.success("All expert answers loaded.")
    return [
        {
            "question_id": qid,
            "question": labels[qid],
            "answers": answers_by_q[qid],
        }
        for qid in answers_by_q
    ]


def render_theme_entries(entries: list[dict]) -> None:
    for entry in entries:
        with st.expander(f"{entry['topic']}"):
            if entry.get("error"):
                st.warning(
                    "Oops - we hit a snag generating this one. "
                    "Please use the Refresh button and we'll try again."
                )
                continue
            if not entry.get("themes"):
                st.info("No themes identified for this topic.")
                continue
            for theme in entry["themes"]:
                label = theme["type"]
                emoji = THEME_EMOJI.get(label, "\U0001f4cb")
                st.markdown(f"{emoji} **{label}** \u2014 {theme['summary']}")
                if theme.get("citations"):
                    with st.expander("Sources"):
                        render_citations(theme["citations"])
                st.divider()


def render_progressive_theme_section(
    topic: str, themes: list[dict], placeholder, final: bool = False, error: bool = False
) -> None:
    lines = [f"#### {topic}"]
    if error:
        lines.append(
            "Oops - we hit a snag generating this one. "
            "Please use the Refresh button and we'll try again."
        )
    elif not themes:
        lines.append(
            "No themes identified for this topic." if final else "_Waiting for analysis…_"
        )
    else:
        for theme in themes:
            icon = THEME_EMOJI.get(theme["type"], "\U0001f4cb")
            lines.append(f"{icon} **{theme['type']}** \u2014 {theme['summary']}")
            for citation in theme.get("citations", []):
                citation_line = (
                    f"> \u201c{citation['quote']}\u201d \u2014 {citation['expert_name']} "
                    f"({citation['market']}) @{citation['timestamp']} "
                    f"`{citation['transcript_file']}`"
                )
                lines.append(citation_line)
    placeholder.markdown("\n\n".join(lines))


def stream_themes() -> list[dict]:
    """Stream the theme analysis, rendering each topic as it completes."""
    placeholders: dict[int, object] = {}
    ordered_topics: list[str] = []
    themes_by_topic: dict[str, list[dict]] = {}
    themes_error: dict[str, bool] = {}
    error: str | None = None

    with api_client() as client, client.stream(
        "GET", "/api/v1/analysis/themes/stream"
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event["type"] == "meta":
                for item in event["topics"]:
                    ordered_topics.append(item["topic"])
                    themes_by_topic[item["topic"]] = []
                    with st.expander(item["topic"]):
                        placeholders[item["index"]] = st.empty()
                        render_progressive_theme_section(
                            item["topic"], [], placeholders[item["index"]]
                        )
            elif event["type"] == "topic":
                topic = event["topic"]
                if topic in themes_by_topic:
                    themes_by_topic[topic] = event["themes"]
                    themes_error[topic] = event.get("error", False)
                    placeholder = placeholders.get(ordered_topics.index(topic) + 1)
                    if placeholder is not None:
                        render_progressive_theme_section(
                            topic,
                            event["themes"],
                            placeholder,
                            final=True,
                            error=event.get("error", False),
                        )
            elif event["type"] == "error":
                error = event.get("detail", "An error occurred during streaming.")
                break
            elif event["type"] == "done":
                break

    if error:
        st.error(f"Backend error: {error}")
        return []

    st.success("All theme analyses loaded.")
    return [
        {
            "topic": topic,
            "themes": themes_by_topic.get(topic, []),
            "error": themes_error.get(topic, False),
        }
        for topic in ordered_topics
    ]


def fetch_guide_entries() -> tuple[list[dict], str | None]:
    """Stream the guide; returns (entries, error). error is None on success."""
    try:
        return stream_guide(), None
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        return [], f"Backend error ({exc.response.status_code}): {detail}"
    except httpx.HTTPError as exc:
        return [], f"Cannot reach backend at {API_BASE_URL}: {exc}"


def fetch_theme_entries() -> tuple[list[dict], str | None]:
    """Stream the themes; returns (entries, error). error is None on success."""
    try:
        return stream_themes(), None
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        return [], f"Backend error ({exc.response.status_code}): {detail}"
    except httpx.HTTPError as exc:
        return [], f"Cannot reach backend at {API_BASE_URL}: {exc}"


def _render_tab(state_key: str, state_label: str, retry_key: str, stream_fn, render_fn) -> None:
    state = st.session_state.get(state_key)
    if state is not None and state.get("status") == "error":
        st.error(state.get("error", "Unknown error"))
        if st.button("Retry", key=retry_key):
            st.session_state.pop(state_key, None)
            st.rerun()
        return

    if state is not None and state.get("status") == "done":
        if state.get("entries"):
            render_fn(state["entries"])
            st.success(f"All {state_label} loaded.")
        else:
            st.info(f"No {state_label} data returned by the backend.")
        return

    entries, error = stream_fn()
    if error:
        st.session_state[state_key] = {"status": "error", "error": error, "entries": []}
        st.error(f"Could not load {state_label}: {error}")
        return
    st.session_state[state_key] = {"status": "done", "entries": entries}
    if not entries:
        st.info(f"No {state_label} data returned by the backend.")


def render_chat_tab() -> None:
    st.header("Ask a Question")
    st.caption(
        "Free-form questions are answered with citations. "
        "Ask for an *exact quote* (e.g. \u201cquote what Anna Keller said about barriers\u201d) "
        "to get verbatim transcript excerpts without any AI rewriting."
    )

    messages = st.session_state.setdefault(CHAT_SESSION_KEY, [])

    pending_question = st.session_state.pop("pending_question", None)
    if pending_question:
        messages.append({"role": "user", "content": pending_question})
        data, error = fetch_or_error(
            lambda: post_json("/api/v1/qa/ask", {"question": pending_question})
        )
        if error:
            messages.append({"role": "assistant", "mode": "error", "content": error})
        else:
            messages.append(
                {"role": "assistant", "mode": data.get("mode", "answer"), "data": data}
            )

    with st.container(height=CHAT_SCROLL_HEIGHT):
        for message in messages:
            render_chat_message(message)

    question = st.chat_input("Ask about adoption, barriers, ROI, training, timelines\u2026")
    if question:
        st.session_state["pending_question"] = question
        st.rerun()


def main() -> None:
    set_page()
    st.title("\U0001f4ca Hasamex \u2014 Expert-Call Transcript Analysis")
    st.caption("European Robotic Surgery Market | Backed by verbatim quotes with timestamps")

    tab_guide, tab_themes, tab_chat = st.tabs(
        ["Interview Guide Answers", "Themes & Disagreements", "Ask a Question"]
    )

    with tab_guide:
        st.header("Interview Guide Answers")
        st.caption("Answers per expert, grounded in each transcript with source citations.")
        _render_tab(
            state_key=GUIDE_SESSION_KEY,
            state_label="interview guide answers",
            retry_key="retry_guide",
            stream_fn=fetch_guide_entries,
            render_fn=render_guide_entries,
        )

    with tab_themes:
        st.header("Themes & Disagreements")
        st.caption("Cross-expert themes with source citations.")
        _render_tab(
            state_key=THEMES_SESSION_KEY,
            state_label="theme analyses",
            retry_key="retry_themes",
            stream_fn=fetch_theme_entries,
            render_fn=render_theme_entries,
        )

    with tab_chat:
        render_chat_tab()


if __name__ == "__main__":
    main()