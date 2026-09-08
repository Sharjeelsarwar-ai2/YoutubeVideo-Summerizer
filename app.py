import html
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import requests
import streamlit as st


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="YouTube Video Summarizer",
    page_icon="▶️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        * {
            font-family: 'Inter', sans-serif;
        }

        .stApp {
            background:
                radial-gradient(circle at 10% 10%, rgba(255,255,255,0.04), transparent 25%),
                radial-gradient(circle at 90% 20%, rgba(255,255,255,0.03), transparent 25%),
                #080808;
            color: #f5f5f5;
        }

        .block-container {
            max-width: 1200px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        .hero {
            text-align: center;
            padding: 2rem 1rem 1.5rem;
        }

        .hero-badge {
            display: inline-block;
            padding: 0.45rem 0.9rem;
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 999px;
            background: rgba(255,255,255,0.05);
            color: #cfcfcf;
            font-size: 0.8rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }

        .hero h1 {
            font-size: 3.1rem;
            line-height: 1.05;
            font-weight: 800;
            margin: 0;
            letter-spacing: -0.04em;
        }

        .hero p {
            max-width: 720px;
            margin: 1rem auto 0;
            color: #9d9d9d;
            font-size: 1rem;
            line-height: 1.7;
        }

        .glass-card {
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 22px;
            padding: 1.4rem;
            box-shadow: 0 20px 60px rgba(0,0,0,0.25);
            backdrop-filter: blur(18px);
        }

        .section-title {
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 0.9rem;
        }

        .result-card {
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 1.35rem;
            margin-top: 1rem;
        }

        .result-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 0.8rem;
        }

        .timestamp {
            display: inline-block;
            padding: 0.28rem 0.55rem;
            margin-right: 0.45rem;
            margin-bottom: 0.4rem;
            border-radius: 8px;
            background: rgba(255,255,255,0.08);
            color: #ffffff;
            font-size: 0.82rem;
            font-weight: 600;
        }

        .video-id {
            color: #888;
            font-size: 0.78rem;
        }

        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 15px;
            padding: 0.7rem;
        }

        .small-muted {
            color: #888;
            font-size: 0.82rem;
        }

        .stButton > button {
            border-radius: 12px;
            font-weight: 700;
            min-height: 2.7rem;
        }

        .stTextInput > div > div > input {
            border-radius: 12px;
        }

        .stSelectbox > div > div {
            border-radius: 12px;
        }

        .footer {
            text-align: center;
            color: #666;
            font-size: 0.8rem;
            padding-top: 2rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
# ============================================================

if "transcript_data" not in st.session_state:
    st.session_state.transcript_data = None

if "video_id" not in st.session_state:
    st.session_state.video_id = None

if "video_url" not in st.session_state:
    st.session_state.video_url = None

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None


# ============================================================
# HELPERS
# ============================================================

def get_secret(name: str):
    """Safely read a Streamlit secret."""
    try:
        value = st.secrets.get(name)
        if value:
            return str(value).strip()
    except Exception:
        pass

    return None


def extract_video_id(url: str):
    """Extract a YouTube video ID from common YouTube URL formats."""
    if not url:
        return None

    url = url.strip()

    # Direct 11-character video ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")

        # youtube.com/watch?v=...
        if host in {"youtube.com", "m.youtube.com"}:
            query = parse_qs(parsed.query)
            video_id = query.get("v", [None])[0]

            if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return video_id

            # /shorts/ID
            parts = [p for p in parsed.path.split("/") if p]

            if len(parts) >= 2 and parts[0].lower() in {
                "shorts",
                "embed",
                "live",
            }:
                candidate = parts[1]

                if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                    return candidate

        # youtu.be/ID
        if host == "youtu.be":
            candidate = parsed.path.strip("/").split("/")[0]

            if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return candidate

    except Exception:
        return None

    return None


def format_timestamp(seconds):
    """Convert seconds to HH:MM:SS or MM:SS."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "00:00"

    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    return f"{minutes:02d}:{secs:02d}"


def normalize_timestamp(value):
    """
    Normalize timestamp values.

    Supadata may return timestamps in seconds or milliseconds
    depending on response format.
    """
    if value is None:
        return 0.0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    # Treat very large values as milliseconds.
    if number > 100000:
        number /= 1000

    return max(0.0, number)


def extract_transcript_segments(data):
    """
    Extract transcript segments from several possible response formats.
    """

    content = None

    if isinstance(data, dict):
        if isinstance(data.get("content"), list):
            content = data["content"]

        elif isinstance(data.get("segments"), list):
            content = data["segments"]

        elif isinstance(data.get("items"), list):
            content = data["items"]

        elif isinstance(data.get("transcript"), list):
            content = data["transcript"]

        elif isinstance(data.get("data"), dict):
            nested = data["data"]

            if isinstance(nested.get("content"), list):
                content = nested["content"]

            elif isinstance(nested.get("segments"), list):
                content = nested["segments"]

    elif isinstance(data, list):
        content = data

    if not content:
        return []

    segments = []

    for item in content:
        if not isinstance(item, dict):
            continue

        text = (
            item.get("text")
            or item.get("content")
            or item.get("value")
            or ""
        )

        text = str(text).strip()

        if not text:
            continue

        start = (
            item.get("start")
            if item.get("start") is not None
            else item.get("offset")
        )

        duration = item.get("duration", 0)

        segments.append(
            {
                "text": text,
                "start": normalize_timestamp(start),
                "duration": normalize_timestamp(duration),
            }
        )

    return segments


# ============================================================
# SUPADATA TRANSCRIPT
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_transcript(video_url: str):
    """
    Fetch YouTube transcript from Supadata.
    Cached for one hour.
    """

    api_key = get_secret("SUPADATA_API_KEY")

    if not api_key:
        raise RuntimeError(
            "SUPADATA_API_KEY is not configured. "
            "Add it under Streamlit Cloud → Settings → Secrets."
        )

    endpoint = "https://api.supadata.ai/v1/youtube/transcript"

    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }

    params = {
        "url": video_url
    }

    try:
        response = requests.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=45,
        )

    except requests.Timeout:
        raise RuntimeError(
            "Supadata timed out while fetching the transcript."
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not connect to Supadata: {exc}"
        )

    if response.status_code == 401:
        raise RuntimeError(
            "Supadata rejected the API key. Check SUPADATA_API_KEY."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "Supadata denied this request. Check your Supadata API access."
        )

    if response.status_code == 404:
        raise RuntimeError(
            "Supadata could not find a transcript for this YouTube video."
        )

    if response.status_code == 429:
        raise RuntimeError(
            "Supadata rate limit reached. Please try again later."
        )

    if response.status_code >= 500:
        raise RuntimeError(
            f"Supadata server error ({response.status_code}). Please try again."
        )

    if not response.ok:
        try:
            details = response.json()
        except Exception:
            details = response.text

        raise RuntimeError(
            f"Supadata returned HTTP {response.status_code}: {details}"
        )

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            "Supadata returned an invalid JSON response."
        )

    segments = extract_transcript_segments(data)

    if not segments:
        raise RuntimeError(
            "Supadata returned no usable transcript segments for this video."
        )

    return segments


def build_transcript_text(segments):
    """Build plain transcript text."""
    return " ".join(
        segment["text"]
        for segment in segments
        if segment["text"].strip()
    )


def build_timestamped_transcript(segments):
    """Build transcript while preserving timestamps."""
    lines = []

    for segment in segments:
        timestamp = format_timestamp(segment["start"])
        text = segment["text"].strip()

        if text:
            lines.append(f"[{timestamp}] {text}")

    return "\n".join(lines)


# ============================================================
# TOKEN-SAFE CHUNKING
# ============================================================

def split_timestamped_transcript(
    segments,
    max_chars=7000,
):
    """
    Split transcript into smaller chunks.

    We deliberately use a conservative character limit because
    Groq's current TPM limit is 8,000 tokens.
    """

    chunks = []
    current_lines = []
    current_chars = 0

    for segment in segments:

        timestamp = format_timestamp(segment["start"])
        text = segment["text"].strip()

        if not text:
            continue

        line = f"[{timestamp}] {text}"

        # Large individual transcript segment
        if len(line) > max_chars:
            words = text.split()
            partial = []
            partial_chars = 0

            for word in words:
                extra = len(word) + 1

                if partial and partial_chars + extra > max_chars:
                    chunks.append(
                        {
                            "start": segment["start"],
                            "text": (
                                f"[{timestamp}] "
                                + " ".join(partial)
                            ),
                        }
                    )

                    partial = []
                    partial_chars = 0

                partial.append(word)
                partial_chars += extra

            if partial:
                chunks.append(
                    {
                        "start": segment["start"],
                        "text": (
                            f"[{timestamp}] "
                            + " ".join(partial)
                        ),
                    }
                )

            continue

        if current_lines and current_chars + len(line) + 1 > max_chars:
            chunks.append(
                {
                    "start": current_lines[0]["start"],
                    "text": "\n".join(
                        item["text"] for item in current_lines
                    ),
                }
            )

            current_lines = []
            current_chars = 0

        current_lines.append(
            {
                "start": segment["start"],
                "text": line,
            }
        )

        current_chars += len(line) + 1

    if current_lines:
        chunks.append(
            {
                "start": current_lines[0]["start"],
                "text": "\n".join(
                    item["text"] for item in current_lines
                ),
            }
        )

    return chunks


# ============================================================
# GROQ
# ============================================================

def ask_groq(
    user_prompt,
    system_prompt,
    max_tokens=900,
    retries=3,
):
    """
    Call Groq safely with retry handling.
    """

    api_key = get_secret("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. "
            "Add it under Streamlit Cloud → Settings → Secrets."
        )

    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "openai/gpt-oss-120b",
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    }

    last_error = None

    for attempt in range(retries):

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=90,
            )

        except requests.Timeout:
            last_error = "Groq request timed out."

            if attempt < retries - 1:
                time.sleep(2)
                continue

            raise RuntimeError(last_error)

        except requests.RequestException as exc:
            last_error = f"Could not connect to Groq: {exc}"

            if attempt < retries - 1:
                time.sleep(2)
                continue

            raise RuntimeError(last_error)

        if response.status_code == 401:
            raise RuntimeError(
                "Groq rejected the API key. Check GROQ_API_KEY."
            )

        if response.status_code == 403:
            raise RuntimeError(
                "Groq denied the request. Check your API access."
            )

        if response.status_code == 413:
            raise RuntimeError(
                "Groq rejected the request because it is too large. "
                "The transcript chunk is still too big."
            )

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")

            try:
                wait_time = float(retry_after)
            except (TypeError, ValueError):
                wait_time = 8

            if attempt < retries - 1:
                time.sleep(min(max(wait_time, 2), 30))
                continue

            raise RuntimeError(
                "Groq rate limit reached. Please try again shortly."
            )

        if response.status_code >= 500:
            last_error = (
                f"Groq server error ({response.status_code})."
            )

            if attempt < retries - 1:
                time.sleep(3)
                continue

            raise RuntimeError(last_error)

        if not response.ok:
            try:
                error_data = response.json()
                error_message = (
                    error_data.get("error", {}).get(
                        "message",
                        str(error_data),
                    )
                )
            except Exception:
                error_message = response.text

            raise RuntimeError(
                f"Groq returned HTTP {response.status_code}: "
                f"{error_message}"
            )

        try:
            data = response.json()

            return data["choices"][0]["message"]["content"]

        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError(
                "Groq returned an unexpected response format."
            )

    raise RuntimeError(last_error or "Groq request failed.")


# ============================================================
# CHUNK SUMMARIZATION
# ============================================================

def summarize_transcript_chunk(
    chunk_text,
    chunk_number,
    total_chunks,
):
    """
    Summarize one small transcript chunk.

    The chunk is intentionally small so the request remains
    below the Groq TPM limit.
    """

    system_prompt = """
You are a YouTube transcript analysis assistant.

Summarize only the information provided.
Do not invent facts.
Do not add information that is not present.

Preserve:
- important facts
- names
- examples
- arguments
- conclusions
- useful details

Keep the output compact.
"""

    user_prompt = f"""
This is transcript chunk {chunk_number} of {total_chunks}.

Create a concise but informative summary of this chunk.

The transcript contains timestamps in square brackets.
Keep important timestamps when they are useful.

TRANSCRIPT CHUNK:

{chunk_text}
"""

    return ask_groq(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=750,
    )


# ============================================================
# FINAL ANALYSIS
# ============================================================

def generate_final_analysis(
    chunk_summaries,
    options,
    summary_type,
    original_segments,
):
    """
    Generate the final analysis using compact chunk summaries.

    This prevents sending the entire original transcript to Groq.
    """

    tasks = []

    if options["summary"]:
        tasks.append(
            f"Create a {summary_type.lower()} overall summary."
        )

    if options["takeaways"]:
        tasks.append(
            "Extract the most important key takeaways."
        )

    if options["topics"]:
        tasks.append(
            "Identify the main topics discussed."
        )

    if options["sentiment"]:
        tasks.append(
            "Analyze the overall sentiment and tone."
        )

    if options["actions"]:
        tasks.append(
            "Extract clear action items, recommendations, "
            "or things the viewer should do."
        )

    # Build a compact list of REAL timestamps that actually exist.
    timestamp_reference = []

    for segment in original_segments:
        timestamp_reference.append(
            f"[{format_timestamp(segment['start'])}]"
        )

    timestamp_reference = list(
        dict.fromkeys(timestamp_reference)
    )

    if options["timestamps"]:
        tasks.append(
            "Identify important moments and their timestamps. "
            "Use ONLY timestamps from the supplied timestamp list. "
            "Never invent a timestamp."
        )

    compact_sources = []

    for index, summary in enumerate(chunk_summaries, start=1):
        compact_sources.append(
            f"CHUNK {index}:\n{summary}"
        )

    source_text = "\n\n".join(compact_sources)

    system_prompt = """
You are an expert YouTube video analysis assistant.

Use only the supplied transcript summaries and timestamp
reference information.

Do not invent facts.
Do not invent timestamps.

Write clear, useful, well-structured results.

Use Markdown headings where appropriate.
"""

    timestamp_section = ""

    if options["timestamps"]:
        timestamp_section = f"""

REAL TIMESTAMPS AVAILABLE:

{", ".join(timestamp_reference)}

You MUST select timestamps only from this list.
"""

    user_prompt = f"""
Perform the following requested tasks:

{chr(10).join("- " + task for task in tasks)}

{timestamp_section}

TRANSCRIPT CHUNK SUMMARIES:

{source_text}
"""

    result = ask_groq(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=1200,
    )

    return result


# ============================================================
# OPTIONAL SENTIMENT / TOPIC EXTRACTION FALLBACK
# ============================================================

def clean_markdown_for_html(text):
    """Basic HTML escaping for safe display."""
    return html.escape(text).replace("\n", "<br>")


# ============================================================
# HEADER
# ============================================================

st.markdown(
    """
    <div class="hero">
        <div class="hero-badge">AI-POWERED VIDEO ANALYSIS</div>

        <h1>YouTube Video Summarizer</h1>

        <p>
            Turn long YouTube videos into concise summaries,
            key takeaways, topics, timestamps, sentiment,
            and actionable insights.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# INPUT CARD
# ============================================================

st.markdown('<div class="glass-card">', unsafe_allow_html=True)

st.markdown(
    '<div class="section-title">YouTube Video</div>',
    unsafe_allow_html=True,
)

video_url = st.text_input(
    "Paste YouTube URL",
    value=st.session_state.video_url or "",
    placeholder="https://www.youtube.com/watch?v=...",
    label_visibility="collapsed",
)

col1, col2 = st.columns([1, 1])

with col1:
    fetch_clicked = st.button(
        "Fetch Transcript",
        use_container_width=True,
        type="primary",
    )

with col2:
    clear_clicked = st.button(
        "Clear",
        use_container_width=True,
    )

st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# CLEAR
# ============================================================

if clear_clicked:
    st.session_state.transcript_data = None
    st.session_state.video_id = None
    st.session_state.video_url = None
    st.session_state.analysis_result = None
    st.rerun()


# ============================================================
# FETCH TRANSCRIPT
# ============================================================

if fetch_clicked:

    video_id = extract_video_id(video_url)

    if not video_id:
        st.error(
            "Please enter a valid YouTube URL."
        )

    else:
        try:
            with st.spinner(
                "Fetching transcript..."
            ):
                segments = get_transcript(video_url)

            st.session_state.transcript_data = segments
            st.session_state.video_id = video_id
            st.session_state.video_url = video_url
            st.session_state.analysis_result = None

            st.success(
                "Transcript fetched successfully."
            )

        except Exception as exc:
            st.error(str(exc))


# ============================================================
# DISPLAY TRANSCRIPT INFO
# ============================================================

segments = st.session_state.transcript_data

if segments:

    transcript_text = build_transcript_text(segments)
    timestamped_transcript = build_timestamped_transcript(segments)

    total_chars = len(transcript_text)
    total_words = len(transcript_text.split())

    # Approximate token count.
    approximate_tokens = max(
        1,
        int(total_chars / 4),
    )

    st.markdown(
        "<br>",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric(
            "Transcript Words",
            f"{total_words:,}",
        )

    with m2:
        st.metric(
            "Segments",
            f"{len(segments):,}",
        )

    with m3:
        st.metric(
            "Approx. Tokens",
            f"{approximate_tokens:,}",
        )

    with m4:
        first_time = segments[0]["start"]
        last_segment = segments[-1]
        last_time = (
            last_segment["start"]
            + last_segment.get("duration", 0)
        )

        st.metric(
            "Video Length",
            format_timestamp(last_time or first_time),
        )

    # --------------------------------------------------------
    # Advanced settings
    # --------------------------------------------------------

    st.markdown(
        "<br>",
        unsafe_allow_html=True,
    )

    with st.expander(
        "⚙️ Advanced Settings",
        expanded=False,
    ):

        s1, s2 = st.columns(2)

        with s1:
            summary_type = st.selectbox(
                "Summary Type",
                [
                    "Brief Summary",
                    "Detailed Summary",
                    "Bullet Points",
                    "Key Timestamps",
                ],
                index=0,
            )

        with s2:
            st.caption(
                "Long transcripts are automatically divided "
                "into smaller Groq-safe chunks."
            )

        st.markdown(
            "### Additional Analysis"
        )

        a1, a2, a3, a4 = st.columns(4)

        with a1:
            extra_takeaways = st.checkbox(
                "Key Takeaways",
                value=True,
            )

        with a2:
            extra_topics = st.checkbox(
                "Topic Extraction",
                value=False,
            )

        with a3:
            extra_sentiment = st.checkbox(
                "Sentiment Analysis",
                value=False,
            )

        with a4:
            extra_actions = st.checkbox(
                "Action Items",
                value=False,
            )

    # ========================================================
    # GENERATE BUTTON
    # ========================================================

    st.markdown("<br>", unsafe_allow_html=True)

    generate_clicked = st.button(
        "✨ Generate Summary",
        use_container_width=True,
        type="primary",
    )

    # ========================================================
    # GENERATE
    # ========================================================

    if generate_clicked:

        options = {
            "summary": True,
            "timestamps": summary_type == "Key Timestamps",
            "takeaways": extra_takeaways,
            "topics": extra_topics,
            "sentiment": extra_sentiment,
            "actions": extra_actions,
        }

        chunks = split_timestamped_transcript(
            segments,
            max_chars=7000,
        )

        if not chunks:
            st.error(
                "The transcript could not be divided into analysis chunks."
            )

        else:

            st.info(
                f"Long-transcript protection: "
                f"{len(chunks)} smaller chunk(s) will be analyzed."
            )

            chunk_summaries = []

            progress = st.progress(0)
            status = st.empty()

            generation_failed = False

            for index, chunk in enumerate(chunks):

                status.write(
                    f"Analyzing transcript chunk "
                    f"{index + 1} of {len(chunks)}..."
                )

                try:
                    result = summarize_transcript_chunk(
                        chunk["text"],
                        index + 1,
                        len(chunks),
                    )

                    chunk_summaries.append(result)

                except Exception as exc:
                    generation_failed = True
                    st.error(
                        f"Failed on chunk {index + 1}: {exc}"
                    )
                    break

                progress.progress(
                    (index + 1) / len(chunks)
                )

                # Keep requests spread out to avoid TPM bursts.
                if index < len(chunks) - 1:
                    time.sleep(3)

            progress.empty()
            status.empty()

            if not generation_failed:

                with st.spinner(
                    "Creating final analysis..."
                ):

                    try:
                        final_result = generate_final_analysis(
                            chunk_summaries,
                            options,
                            summary_type,
                            segments,
                        )

                        st.session_state.analysis_result = (
                            final_result
                        )

                    except Exception as exc:
                        st.error(
                            f"Final Groq analysis failed: {exc}"
                        )

    # ========================================================
    # RESULT
    # ========================================================

    if st.session_state.analysis_result:

        st.markdown(
            "<br>",
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="result-card">
                <div class="result-title">
                    ✨ AI Analysis
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            st.session_state.analysis_result
        )

        # ----------------------------------------------------
        # Timestamp section
        # ----------------------------------------------------

        if summary_type == "Key Timestamps":

            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown(
                """
                <div class="result-card">
                    <div class="result-title">
                        ⏱️ Available Real Timestamps
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Show transcript timestamps independently so the
            # timestamps always come from actual transcript data.
            timestamp_html = ""

            seen_timestamps = set()

            for segment in segments:

                timestamp = format_timestamp(
                    segment["start"]
                )

                if timestamp not in seen_timestamps:
                    seen_timestamps.add(timestamp)

                    timestamp_html += (
                        f'<span class="timestamp">'
                        f'{html.escape(timestamp)}'
                        f"</span>"
                    )

            st.markdown(
                timestamp_html,
                unsafe_allow_html=True,
            )

    # ========================================================
    # FULL TRANSCRIPT
    # ========================================================

    st.markdown("<br>", unsafe_allow_html=True)

    with st.expander(
        "📜 View Full Timestamped Transcript",
        expanded=False,
    ):

        st.text_area(
            "Transcript",
            timestamped_transcript,
            height=450,
            label_visibility="collapsed",
        )

    # ========================================================
    # DOWNLOAD
    # ========================================================

    report_parts = []

    report_parts.append(
        "YOUTUBE VIDEO SUMMARIZER"
    )

    report_parts.append(
        f"Generated: "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    report_parts.append(
        f"Video URL: {st.session_state.video_url}"
    )

    report_parts.append(
        f"Video ID: {st.session_state.video_id}"
    )

    report_parts.append(
        "\n\n"
        "==================== AI ANALYSIS ====================\n"
    )

    if st.session_state.analysis_result:
        report_parts.append(
            st.session_state.analysis_result
        )
    else:
        report_parts.append(
            "No analysis generated yet."
        )

    report_parts.append(
        "\n\n"
        "==================== TIMESTAMPED TRANSCRIPT ====================\n"
    )

    report_parts.append(
        timestamped_transcript
    )

    report_text = "\n".join(report_parts)

    st.download_button(
        "⬇️ Download TXT Report",
        data=report_text,
        file_name=(
            f"youtube_summary_"
            f"{st.session_state.video_id}.txt"
        ),
        mime="text/plain",
        use_container_width=True,
    )


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    """
    <div class="footer">
        YouTube Video Summarizer · Powered by Supadata + Groq
    </div>
    """,
    unsafe_allow_html=True,
)
