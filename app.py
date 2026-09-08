
import html
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================
#
# Streamlit Cloud:
# App → Settings → Secrets
#
# Add:
#
# GROQ_API_KEY = "gsk_..."
# SUPADATA_API_KEY = "..."
#
# ============================================================

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

SUPADATA_URL = "https://api.supadata.ai/v1/youtube/transcript"


def get_secret(name):
    """Safely read a Streamlit secret."""
    try:
        value = st.secrets.get(name, "")
        return str(value).strip()
    except Exception:
        return ""


GROQ_API_KEY = get_secret("GROQ_API_KEY")
SUPADATA_API_KEY = get_secret("SUPADATA_API_KEY")


# ============================================================
# URL HELPERS
# ============================================================

def extract_video_id(url):
    """Extract a YouTube video ID from common YouTube URL formats."""

    if not url:
        return None

    url = url.strip()

    try:
        parsed = urlparse(url)

        hostname = (parsed.hostname or "").lower()

        # youtube.com/watch?v=...
        if hostname in (
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
        ):
            video_id = parse_qs(parsed.query).get("v", [None])[0]

            if video_id:
                return video_id[:11]

        # youtu.be/VIDEO_ID
        if hostname == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]

            if video_id:
                return video_id[:11]

        # youtube.com/shorts/VIDEO_ID
        if hostname in ("youtube.com", "www.youtube.com"):
            parts = parsed.path.strip("/").split("/")

            if len(parts) >= 2 and parts[0].lower() == "shorts":
                return parts[1][:11]

        # youtube.com/embed/VIDEO_ID
        if hostname in ("youtube.com", "www.youtube.com"):
            parts = parsed.path.strip("/").split("/")

            if len(parts) >= 2 and parts[0].lower() == "embed":
                return parts[1][:11]

    except Exception:
        return None

    return None


def format_timestamp(seconds):
    """Convert seconds into HH:MM:SS or MM:SS."""

    try:
        seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "00:00"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    return f"{minutes:02d}:{secs:02d}"


# ============================================================
# TRANSCRIPT NORMALIZATION
# ============================================================

def normalize_transcript_response(data):
    """
    Convert different transcript response shapes into:

        [
            {
                "text": "...",
                "start": 0.0,
                "duration": 2.5
            },
            ...
        ]

    This keeps timestamp information instead of throwing it away.
    """

    if not isinstance(data, dict):
        return [], "Transcript API returned an unexpected response."

    # Most useful/expected shape.
    content = data.get("content")

    # Some APIs wrap transcript in a nested object.
    if content is None and isinstance(data.get("transcript"), dict):
        content = data["transcript"].get("content")

    # Other possible response names.
    if content is None:
        content = data.get("segments")

    if content is None:
        content = data.get("items")

    if content is None and isinstance(data.get("transcript"), list):
        content = data["transcript"]

    if not isinstance(content, list):
        return [], "No transcript segments were returned."

    segments = []

    for item in content:
        if not isinstance(item, dict):
            continue

        text = (
            item.get("text")
            or item.get("content")
            or item.get("snippet")
            or ""
        )

        if not isinstance(text, str):
            text = str(text)

        text = text.strip()

        if not text:
            continue

        start = (
            item.get("start")
            if item.get("start") is not None
            else item.get("startTime")
        )

        duration = (
            item.get("duration")
            if item.get("duration") is not None
            else item.get("dur")
        )

        # Some transcript providers return milliseconds.
        try:
            start = float(start or 0)

            if start > 100000:
                start = start / 1000

        except (TypeError, ValueError):
            start = 0.0

        try:
            duration = float(duration or 0)

            if duration > 100000:
                duration = duration / 1000

        except (TypeError, ValueError):
            duration = 0.0

        segments.append(
            {
                "text": text,
                "start": start,
                "duration": duration,
            }
        )

    if not segments:
        return [], "The transcript was empty."

    return segments, None


def build_transcript_text(segments):
    """Build clean transcript text for AI processing."""

    return " ".join(segment["text"] for segment in segments)


def build_timestamped_transcript(segments):
    """Build transcript while retaining timestamps."""

    lines = []

    for segment in segments:
        timestamp = format_timestamp(segment["start"])
        lines.append(f"[{timestamp}] {segment['text']}")

    return "\n".join(lines)


# ============================================================
# SUPADATA TRANSCRIPT
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_transcript(video_url):
    """
    Fetch YouTube transcript through Supadata.

    This avoids making the transcript request directly from
    Streamlit Cloud to YouTube.
    """

    if not SUPADATA_API_KEY:
        return None, None, (
            "SUPADATA_API_KEY is not configured. "
            "Add it to Streamlit Cloud → Settings → Secrets."
        )

    video_id = extract_video_id(video_url)

    if not video_id:
        return None, None, "Invalid YouTube URL."

    params = {
        "url": video_url,
    }

    headers = {
        "x-api-key": SUPADATA_API_KEY,
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            SUPADATA_URL,
            params=params,
            headers=headers,
            timeout=45,
        )

    except requests.exceptions.Timeout:
        return None, None, (
            "The transcript service timed out. "
            "Please try again."
        )

    except requests.exceptions.ConnectionError:
        return None, None, (
            "Could not connect to the transcript service. "
            "Check your internet connection or try again."
        )

    except requests.exceptions.RequestException as exc:
        return None, None, f"Transcript service request failed: {exc}"

    # --------------------------------------------------------
    # HTTP ERROR HANDLING
    # --------------------------------------------------------

    if response.status_code == 401:
        return None, None, (
            "Supadata rejected the API key. "
            "Check SUPADATA_API_KEY in Streamlit Secrets."
        )

    if response.status_code == 403:
        return None, None, (
            "Supadata denied this request. "
            "Check your API key and account permissions."
        )

    if response.status_code == 404:
        return None, None, (
            "Transcript was not found for this video."
        )

    if response.status_code == 429:
        return None, None, (
            "Transcript API rate limit reached. "
            "Please wait and try again."
        )

    if response.status_code >= 500:
        return None, None, (
            "The transcript service is temporarily unavailable. "
            "Please try again later."
        )

    if response.status_code != 200:
        try:
            error_data = response.json()
            message = (
                error_data.get("message")
                or error_data.get("error")
                or response.text
            )
        except Exception:
            message = response.text

        return None, None, (
            f"Transcript service returned HTTP "
            f"{response.status_code}: {message}"
        )

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    try:
        data = response.json()
    except ValueError:
        return None, None, (
            "Transcript service returned invalid JSON."
        )

    segments, error = normalize_transcript_response(data)

    if error:
        return None, None, error

    full_text = build_transcript_text(segments)
    timestamped_text = build_timestamped_transcript(segments)

    if not full_text.strip():
        return None, None, "Transcript was empty."

    return segments, timestamped_text, None


# ============================================================
# GROQ
# ============================================================

def groq_request(messages, max_tokens=3000, retries=2):
    """Make a robust Groq API request."""

    if not GROQ_API_KEY:
        return None, (
            "GROQ_API_KEY is not configured. "
            "Add it to Streamlit Cloud → Settings → Secrets."
        )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": max_tokens,
    }

    for attempt in range(retries + 1):

        try:
            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=90,
            )

        except requests.exceptions.Timeout:
            if attempt < retries:
                time.sleep(2)
                continue

            return None, (
                "Groq request timed out. "
                "Please try again."
            )

        except requests.exceptions.ConnectionError:
            if attempt < retries:
                time.sleep(2)
                continue

            return None, (
                "Could not connect to Groq. "
                "Please try again."
            )

        except requests.exceptions.RequestException as exc:
            return None, f"Groq request failed: {exc}"

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if response.status_code == 200:

            try:
                data = response.json()

                content = (
                    data["choices"][0]["message"]["content"]
                )

                if not content:
                    return None, "Groq returned an empty response."

                return content.strip(), None

            except (KeyError, IndexError, TypeError, ValueError):
                return None, (
                    "Groq returned an unexpected response format."
                )

        # ----------------------------------------------------
        # AUTH
        # ----------------------------------------------------

        if response.status_code == 401:
            return None, (
                "Invalid Groq API key. "
                "Check GROQ_API_KEY in Streamlit Secrets."
            )

        # ----------------------------------------------------
        # RATE LIMIT
        # ----------------------------------------------------

        if response.status_code == 429:

            if attempt < retries:

                retry_after = response.headers.get("Retry-After")

                try:
                    wait_seconds = float(retry_after)
                except (TypeError, ValueError):
                    wait_seconds = 3 * (attempt + 1)

                wait_seconds = min(wait_seconds, 20)

                time.sleep(wait_seconds)
                continue

            return None, (
                "Groq rate limit reached. "
                "Please wait a little and try again."
            )

        # ----------------------------------------------------
        # OTHER ERRORS
        # ----------------------------------------------------

        try:
            error_data = response.json()

            message = (
                error_data.get("error", {}).get("message")
                if isinstance(error_data.get("error"), dict)
                else error_data.get("message")
            )

            if not message:
                message = response.text

        except Exception:
            message = response.text

        return None, (
            f"Groq returned HTTP {response.status_code}: "
            f"{message}"
        )

    return None, "Groq request failed."


# ============================================================
# AI ANALYSIS
# ============================================================

def generate_analysis(
    transcript,
    timestamped_transcript,
    summary_type,
    include_takeaways,
    include_topics,
    include_sentiment,
    include_actions,
):
    """
    Generate all requested analysis in ONE Groq request.

    This is much better than making 5 separate requests.
    """

    analysis_requirements = []

    if summary_type == "Brief Summary":
        analysis_requirements.append(
            "summary: Write a clear 2–3 sentence summary."
        )

    elif summary_type == "Detailed Summary":
        analysis_requirements.append(
            "summary: Write a comprehensive summary using "
            "well-structured paragraphs."
        )

    elif summary_type == "Bullet Points":
        analysis_requirements.append(
            "summary: Summarize the video using clear bullet points."
        )

    elif summary_type == "Key Timestamps":
        analysis_requirements.append(
            "summary: Identify the most important sections of the "
            "video and include their REAL timestamps. "
            "Use timestamps from the supplied timestamped transcript. "
            "Do not invent timestamps."
        )

    if include_takeaways:
        analysis_requirements.append(
            "takeaways: Give the top 5 specific and practical "
            "key takeaways."
        )

    if include_topics:
        analysis_requirements.append(
            "topics: List the main topics and themes discussed."
        )

    if include_sentiment:
        analysis_requirements.append(
            "sentiment: Briefly describe the overall tone and "
            "sentiment of the video."
        )

    if include_actions:
        analysis_requirements.append(
            "actions: Extract concrete action items, tasks, "
            "steps, or recommendations. If none exist, say "
            "'No specific action items found.'"
        )

    requested = "\n".join(
        f"- {item}" for item in analysis_requirements
    )

    system_prompt = """
You are an expert YouTube video analysis assistant.

Analyze the supplied transcript accurately.

IMPORTANT RULES:

1. Do not invent facts.
2. Do not invent timestamps.
3. For timestamp-related output, ONLY use timestamps that
   actually appear in the supplied timestamped transcript.
4. Keep the output concise but useful.
5. Return valid JSON only.
6. Do not wrap the JSON in Markdown code fences.

Use this exact JSON structure:

{
  "summary": "...",
  "takeaways": "...",
  "topics": "...",
  "sentiment": "...",
  "actions": "..."
}

For fields that were not requested, return an empty string.
"""

    user_prompt = f"""
SUMMARY TYPE:
{summary_type}

REQUESTED ANALYSIS:
{requested}

TIMESTAMPED TRANSCRIPT:
--------------------------------------------------
{timestamped_transcript[:30000]}
--------------------------------------------------

PLAIN TRANSCRIPT:
--------------------------------------------------
{transcript[:30000]}
--------------------------------------------------
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt.strip(),
        },
        {
            "role": "user",
            "content": user_prompt.strip(),
        },
    ]

    result, error = groq_request(
        messages,
        max_tokens=5000,
        retries=2,
    )

    if error:
        return None, error

    # --------------------------------------------------------
    # Parse JSON
    # --------------------------------------------------------

    try:
        parsed = json.loads(result)

    except json.JSONDecodeError:

        # Sometimes a model still puts ```json around the response.
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            result.strip(),
            flags=re.IGNORECASE,
        )

        try:
            parsed = json.loads(cleaned)

        except json.JSONDecodeError:
            return None, (
                "AI returned an invalid analysis format. "
                "Please try again."
            )

    if not isinstance(parsed, dict):
        return None, "AI returned an unexpected analysis format."

    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "takeaways": str(parsed.get("takeaways", "")).strip(),
        "topics": str(parsed.get("topics", "")).strip(),
        "sentiment": str(parsed.get("sentiment", "")).strip(),
        "actions": str(parsed.get("actions", "")).strip(),
    }, None


# ============================================================
# MARKDOWN → SAFE HTML
# ============================================================

def safe_markdown(text):
    """
    Basic Markdown-like rendering without allowing arbitrary
    HTML from the AI response.
    """

    if not text:
        return ""

    escaped = html.escape(text)

    # Bold
    escaped = re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
        escaped,
    )

    # Bullet points
    lines = escaped.split("\n")
    rendered = []

    for line in lines:

        stripped = line.strip()

        if stripped.startswith("- "):
            rendered.append(
                f"<div style='margin:4px 0'>• "
                f"{stripped[2:]}</div>"
            )

        elif stripped.startswith("* "):
            rendered.append(
                f"<div style='margin:4px 0'>• "
                f"{stripped[2:]}</div>"
            )

        else:
            rendered.append(line)

    return "<br>".join(rendered)


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="YouTube Video Summarizer",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# DESIGN SYSTEM
# ============================================================

st.markdown(
    """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;650;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>

:root{
    --bg:#060a14;
    --glass:rgba(16,21,35,.58);
    --glass-strong:rgba(16,21,35,.8);
    --border:rgba(148,163,184,.14);
    --border-soft:rgba(148,163,184,.09);
    --text:#f2f4f8;
    --muted:#8d99ae;
    --red:#ff3b5c;
    --red-soft:rgba(255,59,92,.14);
    --cyan:#22d3ee;
    --cyan-soft:rgba(34,211,238,.14);
    --violet:#a78bfa;
    --violet-soft:rgba(167,139,250,.14);
    --amber:#fbbf24;
    --amber-soft:rgba(251,191,36,.14);
}

html, body, [class*="css"]{
    font-family:'Inter',-apple-system,sans-serif
}

.stApp{
    background:
      radial-gradient(circle at 12% -8%, rgba(255,59,92,.10), transparent 32%),
      radial-gradient(circle at 88% 0%, rgba(34,211,238,.08), transparent 30%),
      var(--bg);
    color:var(--text);
}

.block-container{
    max-width:980px;
    padding:1.4rem 1.5rem 4rem
}

header[data-testid="stHeader"]{
    background:transparent!important;
    box-shadow:none!important;
    height:2.4rem!important;
    min-height:0!important
}

header[data-testid="stHeader"] [data-testid="stToolbarActions"]{
    display:none!important
}

header[data-testid="stHeader"] [data-testid="stDecoration"]{
    display:none!important
}

#MainMenu{
    visibility:hidden!important
}

footer{
    visibility:hidden!important
}

[data-testid="stSidebarCollapsedControl"]{
    z-index:999999!important;
    opacity:1!important;
    visibility:visible!important
}

section[data-testid="stSidebar"]{
    background:linear-gradient(180deg,#0a0f1c,#060a14);
    border-right:1px solid var(--border)
}


/* TOPBAR */

.topbar{
    display:flex;
    align-items:center;
    justify-content:space-between;
    padding:2px 2px 22px
}

.topbar-brand{
    display:flex;
    align-items:center;
    gap:10px
}

.topbar-mark{
    width:34px;
    height:34px;
    border-radius:10px;
    display:grid;
    place-items:center;
    font-size:17px;
    background:linear-gradient(135deg,var(--red),#ff7a45);
    box-shadow:0 8px 22px rgba(255,59,92,.28)
}

.topbar-word{
    font-family:'Sora',sans-serif;
    font-weight:650;
    font-size:15px;
    letter-spacing:-.01em;
    color:var(--text)
}

.topbar-pill{
    padding:6px 12px;
    border-radius:999px;
    background:var(--glass);
    border:1px solid var(--border);
    color:var(--muted);
    font-size:.76rem;
    backdrop-filter:blur(12px)
}


/* HERO */

.hero{
    padding:8px 4px 30px
}

.hero h1{
    font-family:'Sora',sans-serif;
    font-weight:800;
    font-size:clamp(2.1rem,4.6vw,3.1rem);
    line-height:1.06;
    letter-spacing:-.03em;
    margin:0 0 12px;
    max-width:15ch
}

.hero p{
    color:var(--muted);
    font-size:1.05rem;
    line-height:1.55;
    max-width:46ch;
    margin:0
}


/* INPUT */

.input-dock{
    padding:8px;
    border-radius:20px;
    border:1px solid var(--border);
    background:var(--glass);
    backdrop-filter:blur(22px);
    -webkit-backdrop-filter:blur(22px);
    box-shadow:0 20px 50px rgba(0,0,0,.35);
    margin-bottom:16px
}

.input-dock div[data-testid="stTextInput"] input{
    background:transparent!important;
    border:none!important;
    color:var(--text)!important;
    font-size:.98rem!important;
    padding:12px 6px!important;
    box-shadow:none!important
}

.input-dock div[data-testid="stTextInput"] input::placeholder{
    color:#5c6a83!important
}

.input-dock div[data-baseweb="input"]{
    background:transparent!important;
    border:none!important
}

.input-dock [data-testid="stHorizontalBlock"]{
    align-items:center
}


/* PANELS */

.glass-panel{
    padding:22px 24px;
    border-radius:20px;
    border:1px solid var(--border);
    background:var(--glass);
    backdrop-filter:blur(20px);
    -webkit-backdrop-filter:blur(20px);
    box-shadow:0 16px 40px rgba(0,0,0,.25);
    margin-bottom:16px
}

.panel-label{
    color:var(--muted);
    font-size:.74rem;
    letter-spacing:.03em;
    font-weight:600;
    margin-bottom:4px
}

.panel-title{
    font-family:'Sora',sans-serif;
    font-weight:650;
    font-size:1.05rem;
    color:var(--text);
    margin:0 0 14px
}

div[data-testid="stExpander"]{
    border:1px solid var(--border)!important;
    border-radius:18px!important;
    background:var(--glass)!important;
    backdrop-filter:blur(18px);
    overflow:hidden
}

div[data-testid="stExpander"] summary{
    font-family:'Sora',sans-serif;
    font-weight:600;
    color:var(--text)!important
}


/* BUTTONS */

.stButton>button{
    border-radius:13px!important;
    font-weight:600!important;
    border:1px solid var(--border)!important;
    background:var(--glass-strong)!important;
    color:var(--text)!important;
    min-height:46px;
    transition:transform .15s ease,border-color .15s ease
}

.stButton>button:hover{
    transform:translateY(-1px);
    border-color:rgba(255,59,92,.4)!important
}

.stButton>button[kind="primary"]{
    background:linear-gradient(135deg,var(--red),#ff7a45)!important;
    border:none!important;
    color:#fff!important;
    box-shadow:0 14px 34px rgba(255,59,92,.24)!important;
    font-family:'Sora',sans-serif
}

.stButton>button[kind="primary"]:hover{
    transform:translateY(-1px) scale(1.005)
}

.stDownloadButton>button{
    border-radius:13px!important;
    border:1px solid var(--border)!important;
    background:var(--glass)!important;
    color:var(--text)!important;
    font-weight:600!important
}


/* CONTROLS */

div[data-testid="stSelectbox"] div[data-baseweb="select"]{
    background:rgba(8,12,22,.7)!important;
    border-radius:11px!important;
    border:1px solid var(--border)!important
}

div[data-testid="stCheckbox"] label p{
    color:var(--text)!important;
    font-size:.92rem
}


/* STATS */

.stat-readout{
    font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,monospace;
    color:var(--cyan);
    font-size:.86rem;
    letter-spacing:.01em
}


/* SUMMARY */

.summary-card{
    padding:20px 22px;
    border-radius:18px;
    border:1px solid var(--red-soft);
    border-left:3px solid var(--red);
    background:
        linear-gradient(135deg,rgba(255,59,92,.06),transparent 60%),
        var(--glass);
    backdrop-filter:blur(18px);
    margin-bottom:6px
}

.summary-card p{
    margin:0;
    line-height:1.6;
    color:#e7ebf3
}


/* ANALYSIS */

.analysis-card{
    padding:18px 20px;
    border-radius:16px;
    border:1px solid var(--border-soft);
    background:var(--glass);
    backdrop-filter:blur(16px);
    height:100%;
    box-sizing:border-box
}

.analysis-card.takeaways{
    border-left:3px solid var(--cyan);
    background:
        linear-gradient(135deg,var(--cyan-soft),transparent 55%),
        var(--glass)
}

.analysis-card.topics{
    border-left:3px solid var(--violet);
    background:
        linear-gradient(135deg,var(--violet-soft),transparent 55%),
        var(--glass)
}

.analysis-card.sentiment{
    border-left:3px solid var(--amber);
    background:
        linear-gradient(135deg,var(--amber-soft),transparent 55%),
        var(--glass)
}

.analysis-card.actions{
    border-left:3px solid var(--red);
    background:
        linear-gradient(135deg,var(--red-soft),transparent 55%),
        var(--glass)
}

.analysis-card h4{
    font-family:'Sora',sans-serif;
    font-weight:650;
    font-size:.92rem;
    margin:0 0 8px;
    color:var(--text)
}

.analysis-card .card-body{
    color:#cbd4e3;
    font-size:.9rem;
    line-height:1.55
}


/* TRANSCRIPT */

div[data-testid="stTextArea"] textarea{
    background:rgba(6,10,20,.75)!important;
    border-radius:14px!important;
    border:1px solid var(--border)!important;
    color:#c7d0de!important;
    font-family:'JetBrains Mono',ui-monospace,monospace!important;
    font-size:.82rem!important
}


/* FOOTER */

.footer-note{
    text-align:center;
    color:#5c6a83;
    font-size:.8rem;
    padding:22px 0 4px
}


/* ALERTS */

div[data-testid="stAlert"]{
    border-radius:16px!important;
    border:1px solid var(--border)!important;
    backdrop-filter:blur(16px)
}

div[data-testid="stAlert"] p{
    color:var(--text)!important
}

div[data-testid="stAlertContentError"],
div[data-testid="stAlert"]:has(div[data-testid="stAlertContentError"]){
    background:
        linear-gradient(135deg,var(--red-soft),transparent 60%),
        var(--glass)!important
}

div[data-testid="stAlertContentSuccess"],
div[data-testid="stAlert"]:has(div[data-testid="stAlertContentSuccess"]){
    background:
        linear-gradient(135deg,rgba(52,211,153,.14),transparent 60%),
        var(--glass)!important
}

div[data-testid="stAlertContentWarning"],
div[data-testid="stAlert"]:has(div[data-testid="stAlertContentWarning"]){
    background:
        linear-gradient(135deg,var(--amber-soft),transparent 60%),
        var(--glass)!important
}


@media(max-width:820px){
    .block-container{
        padding-left:1rem;
        padding-right:1rem
    }

    .hero h1{
        max-width:none
    }
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# HEADER
# ============================================================

st.markdown(
    """
<div class="topbar">
    <div class="topbar-brand">
        <div class="topbar-mark">🎬</div>
        <div class="topbar-word">Video Summarizer</div>
    </div>

    <div class="topbar-pill">
        Powered by Groq
</div>

<div class="hero">
    <h1>YouTube Video Summarizer</h1>
    <p>
        Paste any YouTube URL and get an AI-powered summary
        in seconds.
    </p>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        '<div class="panel-title">📖 How it works</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
1. **Paste** a YouTube URL
2. **Fetch** the video transcript
3. **Choose** summary type
4. **Get** AI-powered insights
        """
    )

    st.markdown("---")

    st.markdown(
        '<div class="panel-title">💡 Tips</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
- Works best with **educational** videos
- Some videos have **captions disabled**
- Transcripts are **cached for 1 hour**
- Works best with English videos
        """
    )

    st.markdown("---")

    st.caption("Powered by Groq AI")


# ============================================================
# URL INPUT
# ============================================================

st.markdown(
    '<div class="input-dock">',
    unsafe_allow_html=True,
)

col1, col2 = st.columns([4, 1])

with col1:

    url = st.text_input(
        "🔗 Enter YouTube Video URL",
        placeholder=(
            "Paste a YouTube URL — "
            "https://www.youtube.com/watch?v=..."
        ),
        label_visibility="collapsed",
    )

with col2:

    fetch_btn = st.button(
        "Fetch",
        use_container_width=True,
    )

st.markdown(
    "</div>",
    unsafe_allow_html=True,
)


# ============================================================
# FETCH BUTTON
# ============================================================

if fetch_btn:

    if not url.strip():

        st.error("⚠️ Please enter a YouTube video URL.")

    elif not extract_video_id(url):

        st.error(
            "❌ Invalid YouTube URL. "
            "Use a normal YouTube video, Shorts, or youtu.be URL."
        )

    else:

        with st.spinner("📥 Fetching transcript..."):

            segments, timestamped_transcript, error = (
                get_transcript(url)
            )

        if error:

            st.error(f"❌ {error}")

        else:

            transcript = build_transcript_text(segments)

            word_count = len(transcript.split())

            st.session_state["transcript"] = transcript
            st.session_state["timestamped_transcript"] = (
                timestamped_transcript
            )
            st.session_state["segments"] = segments
            st.session_state["video_url"] = url

            st.success(
                f"✅ Transcript loaded successfully — "
                f"{word_count:,} words."
            )


# ============================================================
# SETTINGS
# ============================================================

with st.expander(
    "⚙️ Advanced Settings",
    expanded=False,
):

    col_a, col_b = st.columns(2)

    with col_a:

        st.markdown("**📋 Summary Type**")

        summary_type = st.selectbox(
            "Choose format:",
            [
                "Brief Summary",
                "Detailed Summary",
                "Bullet Points",
                "Key Timestamps",
            ],
            index=0,
        )

    with col_b:

        st.markdown("**🎯 Extra Features**")

        include_takeaways = st.checkbox(
            "Key Takeaways",
            value=True,
        )

        include_topics = st.checkbox(
            "Topic Extraction",
            value=True,
        )

        include_sentiment = st.checkbox(
            "Sentiment Analysis",
            value=False,
        )

        include_actions = st.checkbox(
            "Action Items",
            value=False,
        )


# ============================================================
# GENERATE SUMMARY
# ============================================================

if st.button(
    "🚀 Generate Summary",
    type="primary",
    use_container_width=True,
):

    # --------------------------------------------------------
    # CHECK TRANSCRIPT
    # --------------------------------------------------------

    if "transcript" not in st.session_state:

        st.error(
            "⚠️ Fetch a transcript first. "
            "Paste a YouTube URL and click Fetch."
        )

    else:

        transcript = st.session_state["transcript"]
        timestamped_transcript = st.session_state[
            "timestamped_transcript"
        ]

        # ----------------------------------------------------
        # PROGRESS
        # ----------------------------------------------------

        progress_bar = st.progress(0)
        status_text = st.empty()

        status_text.text(
            "🤖 Sending transcript to AI..."
        )

        progress_bar.progress(30)

        # ----------------------------------------------------
        # AI
        # ----------------------------------------------------

        analysis, error = generate_analysis(
            transcript=transcript,
            timestamped_transcript=timestamped_transcript,
            summary_type=summary_type,
            include_takeaways=include_takeaways,
            include_topics=include_topics,
            include_sentiment=include_sentiment,
            include_actions=include_actions,
        )

        if error:

            progress_bar.empty()
            status_text.empty()

            st.error(f"❌ {error}")

        else:

            progress_bar.progress(90)

            status_text.text(
                "📝 Preparing results..."
            )

            # ------------------------------------------------
            # RESULTS
            # ------------------------------------------------

            st.session_state["analysis"] = analysis

            progress_bar.progress(100)

            status_text.text("✅ Done!")

            time.sleep(0.2)

            progress_bar.empty()
            status_text.empty()

            st.success(
                "✨ Summary generated successfully!"
            )

            # =================================================
            # MAIN SUMMARY
            # =================================================

            st.markdown(
                '<div class="panel-title" '
                'style="margin-top:18px">'
                '📝 Summary'
                '</div>',
                unsafe_allow_html=True,
            )

            summary_html = safe_markdown(
                analysis.get("summary", "")
            )

            st.markdown(
                f"""
<div class="summary-card">
    <p>{summary_html}</p>
</div>
                """,
                unsafe_allow_html=True,
            )

            # =================================================
            # TRANSCRIPT
            # =================================================

            with st.expander(
                "📜 View Full Timestamped Transcript"
            ):

                st.text_area(
                    "Transcript",
                    timestamped_transcript,
                    height=350,
                    disabled=True,
                    label_visibility="collapsed",
                )

            # =================================================
            # ADDITIONAL ANALYSIS
            # =================================================

            has_extra = any(
                [
                    include_takeaways,
                    include_topics,
                    include_sentiment,
                    include_actions,
                ]
            )

            if has_extra:

                st.markdown(
                    '<div class="panel-title" '
                    'style="margin-top:18px">'
                    '🔍 Additional Analysis'
                    '</div>',
                    unsafe_allow_html=True,
                )

                # --------------------------------------------
                # ROW 1
                # --------------------------------------------

                row1_col1, row1_col2 = st.columns(2)

                if include_takeaways:

                    with row1_col1:

                        body = safe_markdown(
                            analysis.get("takeaways", "")
                        )

                        st.markdown(
                            f"""
<div class="analysis-card takeaways">
    <h4>📌 Key Takeaways</h4>
    <div class="card-body">
        {body}
    </div>
</div>
                            """,
                            unsafe_allow_html=True,
                        )

                if include_topics:

                    with row1_col2:

                        body = safe_markdown(
                            analysis.get("topics", "")
                        )

                        st.markdown(
                            f"""
<div class="analysis-card topics">
    <h4>🏷️ Topics Covered</h4>
    <div class="card-body">
        {body}
    </div>
</div>
                            """,
                            unsafe_allow_html=True,
                        )

                # --------------------------------------------
                # ROW 2
                # --------------------------------------------

                row2_col1, row2_col2 = st.columns(2)

                if include_sentiment:

                    with row2_col1:

                        body = safe_markdown(
                            analysis.get("sentiment", "")
                        )

                        st.markdown(
                            f"""
<div class="analysis-card sentiment"
     style="margin-top:12px">

    <h4>💭 Sentiment Analysis</h4>

    <div class="card-body">
        {body}
    </div>

</div>
                            """,
                            unsafe_allow_html=True,
                        )

                if include_actions:

                    with row2_col2:

                        body = safe_markdown(
                            analysis.get("actions", "")
                        )

                        st.markdown(
                            f"""
<div class="analysis-card actions"
     style="margin-top:12px">

    <h4>📝 Action Items</h4>

    <div class="card-body">
        {body}
    </div>

</div>
                            """,
                            unsafe_allow_html=True,
                        )

            # =================================================
            # DOWNLOAD REPORT
            # =================================================

            video_url = st.session_state.get(
                "video_url",
                url,
            )

            word_count = len(
                transcript.split()
            )

            full_report = f"""
YouTube Video Summary Report
==================================================

Video URL:
{video_url}

Word Count:
{word_count}

Summary Type:
{summary_type}

Generated:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


==================================================
MAIN SUMMARY
==================================================

{analysis.get("summary", "")}


==================================================
ADDITIONAL ANALYSIS
==================================================
"""

            if include_takeaways:

                full_report += (
                    "\nKEY TAKEAWAYS:\n"
                    + analysis.get("takeaways", "")
                    + "\n"
                )

            if include_topics:

                full_report += (
                    "\nTOPICS COVERED:\n"
                    + analysis.get("topics", "")
                    + "\n"
                )

            if include_sentiment:

                full_report += (
                    "\nSENTIMENT ANALYSIS:\n"
                    + analysis.get("sentiment", "")
                    + "\n"
                )

            if include_actions:

                full_report += (
                    "\nACTION ITEMS:\n"
                    + analysis.get("actions", "")
                    + "\n"
                )

            full_report += (
                "\n\n"
                "==================================================\n"
                "TIMESTAMPED TRANSCRIPT\n"
                "==================================================\n\n"
                + timestamped_transcript
            )

            st.download_button(
                label="📥 Download Full Report (.txt)",
                data=full_report,
                file_name="youtube_summary_report.txt",
                mime="text/plain",
                use_container_width=True,
            )


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    """
<p class='footer-note'>
Built with Streamlit ❤️ · Powered by Groq AI · For CS Students
</p>
""",
    unsafe_allow_html=True,
)

