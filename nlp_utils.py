# nlp_utils.py - NLP utilities for sentiment analysis, bias detection, and summarization

import re
import json
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# --- Global model instances ---
sia = None
summarizer = None
GROQ_API_KEY = None

def set_gemini_key(key: str):
    """Kept for backward compatibility with app.py — does nothing now."""
    pass

def set_groq_key(key: str):
    """Called from app.py to pass the Groq key."""
    global GROQ_API_KEY
    GROQ_API_KEY = key

def init_nlp_models():
    global sia, summarizer

    # --- VADER (sentiment) ---
    try:
        nltk.data.find('sentiment/vader_lexicon.zip')
    except LookupError:
        nltk.download('vader_lexicon', quiet=True)
    if sia is None:
        sia = SentimentIntensityAnalyzer()
        print("VADER sentiment analyzer loaded.")

    # --- DistilBART (summarization backup) ---
    if summarizer is None:
        try:
            from transformers import pipeline
            import warnings
            warnings.filterwarnings("ignore")
            print("Loading summarization model: sshleifer/distilbart-cnn-12-6...")
            summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
            print("Summarization model loaded successfully.")
        except Exception as e:
            print(f"DistilBART failed to load: {e}")
            summarizer = None

    return True

# ───────────────────────────────────────────────
# SENTIMENT ANALYSIS
# ───────────────────────────────────────────────
def analyze_sentiment(text: str) -> dict:
    if not text or len(text.strip()) == 0:
        return {"score": 0.0, "label": "Neutral"}
    if sia is None:
        init_nlp_models()
    scores = sia.polarity_scores(text)
    compound = scores['compound']
    if compound >= 0.05:
        label = 'Positive'
    elif compound <= -0.05:
        label = 'Negative'
    else:
        label = 'Neutral'
    return {"score": round(compound, 2), "label": label}

# ───────────────────────────────────────────────
# BIAS DETECTION — WORD LIST FALLBACK
# (used only during initial NewsAPI fetch, not for article detail page)
# ───────────────────────────────────────────────
STRONG_BIAS_WORDS = [
    "radical", "extreme", "extremist", "far-left", "far-right", "fascist",
    "communist", "terrorist", "regime", "propaganda", "catastrophe",
    "devastating", "corrupt", "criminal", "evil", "disgusting", "outrageous",
    "shameful", "horrific", "despicable", "pathetic", "heroic", "magnificent",
    "glorious", "perfect", "flawless", "deep state", "fake news", "cover-up",
    "conspiracy", "hoax", "rigged", "stolen", "illegitimate", "cabal",
    "disaster", "destroy", "brainwash", "indoctrination", "puppet"
]

SLIGHT_BIAS_WORDS = [
    "apparently", "supposedly", "allegedly", "claimed", "insists", "refuses",
    "slammed", "blasted", "ripped", "failed", "struggling", "controversial",
    "disputed", "so-called", "questionable", "problematic", "alarming",
    "concerning", "unprecedented", "massive", "stunning", "doubles down",
    "pushes back", "hits back", "yet again", "once again", "continues to",
    "defends", "attacks", "admits", "concedes"
]

NEUTRAL_INDICATORS = [
    "according to", "said", "stated", "reported", "confirmed", "announced",
    "published", "found", "showed", "data shows", "research shows",
    "study finds", "however", "in contrast", "meanwhile", "officials said",
    "spokesperson said", "in a statement", "both sides", "multiple sources"
]

def _analyze_bias_wordlist(text: str) -> dict:
    """Lexicon-based bias detection — used for initial article fetch scoring."""
    text_lower = text.lower()
    strong_hits = sum(1 for word in STRONG_BIAS_WORDS if word in text_lower)
    slight_hits = sum(1 for word in SLIGHT_BIAS_WORDS if word in text_lower)
    neutral_hits = sum(1 for word in NEUTRAL_INDICATORS if word in text_lower)
    raw = (strong_hits * 0.25) + (slight_hits * 0.10) - (neutral_hits * 0.08)
    words = text.split()
    word_count = len(words) if words else 1
    length_factor = min(1.0, 50 / word_count)
    final_score = max(0.0, min(1.0, raw + length_factor * 0.05))
    if final_score < 0.35:
        label = "Neutral"
    elif final_score <= 0.65:
        label = "Slight Bias"
    else:
        label = "Strong Bias"
    return {"score": round(final_score, 2), "label": label}

def analyze_bias(text: str) -> dict:
    """Public bias function — uses wordlist only now. ML model removed."""
    if not text or len(text.strip()) == 0:
        return {"score": 0.0, "label": "Neutral"}
    return _analyze_bias_wordlist(text)


def _get_groq_client():
    """Returns a configured Groq client, or None if key missing."""
    if not GROQ_API_KEY:
        print("Groq skipped: no API key set.")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        return client
    except Exception as e:
        print(f"Groq init failed: {e}")
        return None

# ───────────────────────────────────────────────
# SCRAPING
# ───────────────────────────────────────────────
def _scrape_article(url: str) -> str:
    """Try to scrape full article text using newspaper3k."""
    try:
        from newspaper import Article as NewsArticle
        news_art = NewsArticle(
            url,
            browser_user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        )
        news_art.download()
        news_art.parse()
        if news_art.text and len(news_art.text.split()) > 80:
            print(f"Scraped {len(news_art.text.split())} words from {url}")
            return news_art.text
    except Exception as e:
        print(f"Scraping failed for {url}: {e}")
    return ""


def _summarize_and_analyze_with_groq(text: str, title: str, description: str) -> dict:
    """
    Single Groq call that returns both summary AND bias analysis.
    Returns dict with keys: summary, bias_label, bias_score
    """
    client = _get_groq_client()
    if not client:
        return {}
    try:
        words = text.split()
        clipped = " ".join(words[:1200])
        prompt = (
            f"You are a professional news analyst. Read the following article carefully.\n\n"
            f"Article title: {title}\n\n"
            f"Article text:\n{clipped}\n\n"
            f"Respond ONLY in this exact JSON format with no extra text before or after:\n"
            f"{{\n"
            f'  "summary": "write a 6-8 sentence detailed summary here covering what happened, '
            f'who is specifically involved with names and organisations, '
            f'any specific numbers dates or figures, reactions or responses, '
            f'and why this news matters. Write in third person. '
            f'Do not start with This article.",\n'
            f'  "bias_label": "one of exactly: Neutral or Slight Bias or Strong Bias",\n'
            f'  "bias_score": 0.0\n'
            f"}}\n\n"
            f"Rules for bias_score:\n"
            f"- If bias_label is Neutral: bias_score must be between 0.05 and 0.30\n"
            f"- If bias_label is Slight Bias: bias_score must be between 0.35 and 0.65\n"
            f"- If bias_label is Strong Bias: bias_score must be between 0.70 and 0.95\n\n"
            f"Rules for bias assessment:\n"
            f"- Neutral: factual reporting, balanced language, uses said/reported/confirmed\n"
            f"- Slight Bias: some loaded words, mild framing, slightly one-sided tone\n"
            f"- Strong Bias: clearly one-sided, emotionally charged, propaganda-like language"
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.2
        )
        raw = response.choices[0].message.content.strip()
        print(f"Groq raw response preview: {raw[:120]}...")

        # Clean markdown code blocks if model adds them
        raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        data = json.loads(raw)

        summary = data.get('summary', '').strip()
        bias_label = data.get('bias_label', 'Neutral').strip()
        bias_score = float(data.get('bias_score', 0.1))

        # Validate bias label
        if bias_label not in ['Neutral', 'Slight Bias', 'Strong Bias']:
            bias_label = 'Neutral'
            bias_score = 0.1

        # Validate bias score range
        bias_score = round(max(0.0, min(1.0, bias_score)), 2)

        word_count = len(summary.split())
        print(f"Groq Summary: {word_count} words | Bias: {bias_label} ({bias_score})")

        if word_count < 30:
            print(f"Summary too short ({word_count} words) — treating as failure")
            return {}

        return {
            'summary': summary,
            'bias_label': bias_label,
            'bias_score': bias_score
        }

    except json.JSONDecodeError as e:
        print(f"Groq JSON parse failed: {e} | Raw: {raw[:200]}")
        return {}
    except Exception as e:
        print(f"Groq analysis failed: {e}")
        return {}

# ───────────────────────────────────────────────
# DISTILBART FALLBACK
# ───────────────────────────────────────────────
def _summarize_with_distilbart(text: str) -> str:
    """DistilBART local model — only used when Groq is unavailable."""
    global summarizer
    if summarizer is None:
        return ""
    try:
        words = text.split()
        if len(words) > 600:
            text = " ".join(words[:600])
        input_length = len(text.split())
        max_len = min(180, max(60, input_length - 10))
        result = summarizer(
            text,
            max_length=max_len,
            min_length=40,
            do_sample=False,
            truncation=True
        )
        summary = result[0]['summary_text'].strip()
        print(f"DistilBART summary: {summary[:80]}...")
        return summary
    except Exception as e:
        print(f"DistilBART failed: {e}")
        return ""

# ───────────────────────────────────────────────
# MAIN SUMMARIZATION FUNCTION
# ───────────────────────────────────────────────
def summarize_text(
    text: str,
    article_url: str = None,
    title: str = None,
    description: str = None,
    content: str = None
) -> dict:
   
    safe_title = title or "Article"
    safe_desc = description or ""
    safe_content = content or ""

    # --- Scrape full article text ---
    scraped_text = ""
    if article_url:
        scraped_text = _scrape_article(article_url)

    
    combined_parts = []
    if scraped_text:
        combined_parts.append(scraped_text)
    if safe_content and safe_content not in scraped_text:
        combined_parts.append(safe_content)
    if safe_desc and safe_desc not in scraped_text:
        combined_parts.append(safe_desc)
    if text and len(text.split()) >= 30 and text not in scraped_text:
        combined_parts.append(text)

    combined_text = " ".join(combined_parts).strip()


    if combined_text and len(combined_text.split()) >= 40 and GROQ_API_KEY:
        print(f"Level 1: Groq with {len(combined_text.split())} words of combined text")
        result = _summarize_and_analyze_with_groq(combined_text, safe_title, safe_desc)
        if result and result.get('summary'):
            return result

    
    if GROQ_API_KEY:
        print(f"Level 2: Groq with title + description + content")
        fallback_text = f"{safe_title}. {safe_desc} {safe_content}".strip()
        result = _summarize_and_analyze_with_groq(fallback_text, safe_title, safe_desc)
        if result and result.get('summary'):
            return result


    if combined_text:
        print(f"Level 3: Trying DistilBART")
        summary = _summarize_with_distilbart(combined_text)
        bias = _analyze_bias_wordlist(combined_text)
        if summary:
            return {
                'summary': summary,
                'bias_label': bias['label'],
                'bias_score': bias['score']
            }

    
    print("All summarization methods failed. Using sentence extraction fallback.")
    base = combined_text if combined_text else f"{safe_title}. {safe_desc}"
    sentences = re.split(r'(?<=[.!?])\s+', base)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    bias = _analyze_bias_wordlist(base)
    return {
        'summary': " ".join(sentences[:4]) or "Summary not available for this article.",
        'bias_label': bias['label'],
        'bias_score': bias['score']
    }
