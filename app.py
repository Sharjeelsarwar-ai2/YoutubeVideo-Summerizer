import streamlit as st
import requests
import time

# ========================
# CONFIGURATION (Streamlit Secrets)
# ========================
# Add these in Streamlit Cloud: Settings → Secrets
# GROQ_API_KEY = "gsk_..."


def _get_groq_api_key():
    # NOTE: the original code did `GROQ_API_KEY = st.secrets["GROQ_API_KEY"]`
    # directly. If the secret isn't set yet (e.g. right after first deploy,
    # before Settings → Secrets is configured), that line throws a
    # StreamlitSecretNotFoundError/KeyError at import time and crashes the
    # ENTIRE app with a blank error screen before any UI even renders.
    # This makes it fail safely instead, so the app still loads and can show
    # a clear, actionable message when you actually try to use it.
    try:
        return str(st.secrets.get("GROQ_API_KEY", "")).strip()
    except Exception:
        return ""


GROQ_API_KEY = _get_groq_api_key()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# NOTE: the original model here was "llama-3.3-70b-versatile", which Groq
# deprecated and fully shut down on August 16, 2026 (already past as of this
# deployment) — every request would fail. Replaced with Groq's official
# recommended replacement.
GROQ_MODEL = "openai/gpt-oss-120b"

HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}


# ========================
# HELPER FUNCTIONS
# ========================
def extract_video_id(url):
    """Extract YouTube video ID from various URL formats."""
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)
    if parsed.hostname in ["www.youtube.com", "youtube.com"]:
        return parse_qs(parsed.query).get("v", [None])[0]
    elif parsed.hostname in ["youtu.be"]:
        return parsed.path[1:]
    return None


@st.cache_data(ttl=3600)
def get_transcript(video_url):
    """Fetch transcript from YouTube video."""
    video_id = extract_video_id(video_url)
    if not video_id:
        return None, "Invalid YouTube URL"

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, "youtube_transcript_api not installed. Add it to requirements.txt"

    try:
        # NOTE: the original code called the classmethod
        # YouTubeTranscriptApi.get_transcript(video_id). That method (along
        # with get_transcripts/list_transcripts) has been REMOVED in current
        # releases of youtube-transcript-api — a fresh `pip install` on
        # Streamlit Cloud would pull the version where this simply doesn't
        # exist anymore, crashing every request with an AttributeError.
        # Current API is instance-based: YouTubeTranscriptApi().fetch(...).
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id)
        full_text = " ".join(snippet.text for snippet in fetched)
        return full_text, None

    except Exception as e:
        # NOTE: the original code imported specific exception classes from
        # youtube_transcript_api._errors (a private module). That import
        # path has moved around across recent library versions, so a
        # top-level `from youtube_transcript_api._errors import ...` can
        # itself raise ImportError and crash the app before a video is even
        # fetched. Matching on the exception's class name instead is
        # version-agnostic and can't fail at import time.
        name = type(e).__name__
        if name == "TranscriptsDisabled":
            return None, "Transcripts are disabled for this video"
        if name == "NoTranscriptFound":
            return None, "No transcript found for this video"
        if name in ("VideoUnavailable", "VideoUnplayable"):
            return None, "Video is unavailable"
        return None, f"Error: {str(e)}"


def ask_groq(prompt, system_prompt=None, _max_retries=2):
    """Send request to Groq API and get response.

    Automatically retries on HTTP 429 (rate limit), since a single
    "Generate Summary" click fires up to 5 sequential Groq calls
    (summary + takeaways + topics + sentiment + actions) — a burst that
    can trip Groq's per-minute limit partway through even though the
    first call or two succeeded.
    """
    if not GROQ_API_KEY:
        return "❌ GROQ_API_KEY is not configured. Add it in Streamlit Cloud → Settings → Secrets."

    if system_prompt is None:
        system_prompt = """You are a helpful AI assistant that summarizes YouTube videos. 
        Provide clear, concise, and well-structured summaries. 
        Use bullet points when helpful. Be specific and informative."""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2048
    }

    for attempt in range(_max_retries + 1):
        try:
            response = requests.post(
                GROQ_URL,
                headers=HEADERS,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            elif response.status_code == 401:
                return "❌ Invalid API Key. Please check your Groq API key."
            elif response.status_code == 429:
                if attempt < _max_retries:
                    # Groq sends a Retry-After header (seconds) telling us
                    # exactly how long to wait — honor it if present,
                    # otherwise back off a little more on each retry.
                    wait_s = response.headers.get("Retry-After")
                    try:
                        wait_s = float(wait_s)
                    except (TypeError, ValueError):
                        wait_s = 3 * (attempt + 1)
                    wait_s = min(wait_s, 20)  # never block the UI too long
                    time.sleep(wait_s)
                    continue
                return "⏳ Rate limit hit after retrying. Please wait a minute and try again."
            else:
                return f"❌ Error {response.status_code}: {response.text}"

        except requests.exceptions.Timeout:
            return "❌ Request timed out. Please try again."
        except Exception as e:
            return f"❌ Error: {str(e)}"


# ========================
# STREAMLIT UI
# ========================
st.set_page_config(
    page_title="YouTube Video Summarizer",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------- Design system ----------
# A "video editing suite" feel rather than generic SaaS glass: near-black
# navy base; signal-red (recording/alert) + cyan (AI/tech) accents, used
# consistently to color-code the four analysis types rather than as
# decoration. Sora for headlines, Inter for UI text.
st.markdown("""
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

html, body, [class*="css"]{font-family:'Inter',-apple-system,sans-serif}

.stApp{
    background:
      radial-gradient(circle at 12% -8%, rgba(255,59,92,.10), transparent 32%),
      radial-gradient(circle at 88% 0%, rgba(34,211,238,.08), transparent 30%),
      var(--bg);
    color:var(--text);
}
.block-container{max-width:980px; padding:1.4rem 1.5rem 4rem}

/* quiet native chrome — keep the sidebar reopen control alive */
header[data-testid="stHeader"]{background:transparent!important;box-shadow:none!important;height:2.4rem!important;min-height:0!important}
header[data-testid="stHeader"] [data-testid="stToolbarActions"]{display:none!important}
header[data-testid="stHeader"] [data-testid="stDecoration"]{display:none!important}
#MainMenu{visibility:hidden!important}
footer{visibility:hidden!important}
[data-testid="stSidebarCollapsedControl"]{z-index:999999!important;opacity:1!important;visibility:visible!important}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#0a0f1c,#060a14);border-right:1px solid var(--border)}

/* ---------- topbar ---------- */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:2px 2px 22px}
.topbar-brand{display:flex;align-items:center;gap:10px}
.topbar-mark{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-size:17px;background:linear-gradient(135deg,var(--red),#ff7a45);box-shadow:0 8px 22px rgba(255,59,92,.28)}
.topbar-word{font-family:'Sora',sans-serif;font-weight:650;font-size:15px;letter-spacing:-.01em;color:var(--text)}
.topbar-pill{padding:6px 12px;border-radius:999px;background:var(--glass);border:1px solid var(--border);color:var(--muted);font-size:.76rem;backdrop-filter:blur(12px)}

/* ---------- hero ---------- */
.hero{padding:8px 4px 30px}
.hero h1{font-family:'Sora',sans-serif;font-weight:800;font-size:clamp(2.1rem,4.6vw,3.1rem);line-height:1.06;letter-spacing:-.03em;margin:0 0 12px;max-width:15ch}
.hero p{color:var(--muted);font-size:1.05rem;line-height:1.55;max-width:46ch;margin:0}

/* ---------- glass capsule input bar ---------- */
.input-dock{padding:8px;border-radius:20px;border:1px solid var(--border);background:var(--glass);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px);box-shadow:0 20px 50px rgba(0,0,0,.35);margin-bottom:16px}
.input-dock div[data-testid="stTextInput"] input{background:transparent!important;border:none!important;color:var(--text)!important;font-size:.98rem!important;padding:12px 6px!important;box-shadow:none!important}
.input-dock div[data-testid="stTextInput"] input::placeholder{color:#5c6a83!important}
.input-dock div[data-baseweb="input"]{background:transparent!important;border:none!important}
.input-dock [data-testid="stHorizontalBlock"]{align-items:center}

/* ---------- glass panels (settings, results) ---------- */
.glass-panel{padding:22px 24px;border-radius:20px;border:1px solid var(--border);background:var(--glass);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);box-shadow:0 16px 40px rgba(0,0,0,.25);margin-bottom:16px}
.panel-label{color:var(--muted);font-size:.74rem;letter-spacing:.03em;font-weight:600;margin-bottom:4px}
.panel-title{font-family:'Sora',sans-serif;font-weight:650;font-size:1.05rem;color:var(--text);margin:0 0 14px}

div[data-testid="stExpander"]{border:1px solid var(--border)!important;border-radius:18px!important;background:var(--glass)!important;backdrop-filter:blur(18px);overflow:hidden}
div[data-testid="stExpander"] summary{font-family:'Sora',sans-serif;font-weight:600;color:var(--text)!important}

/* ---------- buttons ---------- */
.stButton>button{border-radius:13px!important;font-weight:600!important;border:1px solid var(--border)!important;background:var(--glass-strong)!important;color:var(--text)!important;min-height:46px;transition:transform .15s ease,border-color .15s ease}
.stButton>button:hover{transform:translateY(-1px);border-color:rgba(255,59,92,.4)!important}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,var(--red),#ff7a45)!important;border:none!important;color:#fff!important;box-shadow:0 14px 34px rgba(255,59,92,.24)!important;font-family:'Sora',sans-serif}
.stButton>button[kind="primary"]:hover{transform:translateY(-1px) scale(1.005)}
.stDownloadButton>button{border-radius:13px!important;border:1px solid var(--border)!important;background:var(--glass)!important;color:var(--text)!important;font-weight:600!important}

/* checkboxes / selectbox tidy-up */
div[data-testid="stSelectbox"] div[data-baseweb="select"]{background:rgba(8,12,22,.7)!important;border-radius:11px!important;border:1px solid var(--border)!important}
div[data-testid="stCheckbox"] label p{color:var(--text)!important;font-size:.92rem}

/* ---------- numeric / stat readouts ---------- */
.stat-readout{font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,monospace;color:var(--cyan);font-size:.86rem;letter-spacing:.01em}

/* ---------- result cards, color-coded per analysis type ---------- */
.summary-card{padding:20px 22px;border-radius:18px;border:1px solid var(--red-soft);border-left:3px solid var(--red);background:linear-gradient(135deg,rgba(255,59,92,.06),transparent 60%),var(--glass);backdrop-filter:blur(18px);margin-bottom:6px}
.summary-card p{margin:0;line-height:1.6;color:#e7ebf3}

.analysis-card{padding:18px 20px;border-radius:16px;border:1px solid var(--border-soft);background:var(--glass);backdrop-filter:blur(16px);height:100%;box-sizing:border-box}
.analysis-card.takeaways{border-left:3px solid var(--cyan);background:linear-gradient(135deg,var(--cyan-soft),transparent 55%),var(--glass)}
.analysis-card.topics{border-left:3px solid var(--violet);background:linear-gradient(135deg,var(--violet-soft),transparent 55%),var(--glass)}
.analysis-card.sentiment{border-left:3px solid var(--amber);background:linear-gradient(135deg,var(--amber-soft),transparent 55%),var(--glass)}
.analysis-card.actions{border-left:3px solid var(--red);background:linear-gradient(135deg,var(--red-soft),transparent 55%),var(--glass)}
.analysis-card h4{font-family:'Sora',sans-serif;font-weight:650;font-size:.92rem;margin:0 0 8px;color:var(--text)}
.analysis-card .card-body{color:#cbd4e3;font-size:.9rem;line-height:1.55}

div[data-testid="stTextArea"] textarea{background:rgba(6,10,20,.75)!important;border-radius:14px!important;border:1px solid var(--border)!important;color:#c7d0de!important;font-family:'JetBrains Mono',ui-monospace,monospace!important;font-size:.82rem!important}

.footer-note{text-align:center;color:#5c6a83;font-size:.8rem;padding:22px 0 4px}

/* ---------- native alert boxes (st.error / st.success / st.warning) ---------- */
div[data-testid="stAlert"]{border-radius:16px!important;border:1px solid var(--border)!important;backdrop-filter:blur(16px)}
div[data-testid="stAlert"] p{color:var(--text)!important}
div[data-testid="stAlertContentError"], div[data-testid="stAlert"]:has(div[data-testid="stAlertContentError"]){background:linear-gradient(135deg,var(--red-soft),transparent 60%),var(--glass)!important}
div[data-testid="stAlertContentSuccess"], div[data-testid="stAlert"]:has(div[data-testid="stAlertContentSuccess"]){background:linear-gradient(135deg,rgba(52,211,153,.14),transparent 60%),var(--glass)!important}
div[data-testid="stAlertContentWarning"], div[data-testid="stAlert"]:has(div[data-testid="stAlertContentWarning"]){background:linear-gradient(135deg,var(--amber-soft),transparent 60%),var(--glass)!important}

@media(max-width:820px){.block-container{padding-left:1rem;padding-right:1rem}.hero h1{max-width:none}}
</style>
""", unsafe_allow_html=True)

# ========================
# HEADER
# ========================
st.markdown("""
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
""", unsafe_allow_html=True)

# ========================
# SIDEBAR
# ========================
with st.sidebar:
    st.markdown('<div class="panel-title">📖 How it works</div>', unsafe_allow_html=True)
    st.markdown("""
    1. **Paste** a YouTube URL
    2. **Fetch** the video transcript
    3. **Choose** summary type
    4. **Get** AI-powered insights
    """)
    st.markdown("---")
    st.markdown('<div class="panel-title">💡 Tips</div>', unsafe_allow_html=True)
    st.markdown("""
    - Works best with **educational** videos
    - Some videos have **captions disabled**
    - Transcripts are **cached** for 1 hour
    - Works best with English videos
    """)
    st.markdown("---")
    st.caption("Powered by Groq AI")

# ========================
# MAIN CONTENT
# ========================
# URL Input
st.markdown('<div class="input-dock">', unsafe_allow_html=True)
col1, col2 = st.columns([4, 1])
with col1:
    url = st.text_input(
        "🔗 Enter YouTube Video URL",
        placeholder="Paste a YouTube URL — https://www.youtube.com/watch?v=...",
        label_visibility="collapsed"
    )
with col2:
    fetch_btn = st.button("Fetch", use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ========================
# SETTINGS PANEL
# ========================
with st.expander("⚙️ Advanced Settings", expanded=False):
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**📋 Summary Type**")
        summary_type = st.selectbox(
            "Choose format:",
            ["Brief Summary", "Detailed Summary", "Bullet Points", "Key Timestamps"],
            index=0
        )
    with col_b:
        st.markdown("**🎯 Extra Features**")
        include_takeaways = st.checkbox("Key Takeaways", value=True)
        include_topics = st.checkbox("Topic Extraction", value=True)
        include_sentiment = st.checkbox("Sentiment Analysis")
        include_actions = st.checkbox("Action Items")

# ========================
# PROCESS BUTTON
# ========================
if st.button("🚀 Generate Summary", type="primary", use_container_width=True):
    if not url:
        st.error("⚠️ Please enter a YouTube video URL")
    else:
        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()

        # Step 1: Fetch transcript
        status_text.text("📥 Fetching transcript...")
        progress_bar.progress(20)
        transcript, error = get_transcript(url)

        if error:
            progress_bar.empty()
            st.error(f"❌ {error}")
            st.markdown("""
            **Troubleshooting:**
            - Try a different video
            - Check if the video has captions enabled
            - Try an educational or news video
            """)
        else:
            word_count = len(transcript.split())
            progress_bar.progress(50)
            status_text.text(f"✅ Transcript loaded! ({word_count} words)")

            # Step 2: Generate summary
            status_text.text("🤖 Generating summary with AI...")

            # Map selection to prompt
            prompts = {
                "Brief Summary": "Give a clear 2-3 sentence summary of this YouTube video transcript. Focus on the main topic and key points:",
                "Detailed Summary": "Provide a comprehensive summary of this video transcript. Include the main topic, key points, and important details. Use paragraphs:",
                "Bullet Points": "Summarize this video transcript as clear bullet points. Cover all important topics and details:",
                "Key Timestamps": "Analyze this transcript and identify the main topics discussed. Format as: [Topic] - Brief description:"
            }
            summary = ask_groq(
                f"{prompts[summary_type]}\n\n---\n\n{transcript[:8000]}"
            )
            progress_bar.progress(80)

            # Step 3: Extra features
            # A short pause between each call spreads these requests out
            # over time instead of firing them back-to-back, which lowers
            # the chance of tripping Groq's per-minute rate limit at all
            # (the retry logic in ask_groq() is the fallback if it still
            # happens).
            extra_results = {}

            if include_takeaways:
                status_text.text("📌 Extracting key takeaways...")
                takeaways = ask_groq(
                    "List the top 5 key takeaways or learnings from this video. Be specific and practical:",
                    transcript[:8000]
                )
                extra_results["takeaways"] = takeaways
                time.sleep(1.2)

            if include_topics:
                status_text.text("🏷️ Extracting topics...")
                topics = ask_groq(
                    "Extract and list all the main topics and themes discussed in this video. Format as a clean bullet list:",
                    transcript[:8000]
                )
                extra_results["topics"] = topics
                time.sleep(1.2)

            if include_sentiment:
                status_text.text("💭 Analyzing sentiment...")
                sentiment = ask_groq(
                    "Analyze the overall sentiment and tone of this video. Is it positive, negative, neutral, inspirational, motivational, educational, etc? Give a brief analysis:",
                    transcript[:8000]
                )
                extra_results["sentiment"] = sentiment
                time.sleep(1.2)

            if include_actions:
                status_text.text("📝 Extracting action items...")
                actions = ask_groq(
                    "Extract any action items, tasks, steps to take, or things to do mentioned in this video. If none exist, say 'No specific action items found':",
                    transcript[:8000]
                )
                extra_results["actions"] = actions

            progress_bar.progress(100)
            status_text.text("✅ Done!")
            progress_bar.empty()

            # ========================
            # DISPLAY RESULTS
            # ========================
            st.success("✨ Summary generated successfully!")

            # Main Summary
            st.markdown('<div class="panel-title" style="margin-top:18px">📝 Summary</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="summary-card"><p>{summary}</p></div>', unsafe_allow_html=True)

            # Transcript expander
            with st.expander("📜 View Full Transcript"):
                st.text_area(
                    "Transcript",
                    transcript,
                    height=250,
                    disabled=True,
                    label_visibility="collapsed"
                )

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

            # Extra Results
            if extra_results:
                st.markdown('<div class="panel-title" style="margin-top:10px">🔍 Additional Analysis</div>', unsafe_allow_html=True)

                col1, col2 = st.columns(2)

                if "takeaways" in extra_results:
                    with col1:
                        st.markdown(
                            f'<div class="analysis-card takeaways"><h4>📌 Key Takeaways</h4>'
                            f'<div class="card-body">{extra_results["takeaways"]}</div></div>',
                            unsafe_allow_html=True,
                        )

                if "topics" in extra_results:
                    with col2:
                        st.markdown(
                            f'<div class="analysis-card topics"><h4>🏷️ Topics Covered</h4>'
                            f'<div class="card-body">{extra_results["topics"]}</div></div>',
                            unsafe_allow_html=True,
                        )

                if "sentiment" in extra_results:
                    with col1:
                        st.markdown(
                            f'<div class="analysis-card sentiment" style="margin-top:12px"><h4>💭 Sentiment Analysis</h4>'
                            f'<div class="card-body">{extra_results["sentiment"]}</div></div>',
                            unsafe_allow_html=True,
                        )

                if "actions" in extra_results:
                    with col2:
                        st.markdown(
                            f'<div class="analysis-card actions" style="margin-top:12px"><h4>📝 Action Items</h4>'
                            f'<div class="card-body">{extra_results["actions"]}</div></div>',
                            unsafe_allow_html=True,
                        )

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # ========================
            # DOWNLOAD REPORT
            # ========================
            full_report = f"""
YouTube Video Summary Report
{'='*50}

Video URL: {url}
Word Count: {word_count}
Summary Type: {summary_type}
Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'='*50}
MAIN SUMMARY
{'='*50}
{summary}
"""

            if extra_results:
                full_report += f"""

{'='*50}
ADDITIONAL ANALYSIS
{'='*50}
"""
                if "takeaways" in extra_results:
                    full_report += f"\nKEY TAKEAWAYS:\n{extra_results['takeaways']}\n"
                if "topics" in extra_results:
                    full_report += f"\nTOPICS COVERED:\n{extra_results['topics']}\n"
                if "sentiment" in extra_results:
                    full_report += f"\nSENTIMENT ANALYSIS:\n{extra_results['sentiment']}\n"
                if "actions" in extra_results:
                    full_report += f"\nACTION ITEMS:\n{extra_results['actions']}\n"

            full_report += f"""

{'='*50}
FULL TRANSCRIPT
{'='*50}
{transcript}
"""

            st.download_button(
                label="📥 Download Full Report (.txt)",
                data=full_report,
                file_name="youtube_summary_report.txt",
                mime="text/plain",
                use_container_width=True
            )


# ========================
# FOOTER
# ========================
st.markdown(
    "<p class='footer-note'>Built with Streamlit ❤️ · Powered by Groq AI · For CS Students</p>",
    unsafe_allow_html=True

)
