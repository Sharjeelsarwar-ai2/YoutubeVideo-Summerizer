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
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CONFIGURATION
# ============================================================

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

# Conservative Groq limits for the user's current 8,000 TPM tier.
# We intentionally keep each request well below the limit.
CHUNK_MAX_CHARS = 3200
CHUNK_MAX_OUTPUT_TOKENS = 450
MAIN_MAX_OUTPUT_TOKENS = 1300
EXTRA_MAX_OUTPUT_TOKENS = 850
REDUCE_MAX_OUTPUT_TOKENS = 700


def _get_secret(name):
    try:
        value = st.secrets.get(name, "")
        return str(value).strip() if value else ""
    except Exception:
        return ""


GROQ_API_KEY = _get_secret("GROQ_API_KEY")
SUPADATA_API_KEY = _get_secret("SUPADATA_API_KEY")


# ============================================================
# DESIGN SYSTEM — ORIGINAL UI
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

    #MainMenu{visibility:hidden!important}
    footer{visibility:hidden!important}

    [data-testid="stSidebarCollapsedControl"]{
        z-index:999999!important;
        opacity:1!important;
        visibility:visible!important
    }

    section[data-testid="stSidebar"]{
        background:linear-gradient(180deg,#0a0f1c,#060a14);
        border-right:1px solid var(--border)
    }

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

    div[data-testid="stSelectbox"] div[data-baseweb="select"]{
        background:rgba(8,12,22,.7)!important;
        border-radius:11px!important;
        border:1px solid var(--border)!important
    }

    div[data-testid="stCheckbox"] label p{
        color:var(--text)!important;
        font-size:.92rem
    }

    .stat-readout{
        font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,monospace;
        color:var(--cyan);
        font-size:.86rem;
        letter-spacing:.01em
    }

    .summary-card{
        padding:20px 22px;
        border-radius:18px;
        border:1px solid var(--red-soft);
        border-left:3px solid var(--red);
        background:linear-gradient(135deg,rgba(255,59,92,.06),transparent 60%),var(--glass);
        backdrop-filter:blur(18px);
        margin-bottom:6px
    }

    .summary-card p{
        margin:0;
        line-height:1.6;
        color:#e7ebf3
    }

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
        background:linear-gradient(135deg,var(--cyan-soft),transparent 55%),var(--glass)
    }

    .analysis-card.topics{
        border-left:3px solid var(--violet);
        background:linear-gradient(135deg,var(--violet-soft),transparent 55%),var(--glass)
    }

    .analysis-card.sentiment{
        border-left:3px solid var(--amber);
        background:linear-gradient(135deg,var(--amber-soft),transparent 55%),var(--glass)
    }

    .analysis-card.actions{
        border-left:3px solid var(--red);
        background:linear-gradient(135deg,var(--red-soft),transparent 55%),var(--glass)
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

    div[data-testid="stTextArea"] textarea{
        background:rgba(6,10,20,.75)!important;
        border-radius:14px!important;
        border:1px solid var(--border)!important;
        color:#c7d0de!important;
        font-family:'JetBrains Mono',ui-monospace,monospace!important;
        font-size:.82rem!important
    }

    .footer-note{
        text-align:center;
        color:#5c6a83;
        font-size:.8rem;
        padding:22px 0 4px
    }

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
        background:linear-gradient(135deg,var(--red-soft),transparent 60%),var(--glass)!important
    }

    div[data-testid="stAlertContentSuccess"],
    div[data-testid="stAlert"]:has(div[data-testid="stAlertContentSuccess"]){
        background:linear-gradient(135deg,rgba(52,211,153,.14),transparent 60%),var(--glass)!important
    }

    div[data-testid="stAlertContentWarning"],
    div[data-testid="stAlert"]:has(div[data-testid="stAlertContentWarning"]){
        background:linear-gradient(135deg,var(--amber-soft),transparent 60%),var(--glass)!important
    }

    @media(max-width:820px){
        .block-container{padding-left:1rem;padding-right:1rem}
        .hero h1{max-width:none}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
# ============================================================

for key, default in {
    "video_url": "",
    "transcript_data": None,
    "video_id": None,
    "analysis_result": None,
    "extra_results": {},
    "summary_type": "Brief Summary",
    "transcript_word_count": 0,
    "transcript_token_count": 0,
    "video_duration": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================
# HELPERS
# ============================================================

def extract_video_id(url):
    """Extract a YouTube video ID from common URL formats."""
    if not url:
        return None

    url = url.strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        if host in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
            query_id = parse_qs(parsed.query).get("v", [None])[0]
            if query_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", query_id):
                return query_id

            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0].lower() in {
                "shorts", "embed", "live"
            }:
                candidate = parts[1]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                    return candidate

        if host == "youtu.be":
            candidate = parsed.path.strip("/").split("/")[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return candidate

    except Exception:
        pass

    return None


def format_timestamp(seconds):
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "00:00"

    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60

    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def normalize_timestamp(value):
    if value is None:
        return 0.0

    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0

    # Some APIs use milliseconds.
    if value > 100000:
        value /= 1000.0

    return max(0.0, value)


def parse_duration_value(value):
    """Parse numeric or HH:MM:SS/MM:SS duration values."""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return normalize_timestamp(value)

    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"\d+(?::\d{1,2}){1,2}", text):
        parts = [int(x) for x in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]

    try:
        return normalize_timestamp(float(text))
    except (TypeError, ValueError):
        return None


def find_duration_in_payload(data):
    """Look for a real video duration in common API response locations."""
    duration_keys = {
        "duration",
        "videoDuration",
        "video_duration",
        "length",
        "durationSeconds",
        "duration_seconds",
    }

    def walk(obj, depth=0):
        if depth > 4:
            return None

        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in duration_keys:
                    parsed = parse_duration_value(value)
                    if parsed and parsed > 0:
                        return parsed
            for value in obj.values():
                result = walk(value, depth + 1)
                if result:
                    return result

        elif isinstance(obj, list):
            for value in obj[:20]:
                result = walk(value, depth + 1)
                if result:
                    return result

        return None

    return walk(data)


def extract_transcript_segments(data):
    """Extract timestamped transcript segments from Supadata response."""
    content = None

    if isinstance(data, dict):
        for key in ("content", "segments", "items", "transcript"):
            if isinstance(data.get(key), list):
                content = data[key]
                break

        if content is None and isinstance(data.get("data"), dict):
            nested = data["data"]
            for key in ("content", "segments", "items", "transcript"):
                if isinstance(nested.get(key), list):
                    content = nested[key]
                    break

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

        start = item.get("start")
        if start is None:
            start = item.get("offset")
        if start is None:
            start = item.get("startTime")

        duration = item.get("duration")
        if duration is None:
            duration = item.get("durationSeconds", 0)

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
def get_transcript(video_url):
    """Fetch a timestamped YouTube transcript from Supadata."""
    if not SUPADATA_API_KEY:
        return None, None, "SUPADATA_API_KEY is not configured. Add it in Streamlit Cloud → Settings → Secrets."

    endpoint = "https://api.supadata.ai/v1/youtube/transcript"
    headers = {
        "x-api-key": SUPADATA_API_KEY,
        "Accept": "application/json",
    }
    params = {"url": video_url}

    try:
        response = requests.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=45,
        )
    except requests.Timeout:
        return None, None, "Supadata timed out while fetching the transcript."
    except requests.RequestException as exc:
        return None, None, f"Could not connect to Supadata: {exc}"

    if response.status_code == 401:
        return None, None, "Supadata rejected the API key. Check SUPADATA_API_KEY."
    if response.status_code == 403:
        return None, None, "Supadata denied this request. Check your Supadata API access."
    if response.status_code == 404:
        return None, None, "Supadata could not find a transcript for this YouTube video."
    if response.status_code == 429:
        return None, None, "Supadata rate limit reached. Please try again later."
    if response.status_code >= 500:
        return None, None, f"Supadata server error ({response.status_code}). Please try again."

    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        return None, None, f"Supadata returned HTTP {response.status_code}: {detail}"

    try:
        data = response.json()
    except ValueError:
        return None, None, "Supadata returned an invalid JSON response."

    segments = extract_transcript_segments(data)
    duration = find_duration_in_payload(data)

    if not segments:
        return None, duration, "Supadata returned no usable transcript segments for this video."

    return segments, duration, None


def build_timestamped_transcript(segments):
    return "\n".join(
        f"[{format_timestamp(segment['start'])}] {segment['text'].strip()}"
        for segment in segments
        if segment["text"].strip()
    )


def build_plain_transcript(segments):
    return " ".join(
        segment["text"].strip()
        for segment in segments
        if segment["text"].strip()
    )


def estimate_tokens(text):
    # Conservative display-only estimate. The real tokenizer is provider-specific.
    return max(1, int(len(text) / 4))


# ============================================================
# VIDEO DURATION FALLBACK
# ============================================================

def fetch_video_duration_fallback(video_id):
    """
    Optional duration fallback using yt-dlp when installed.
    This is only used when the transcript API did not provide duration metadata.
    """
    try:
        import yt_dlp
    except ImportError:
        return None

    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
            )
        duration = info.get("duration") if isinstance(info, dict) else None
        return parse_duration_value(duration)
    except Exception:
        return None


# ============================================================
# GROQ
# ============================================================

def ask_groq(prompt, system_prompt=None, max_tokens=900, retries=2):
    if not GROQ_API_KEY:
        return "❌ GROQ_API_KEY is not configured. Add it in Streamlit Cloud → Settings → Secrets."

    if system_prompt is None:
        system_prompt = (
            "You are a helpful AI assistant that summarizes YouTube videos. "
            "Provide clear, concise, accurate, well-structured results. "
            "Do not invent facts or timestamps."
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(retries + 1):
        try:
            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=90,
            )

            if response.status_code == 200:
                try:
                    return response.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError, ValueError):
                    return "❌ Groq returned an unexpected response format."

            if response.status_code == 401:
                return "❌ Invalid API Key. Please check your Groq API key."

            if response.status_code == 413:
                return (
                    "❌ Groq rejected this request because it is too large. "
                    "The transcript chunk needs to be smaller."
                )

            if response.status_code == 429:
                if attempt < retries:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait_s = float(retry_after)
                    except (TypeError, ValueError):
                        wait_s = 5 * (attempt + 1)
                    time.sleep(min(max(wait_s, 2), 20))
                    continue
                return "⏳ Groq rate limit reached. Please wait a moment and try again."

            return f"❌ Error {response.status_code}: {response.text[:1200]}"

        except requests.exceptions.Timeout:
            if attempt < retries:
                time.sleep(2)
                continue
            return "❌ Groq request timed out. Please try again."

        except requests.RequestException as exc:
            if attempt < retries:
                time.sleep(2)
                continue
            return f"❌ Groq connection error: {exc}"

        except Exception as exc:
            return f"❌ Error: {exc}"

    return "❌ Groq request failed."


# ============================================================
# TOKEN-SAFE CHUNKING
# ============================================================

def split_transcript_into_chunks(segments, max_chars=CHUNK_MAX_CHARS):
    """Split timestamped transcript into conservative Groq-safe chunks."""
    chunks = []
    current = []
    current_chars = 0

    for segment in segments:
        timestamp = format_timestamp(segment["start"])
        text = segment["text"].strip()
        if not text:
            continue

        line = f"[{timestamp}] {text}"

        if len(line) <= max_chars:
            if current and current_chars + len(line) + 1 > max_chars:
                chunks.append("\n".join(current))
                current = []
                current_chars = 0

            current.append(line)
            current_chars += len(line) + 1
            continue

        # Break unusually large transcript segments by words.
        words = text.split()
        partial = []
        partial_chars = 0

        for word in words:
            extra = len(word) + 1
            prefix = f"[{timestamp}] " if not partial else ""
            extra_total = len(prefix) + extra

            if partial and partial_chars + extra_total > max_chars:
                if current:
                    chunks.append("\n".join(current))
                    current = []
                    current_chars = 0

                chunks.append(
                    f"[{timestamp}] " + " ".join(partial)
                )
                partial = []
                partial_chars = 0

            partial.append(word)
            partial_chars += extra_total

        if partial:
            line2 = f"[{timestamp}] " + " ".join(partial)
            if current and current_chars + len(line2) + 1 > max_chars:
                chunks.append("\n".join(current))
                current = []
                current_chars = 0
            current.append(line2)
            current_chars += len(line2) + 1

    if current:
        chunks.append("\n".join(current))

    return chunks


# ============================================================
# CHUNK SUMMARIZATION
# ============================================================

def summarize_chunk(chunk_text, chunk_number, total_chunks):
    """Create information-rich notes from one transcript chunk."""
    system_prompt = """
You are the first-stage transcript analyst for a high-quality YouTube summarizer.

Analyze ONLY the supplied transcript chunk. Do not invent facts.
Preserve concrete details that a final summarizer may need: main ideas,
arguments, explanations, examples, definitions, names, numbers, conclusions,
and important timestamp references.
Do not write a tiny generic summary. Produce dense, useful notes in a few
clear bullets or short paragraphs. Keep the original meaning intact.
"""

    prompt = f"""
Transcript chunk {chunk_number} of {total_chunks}.

Extract the important information from this chunk for a later final summary.
Include enough detail that the final summary can explain WHAT was said and WHY
it mattered, not just the topic name.
Preserve useful timestamp references such as [02:14] when present.

TRANSCRIPT:
{chunk_text}
"""

    return ask_groq(
        prompt,
        system_prompt=system_prompt,
        max_tokens=CHUNK_MAX_OUTPUT_TOKENS,
        retries=2,
    )


def reduce_notes(notes, target_chars=9500):
    """Hierarchically compress all chunk notes without discarding later chunks."""
    if not notes:
        return ""

    current = list(notes)
    while len("\n\n".join(current)) > target_chars and len(current) > 1:
        groups = []
        group = []
        group_chars = 0

        for note in current:
            note_block = note.strip()
            if not note_block:
                continue
            extra = len(note_block) + 30
            if group and group_chars + extra > 6500:
                groups.append(group)
                group = []
                group_chars = 0
            group.append(note_block)
            group_chars += extra

        if group:
            groups.append(group)

        reduced = []
        for i, group_notes in enumerate(groups, start=1):
            source = "\n\n".join(
                f"SOURCE NOTE {j + 1}:\n{note}"
                for j, note in enumerate(group_notes)
            )
            prompt = f"""
Combine these transcript-analysis notes into one faithful master note block.
Keep all important facts, examples, explanations, conclusions, and timestamp
references. Remove repetition, but do NOT omit unique information.
This is reduction pass group {i}.

{source}
"""
            result = ask_groq(
                prompt,
                system_prompt=(
                    "You are a careful information-preserving editor. "
                    "Merge notes without inventing or dropping unique facts."
                ),
                max_tokens=REDUCE_MAX_OUTPUT_TOKENS,
                retries=2,
            )
            reduced.append(result)
            if i < len(groups):
                time.sleep(4)
        current = reduced

    return "\n\n".join(current)


def generate_main_summary(source, summary_type):
    """Generate the primary user-facing summary separately from extras."""
    style_instructions = {
        "Brief Summary": (
            "Write about 3-5 substantial paragraphs. Cover the central message "
            "plus the most important supporting points."
        ),
        "Detailed Summary": (
            "Write a thorough multi-paragraph summary with clear sections or "
            "paragraphs. Cover the progression of ideas, important explanations, "
            "examples, and conclusions."
        ),
        "Bullet Points": (
            "Write 10-16 informative bullet points. Each bullet should explain a "
            "meaningful point rather than just naming a topic."
        ),
        "Key Timestamps": (
            "Write a detailed chronological summary and include important timestamp "
            "references exactly as they appear in the source notes."
        ),
    }

    system_prompt = """
You are an expert YouTube video summarizer.
Use ONLY the supplied transcript-analysis notes.
Do not invent facts, examples, claims, or timestamps.
The user expects a useful, substantive summary, not a one-paragraph teaser.
Preserve nuance and important details from the notes.
"""
    prompt = f"""
SUMMARY TYPE: {summary_type}

{style_instructions.get(summary_type, style_instructions['Brief Summary'])}

MASTER TRANSCRIPT NOTES:
{source}

Write the final main summary now.
"""
    return ask_groq(
        prompt,
        system_prompt=system_prompt,
        max_tokens=MAIN_MAX_OUTPUT_TOKENS,
        retries=2,
    )


def generate_extra_analysis(source, include_takeaways, include_topics,
                            include_sentiment, include_actions, include_timestamps,
                            segments):
    """Generate optional analysis separately so it cannot consume the main summary budget."""
    requested = {
        "takeaways": include_takeaways,
        "topics": include_topics,
        "sentiment": include_sentiment,
        "actions": include_actions,
        "timestamps": include_timestamps,
    }
    real_timestamps = list(dict.fromkeys(format_timestamp(s["start"]) for s in segments))

    if not any(requested.values()):
        return {key: "" for key in requested}

    system_prompt = """
You are an expert video-analysis assistant.
Use ONLY the supplied master transcript notes.
Return valid JSON only, with the requested fields.
Do not invent facts or timestamps.
For timestamps, use ONLY timestamps that occur in the REAL TIMESTAMPS list.
"""
    prompt = f"""
REQUESTED FEATURES:
{json.dumps(requested)}

REAL TIMESTAMPS:
{json.dumps(real_timestamps)}

MASTER TRANSCRIPT NOTES:
{source}

Requirements:
- takeaways: 5-8 concrete lessons or conclusions when requested.
- topics: 5-10 specific topics/themes when requested.
- sentiment: explain the overall tone and why, when requested.
- actions: practical actions explicitly supported by the video, when requested.
- timestamps: list the most useful moments with their exact allowed timestamps,
  when requested.

JSON shape:
{{
  "takeaways": "",
  "topics": "",
  "sentiment": "",
  "actions": "",
  "timestamps": ""
}}
"""

    raw = ask_groq(
        prompt,
        system_prompt=system_prompt,
        max_tokens=EXTRA_MAX_OUTPUT_TOKENS,
        retries=2,
    )
    parsed = extract_json_object(raw)
    if parsed:
        return {key: str(parsed.get(key, "")).strip() for key in requested}
    return {key: "" for key in requested}




# ============================================================
# ORIGINAL HEADER
# ============================================================

st.markdown(
    """
    <div class="topbar">
        <div class="topbar-brand">
            <div class="topbar-mark">🎬</div>
            <div class="topbar-word">Video Summarizer</div>
        </div>
        <div class="topbar-pill">Powered by Groq</div>
    </div>

    <div class="hero">
        <h1>YouTube Video Summarizer</h1>
        <p>Paste any YouTube URL and get an AI-powered summary in seconds.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# ORIGINAL SIDEBAR
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
        - Transcripts are **cached** for 1 hour
        - Works best with English videos
        """
    )
    st.markdown("---")
    st.caption("Powered by Groq AI")


# ============================================================
# ORIGINAL MAIN INPUT BAR
# ============================================================

st.markdown('<div class="input-dock">', unsafe_allow_html=True)
col1, col2 = st.columns([4, 1])

with col1:
    url = st.text_input(
        "🔗 Enter YouTube Video URL",
        value=st.session_state.video_url,
        placeholder="Paste a YouTube URL — https://www.youtube.com/watch?v=...",
        label_visibility="collapsed",
    )

with col2:
    fetch_btn = st.button("Fetch", use_container_width=True)

st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# FETCH BUTTON
# ============================================================

if fetch_btn:
    video_id = extract_video_id(url)

    if not video_id:
        st.error("❌ Invalid YouTube URL. Please paste a valid YouTube video link.")
    else:
        with st.spinner("📥 Fetching transcript..."):
            segments, duration, error = get_transcript(url)

        if error:
            st.error(f"❌ {error}")
            st.markdown(
                """
                **Troubleshooting:**
                - Try a different video
                - Check if the video has captions enabled
                - Try an educational or news video
                """
            )
        else:
            plain_text = build_plain_transcript(segments)
            word_count = len(plain_text.split())
            token_count = estimate_tokens(plain_text)

            if not duration:
                # Only use this fallback when the transcript API did not
                # provide real duration metadata.
                duration = fetch_video_duration_fallback(video_id)

            st.session_state.video_url = url
            st.session_state.video_id = video_id
            st.session_state.transcript_data = segments
            st.session_state.transcript_word_count = word_count
            st.session_state.transcript_token_count = token_count
            st.session_state.video_duration = duration
            st.session_state.analysis_result = None
            st.session_state.extra_results = {}

            st.success("✅ Transcript loaded successfully!")


# ============================================================
# TRANSCRIPT DETAILS — ADDED WITHOUT CHANGING ORIGINAL UI
# ============================================================

segments = st.session_state.transcript_data

if segments:
    plain_transcript = build_plain_transcript(segments)
    timestamped_transcript = build_timestamped_transcript(segments)

    word_count = st.session_state.transcript_word_count
    token_count = st.session_state.transcript_token_count
    duration = st.session_state.video_duration

    st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
    st.markdown(
        '<div class="panel-label">TRANSCRIPT DETAILS</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="panel-title">Video information</div>',
        unsafe_allow_html=True,
    )

    d1, d2, d3, d4 = st.columns(4)

    with d1:
        st.markdown(
            f'<div class="stat-readout">{word_count:,}</div>'
            '<div class="panel-label">WORDS</div>',
            unsafe_allow_html=True,
        )

    with d2:
        st.markdown(
            f'<div class="stat-readout">{token_count:,}</div>'
            '<div class="panel-label">EST. TOKENS</div>',
            unsafe_allow_html=True,
        )

    with d3:
        st.markdown(
            f'<div class="stat-readout">{len(segments):,}</div>'
            '<div class="panel-label">SEGMENTS</div>',
            unsafe_allow_html=True,
        )

    with d4:
        duration_text = (
            format_timestamp(duration)
            if duration and duration > 0
            else "Unavailable"
        )
        st.markdown(
            f'<div class="stat-readout">{html.escape(duration_text)}</div>'
            '<div class="panel-label">VIDEO LENGTH</div>',
            unsafe_allow_html=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# ORIGINAL SETTINGS PANEL
# ============================================================

with st.expander("⚙️ Advanced Settings", expanded=False):
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
            index=[
                "Brief Summary",
                "Detailed Summary",
                "Bullet Points",
                "Key Timestamps",
            ].index(st.session_state.summary_type),
        )
        st.session_state.summary_type = summary_type

    with col_b:
        st.markdown("**🎯 Extra Features**")
        include_takeaways = st.checkbox("Key Takeaways", value=True)
        include_topics = st.checkbox("Topic Extraction", value=True)
        include_sentiment = st.checkbox("Sentiment Analysis", value=False)
        include_actions = st.checkbox("Action Items", value=False)


# ============================================================
# ORIGINAL PROCESS BUTTON + FIXED PROCESSING
# ============================================================

if st.button("🚀 Generate Summary", type="primary", use_container_width=True):
    if not url:
        st.error("⚠️ Please enter a YouTube video URL")
    else:
        video_id = extract_video_id(url)
        if not video_id:
            st.error("⚠️ Please enter a valid YouTube video URL")
        else:
            # Reuse the already fetched transcript when it belongs to the same URL.
            if (
                st.session_state.transcript_data is None
                or st.session_state.video_url != url
            ):
                progress_bar = st.progress(0)
                status_text = st.empty()

                status_text.text("📥 Fetching transcript...")
                progress_bar.progress(15)

                fetched_segments, duration, error = get_transcript(url)

                if error:
                    progress_bar.empty()
                    status_text.empty()
                    st.error(f"❌ {error}")
                    st.markdown(
                        """
                        **Troubleshooting:**
                        - Try a different video
                        - Check if the video has captions enabled
                        - Try an educational or news video
                        """
                    )
                    st.stop()

                plain_text = build_plain_transcript(fetched_segments)
                st.session_state.video_url = url
                st.session_state.video_id = video_id
                st.session_state.transcript_data = fetched_segments
                st.session_state.transcript_word_count = len(plain_text.split())
                st.session_state.transcript_token_count = estimate_tokens(plain_text)
                st.session_state.video_duration = (
                    duration or fetch_video_duration_fallback(video_id)
                )

                segments = fetched_segments
                progress_bar.progress(25)
            else:
                progress_bar = st.progress(25)
                status_text = st.empty()
                status_text.text(
                    f"✅ Transcript already loaded! ({st.session_state.transcript_word_count:,} words)"
                )

            segments = st.session_state.transcript_data

            if not segments:
                progress_bar.empty()
                status_text.empty()
                st.error("❌ No transcript is available for this video.")
                st.stop()

            timestamped_transcript = build_timestamped_transcript(segments)
            plain_transcript = build_plain_transcript(segments)

            # ------------------------------------------------
            # Token-safe, information-preserving analysis
            # ------------------------------------------------
            chunks = split_transcript_into_chunks(segments)

            if not chunks:
                progress_bar.empty()
                status_text.empty()
                st.error("❌ Could not divide the transcript into analysis chunks.")
                st.stop()

            status_text.text(
                f"🤖 Analyzing transcript safely in {len(chunks)} chunk(s)..."
            )
            progress_bar.progress(30)

            chunk_summaries = []
            failed = False

            for index, chunk in enumerate(chunks):
                status_text.text(
                    f"🤖 Analyzing transcript chunk {index + 1} of {len(chunks)}..."
                )

                result = summarize_chunk(chunk, index + 1, len(chunks))
                if result.startswith("❌") or result.startswith("⏳"):
                    st.error(result)
                    failed = True
                    break

                chunk_summaries.append(result)
                progress_bar.progress(
                    min(55, 30 + int((index + 1) / len(chunks) * 25))
                )

                if index < len(chunks) - 1:
                    time.sleep(4)

            if failed:
                progress_bar.empty()
                status_text.empty()
                st.stop()

            status_text.text("🧩 Combining all transcript sections...")
            progress_bar.progress(60)
            time.sleep(4)

            master_notes = reduce_notes(chunk_summaries)
            if master_notes.startswith("❌") or master_notes.startswith("⏳"):
                progress_bar.empty()
                status_text.empty()
                st.error(master_notes)
                st.stop()

            status_text.text("🧠 Writing the full summary...")
            progress_bar.progress(72)
            time.sleep(4)

            main_summary = generate_main_summary(master_notes, summary_type)
            if main_summary.startswith("❌") or main_summary.startswith("⏳"):
                progress_bar.empty()
                status_text.empty()
                st.error(main_summary)
                st.stop()

            time.sleep(4)
            status_text.text("🔍 Generating additional insights...")
            progress_bar.progress(88)

            extras = generate_extra_analysis(
                master_notes,
                include_takeaways,
                include_topics,
                include_sentiment,
                include_actions,
                summary_type == "Key Timestamps",
                segments,
            )

            st.session_state.analysis_result = main_summary
            st.session_state.extra_results = {k: v for k, v in extras.items() if v}

            progress_bar.progress(100)
            status_text.text("✅ Done!")
            time.sleep(0.15)
            progress_bar.empty()
            status_text.empty()


# ============================================================
# DISPLAY RESULTS — ORIGINAL RESULT UI
# ============================================================

if st.session_state.analysis_result:
    extra_results = st.session_state.extra_results or {}

    st.success("✨ Summary generated successfully!")

    # Main Summary
    st.markdown(
        '<div class="panel-title" style="margin-top:18px">📝 Summary</div>',
        unsafe_allow_html=True,
    )

    # Escape only the HTML-dangerous characters while keeping the original
    # card. Streamlit Markdown is used inside for readable formatting.
    st.markdown(
        f'<div class="summary-card"><p>{html.escape(st.session_state.analysis_result).replace(chr(10), "<br>")}</p></div>',
        unsafe_allow_html=True,
    )

    # Full timestamped transcript
    if segments:
        with st.expander("📜 View Full Transcript"):
            st.text_area(
                "Transcript",
                build_timestamped_transcript(segments),
                height=300,
                disabled=True,
                label_visibility="collapsed",
            )

        # Real timestamp chips when timestamp mode was requested.
        if summary_type == "Key Timestamps":
            timestamp_text = extra_results.get("timestamps", "")
            if timestamp_text:
                st.markdown(
                    '<div class="panel-title" style="margin-top:18px">⏱️ Key Timestamps</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="analysis-card topics"><div class="card-body">{html.escape(timestamp_text).replace(chr(10), "<br>")}</div></div>',
                    unsafe_allow_html=True,
                )

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # Extra Results
    cards = [
        ("takeaways", "takeaways", "📌 Key Takeaways"),
        ("topics", "topics", "🏷️ Topics Covered"),
        ("sentiment", "sentiment", "💭 Sentiment Analysis"),
        ("actions", "actions", "📝 Action Items"),
    ]

    visible_cards = [item for item in cards if extra_results.get(item[0])]

    if visible_cards:
        st.markdown(
            '<div class="panel-title" style="margin-top:10px">🔍 Additional Analysis</div>',
            unsafe_allow_html=True,
        )

        for row_start in range(0, len(visible_cards), 2):
            row = visible_cards[row_start:row_start + 2]
            c1, c2 = st.columns(2)

            for col, (key, css_class, title) in zip((c1, c2), row):
                with col:
                    value = extra_results[key]
                    st.markdown(
                        f'<div class="analysis-card {css_class}">'
                        f'<h4>{title}</h4>'
                        f'<div class="card-body">{html.escape(value).replace(chr(10), "<br>")}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            if len(row) == 2:
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ========================================================
    # DOWNLOAD REPORT
    # ========================================================

    transcript_text_for_report = (
        build_timestamped_transcript(segments)
        if segments
        else ""
    )

    video_length_for_report = (
        format_timestamp(st.session_state.video_duration)
        if st.session_state.video_duration
        else "Unavailable"
    )

    full_report = f"""YouTube Video Summary Report
{'=' * 50}

Video URL: {st.session_state.video_url}
Video ID: {st.session_state.video_id}
Word Count: {st.session_state.transcript_word_count:,}
Estimated Tokens: {st.session_state.transcript_token_count:,}
Video Length: {video_length_for_report}
Summary Type: {summary_type}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'=' * 50}
MAIN SUMMARY
{'=' * 50}
{st.session_state.analysis_result}
"""

    if extra_results:
        full_report += f"\n{'=' * 50}\nADDITIONAL ANALYSIS\n{'=' * 50}\n"

        labels = {
            "takeaways": "KEY TAKEAWAYS",
            "topics": "TOPICS COVERED",
            "sentiment": "SENTIMENT ANALYSIS",
            "actions": "ACTION ITEMS",
            "timestamps": "KEY TIMESTAMPS",
        }

        for key in labels:
            if extra_results.get(key):
                full_report += (
                    f"\n{labels[key]}:\n"
                    f"{extra_results[key]}\n"
                )

    full_report += (
        f"\n{'=' * 50}\n"
        "FULL TIMESTAMPED TRANSCRIPT\n"
        f"{'=' * 50}\n"
        f"{transcript_text_for_report}\n"
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
    "<p class='footer-note'>Built with Streamlit ❤️ · Powered by Groq AI · For CS Students</p>",
    unsafe_allow_html=True,
)
