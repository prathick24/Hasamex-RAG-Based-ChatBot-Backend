import os

import httpx
import streamlit as st

API_BASE_URL = os.getenv("HASAMEX_API_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(600.0, connect=10.0)


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
        data, error = fetch_or_error(lambda: get_json("/api/v1/analysis/interview-guide"))
        if error:
            st.error(error)
        elif data:
            for entry in data:
                with st.expander(f"Q{entry['question_id']}. {entry['question']}"):
                    for answer in entry["answers"]:
                        if answer.get("citations"):
                            summary = f"{answer['expert']} \u2014 {answer['answer']}"
                            with st.expander(summary):
                                render_citations(answer["citations"])
                        else:
                            st.markdown(f"**{answer['expert']}:** {answer['answer']}")
        else:
            st.info("No interview guide data available.")

    with tab_themes:
        st.header("Themes & Disagreements")
        data, error = fetch_or_error(lambda: get_json("/api/v1/analysis/themes"))
        if error:
            st.error(error)
        elif data:
            for entry in data:
                with st.expander(f"{entry['topic']}"):
                    if not entry.get("themes"):
                        st.info("No themes identified for this topic.")
                        continue
                    for theme in entry["themes"]:
                        label = theme["type"]
                        emoji = {
                            "Consensus": "\u2705",
                            "Disagreement": "\U0001f504",
                            "Emphasis": "\u2696\ufe0f",
                        }.get(label, "\U0001f4cb")
                        st.markdown(f"{emoji} **{label}** \u2014 {theme['summary']}")
                        if theme.get("citations"):
                            with st.expander("Sources"):
                                render_citations(theme["citations"])
                        st.divider()
        else:
            st.info("No theme analysis available.")

    with tab_chat:
        st.header("Ask a Question")
        st.caption(
            "Free-form questions are answered with citations. "
            "Ask for an *exact quote* (e.g. \u201cquote what Anna Keller said about barriers\u201d) "
            "to get verbatim transcript excerpts without any AI rewriting."
        )

        question = st.chat_input("Ask about adoption, barriers, ROI, training, timelines\u2026")
        if question:
            st.chat_message("user").write(question)
            payload: dict = {"question": question}
            data, error = fetch_or_error(lambda: post_json("/api/v1/qa/ask", payload))
            if error:
                st.chat_message("assistant").error(error)
            elif data.get("mode") == "quote":
                with st.chat_message("assistant"):
                    render_quote_mode(data)
            else:
                with st.chat_message("assistant"):
                    render_answer_mode(data)


if __name__ == "__main__":
    main()