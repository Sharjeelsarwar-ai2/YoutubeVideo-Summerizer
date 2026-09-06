import streamlit as st
import requests

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


def ask_groq(prompt, system_prompt=None):
    """Send request to Groq API and get response."""
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
            return "⏳ Rate limit hit. Please wait a moment and try again."
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

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #FF4B4B;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #888;
        text-align: center;
        margin-bottom: 2rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #E8F5F5F5;
        border-left: 4px solid #4CAF50;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #F0F7FF;
        border-left: 4px solid #2196F3;
    }
    .stButton>button {
        width: 100%;
        background: linear-gradient(135deg, #FF4B4B, #FF8E53);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-size: 1.1rem;
        font-weight: 600;
        border-radius: 0.5rem;
        cursor: pointer;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, #FF6B6B, #FFA07A);
    }
</style>
""", unsafe_allow_html=True)

# ========================
# HEADER
# ========================
st.markdown('<p class="main-header">🎬 YouTube Video Summarizer</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Paste any YouTube URL and get an AI-powered summary in seconds</p>', unsafe_allow_html=True)

# ========================
# SIDEBAR
# ========================
with st.sidebar:
    st.header("📖 How It Works")
    st.markdown("""
    1. **Paste** a YouTube URL
    2. **Fetch** the video transcript
    3. **Choose** summary type
    4. **Get** AI-powered insights
    """)
    st.markdown("---")
    st.header("💡 Tips")
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
col1, col2 = st.columns([4, 1])
with col1:
    url = st.text_input(
        "🔗 Enter YouTube Video URL",
        placeholder="https://www.youtube.com/watch?v=...",
        label_visibility="collapsed"
    )
with col2:
    st.write("")
    st.write("")
    fetch_btn = st.button("Fetch", use_container_width=True)

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
            extra_results = {}

            if include_takeaways:
                status_text.text("📌 Extracting key takeaways...")
                takeaways = ask_groq(
                    "List the top 5 key takeaways or learnings from this video. Be specific and practical:",
                    transcript[:8000]
                )
                extra_results["takeaways"] = takeaways

            if include_topics:
                status_text.text("🏷️ Extracting topics...")
                topics = ask_groq(
                    "Extract and list all the main topics and themes discussed in this video. Format as a clean bullet list:",
                    transcript[:8000]
                )
                extra_results["topics"] = topics

            if include_sentiment:
                status_text.text("💭 Analyzing sentiment...")
                sentiment = ask_groq(
                    "Analyze the overall sentiment and tone of this video. Is it positive, negative, neutral, inspirational, motivational, educational, etc? Give a brief analysis:",
                    transcript[:8000]
                )
                extra_results["sentiment"] = sentiment

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
            st.markdown("## 📝 Summary")
            st.info(summary)

            # Transcript expander
            with st.expander("📜 View Full Transcript"):
                st.text_area(
                    "Transcript",
                    transcript,
                    height=250,
                    disabled=True,
                    label_visibility="collapsed"
                )

            st.markdown("---")

            # Extra Results
            if extra_results:
                st.markdown("## 🔍 Additional Analysis")

                col1, col2 = st.columns(2)

                if "takeaways" in extra_results:
                    with col1:
                        st.markdown("### 📌 Key Takeaways")
                        st.write(extra_results["takeaways"])

                if "topics" in extra_results:
                    with col2:
                        st.markdown("### 🏷️ Topics Covered")
                        st.write(extra_results["topics"])

                if "sentiment" in extra_results:
                    with col1:
                        st.markdown("### 💭 Sentiment Analysis")
                        st.write(extra_results["sentiment"])

                if "actions" in extra_results:
                    with col2:
                        st.markdown("### 📝 Action Items")
                        st.write(extra_results["actions"])

            st.markdown("---")

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
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: #888; font-size: 0.9rem;'>"
    "Built with Streamlit ❤️ | Powered by Groq AI | For CS Students"
    "</p>",
    unsafe_allow_html=True
)
