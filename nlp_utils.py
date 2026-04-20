# nlp_utils.py - NLP utilities for sentiment analysis, bias detection, and summarization

import re
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# --- Global model instances ---
sia = None
summarizer = None
bias_classifier = None
GROQ_API_KEY = None

def set_gemini_key(key: str):
    """Kept for backward compatibility with app.py — does nothing now."""
    pass

def set_groq_key(key: str):
    """Called from app.py to pass the Groq key."""
    global GROQ_API_KEY
    GROQ_API_KEY = key

def init_nlp_models():
    global sia, summarizer, bias_classifier

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

    # --- RoBERTa (bias detection) ---
    if bias_classifier is None:
        try:
            from transformers import pipeline
            import warnings
            warnings.filterwarnings("ignore")
            print("Loading bias detection model: mediabiasgroup/da-RoBERTa-BABE...")
            bias_classifier = pipeline(
                "text-classification",
                model="mediabiasgroup/da-RoBERTa-BABE"
            )
            print("Bias detection model loaded successfully.")
        except Exception as e:
            print(f"Bias model failed to load, word list fallback will be used: {e}")
            bias_classifier = None

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
# BIAS DETECTION
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
    """Fallback lexicon-based bias detection."""
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
    if not text or len(text.strip()) == 0:
        return {"score": 0.0, "label": "Neutral"}
    if bias_classifier is not None:
        try:
            words = text.split()
            clipped = " ".join(words[:300])
            result = bias_classifier(clipped, truncation=True, max_length=512)[0]
            label_raw = result['label']
            confidence = result['score']
            if label_raw == 'LABEL_1' or label_raw == 'Non-biased':
                final_score = round(1 - confidence, 2)
                label = "Neutral" if final_score < 0.35 else "Slight Bias"
            else:
                final_score = round(confidence, 2)
                label = "Strong Bias" if confidence > 0.80 else "Slight Bias"
            print(f"Bias ML result: {label_raw} ({confidence:.2f}) → {label}")
            return {"score": final_score, "label": label}
        except Exception as e:
            print(f"Bias ML inference failed, using word list fallback: {e}")
    print("Using word list fallback for bias detection.")
    return _analyze_bias_wordlist(text)

# ───────────────────────────────────────────────
# SUMMARIZATION
# ───────────────────────────────────────────────
def _scrape_article(url: str) -> str:
    """Try to scrape full article text."""
    try:
        from newspaper import Article as NewsArticle
        news_art = NewsArticle(url, browser_user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        news_art.download()
        news_art.parse()
        if news_art.text and len(news_art.text.split()) > 80:
            print(f"Scraped {len(news_art.text.split())} words from {url}")
            return news_art.text
    except Exception as e:
        print(f"Scraping failed for {url}: {e}")
    return ""

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

def _summarize_with_groq_text(text: str, title: str, description: str) -> str:
    """Level 1 — Groq with full scraped/combined article text."""
    client = _get_groq_client()
    if not client:
        return ""
    try:
        words = text.split()
        clipped = " ".join(words[:1200])
        prompt = (
            f"You are a professional news summarizer. Read the following article carefully "
            f"and write a detailed, informative summary of 6-8 sentences. "
            f"You must cover: what happened, who is specifically involved (names, organisations), "
            f"any specific numbers, dates or figures mentioned, any reactions or responses, "
            f"and why this news matters. "
            f"Write in third person. Do not start with 'This article'. "
            f"Do not add any information not present in the text below. "
            f"Be specific — vague summaries are not acceptable.\n\n"
            f"Article title: {title}\n\n"
            f"Article text:\n{clipped}\n\n"
            f"Write the summary directly with no preamble or intro phrase."
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.3
        )
        summary = response.choices[0].message.content.strip()
        word_count = len(summary.split())
        print(f"Groq Level 1: {word_count} words")
        if word_count >= 80:
            return summary
        else:
            print(f"Level 1 summary too short ({word_count} words) — falling to Level 2")
            return ""
    except Exception as e:
        print(f"Groq Level 1 failed: {e}")
        return ""

def _summarize_with_groq_title_desc(title: str, description: str, content: str = "") -> str:
    """Level 2 — Groq with title + description + content only."""
    client = _get_groq_client()
    if not client:
        return ""
    try:
        extra = content if content and content not in description else ""
        input_text = f"{description} {extra}".strip()
        prompt = (
            f"You are a professional news summarizer. You only have limited preview text "
            f"from this article, not the full content. Based only on what is provided below, "
            f"write an honest summary of 4-5 sentences covering what happened, who is involved, "
            f"and why it matters. Only use facts present in the text. "
            f"Do not pad or speculate. Write in third person. "
            f"Do not start with 'This article'.\n\n"
            f"Title: {title}\n"
            f"Preview text: {input_text}\n\n"
            f"Write the summary directly with no preamble."
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3
        )
        summary = response.choices[0].message.content.strip()
        word_count = len(summary.split())
        print(f"Groq Level 2: {word_count} words")
        return summary
    except Exception as e:
        print(f"Groq Level 2 failed: {e}")
        return ""

def _summarize_with_distilbart(text: str) -> str:
    """Level 3 — DistilBART local model. Last resort if Groq unavailable."""
    global summarizer
    if summarizer is None:
        return ""
    try:
        words = text.split()
        if len(words) > 600:
            text = " ".join(words[:600])
        result = summarizer(text, max_length=180, min_length=80, do_sample=False, truncation=True)
        summary = result[0]['summary_text'].strip()
        print(f"DistilBART summary: {summary[:80]}...")
        return summary
    except Exception as e:
        print(f"DistilBART failed: {e}")
        return ""

def summarize_text(text: str, article_url: str = None, title: str = None, description: str = None, content: str = None) -> str:
    """
    Main summarization function.
    Level 1 — Groq with full scraped/combined text
    Level 2 — Groq with title + description + content only
    Level 3 — DistilBART local model
    Level 4 — Sentence extraction (absolute last resort)
    """
    safe_title = title or "Article"
    safe_desc = description or ""
    safe_content = content or ""

    # Try scraping first
    scraped_text = ""
    if article_url:
        scraped_text = _scrape_article(article_url)

    # Build richest possible input
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

    # LEVEL 1: Groq with full combined text
    if combined_text and len(combined_text.split()) >= 40 and GROQ_API_KEY:
        print(f"Level 1: Groq with {len(combined_text.split())} words of combined text")
        result = _summarize_with_groq_text(combined_text, safe_title, safe_desc)
        if result:
            return result

    # LEVEL 2: Groq with title + description + content
    if GROQ_API_KEY:
        print(f"Level 2: Groq with title + description + content")
        result = _summarize_with_groq_title_desc(safe_title, safe_desc, safe_content)
        if result:
            return result

    # LEVEL 3: DistilBART
    if combined_text:
        print(f"Level 3: Trying DistilBART")
        result = _summarize_with_distilbart(combined_text)
        if result:
            return result

    # LEVEL 4: Sentence extraction
    print("All summarization methods failed. Using sentence extraction fallback.")
    base = combined_text if combined_text else f"{safe_title}. {safe_desc}"
    sentences = re.split(r'(?<=[.!?])\s+', base)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    return " ".join(sentences[:4]) or "Summary not available for this article."