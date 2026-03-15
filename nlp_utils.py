# nlp_utils.py - NLP utilities for sentiment analysis, bias detection, and summarization
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import re

sia = None
summarizer = None
bias_classifier = None
GEMINI_API_KEY = None

def set_gemini_key(key: str):
    """Called from app.py to pass the Gemini key without circular import."""
    global GEMINI_API_KEY
    GEMINI_API_KEY = key

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

    # --- DistilBART (summarization) ---
    if summarizer is None:
        try:
            from transformers import pipeline
            import warnings
            warnings.filterwarnings("ignore")
            print("Loading summarization model: sshleifer/distilbart-cnn-12-6...")
            summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
            print("Summarization model loaded successfully.")
        except Exception as e:
            print(f"Summarization model failed to load: {e}")
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

# Word lists kept as fallback only — used when ML model is unavailable
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
    """Fallback lexicon-based bias detection used when ML model is unavailable."""
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

    # --- PRIMARY: ML model (RoBERTa trained on real news bias data) ---
    if bias_classifier is not None:
        try:
            # Model has token limits — clip to first 400 words safely
            words = text.split()
            clipped = " ".join(words[:400])
            result = bias_classifier(clipped)[0]
            label_raw = result['label']   # 'Biased' or 'Non-biased'
            confidence = result['score']

            if label_raw == 'Non-biased':
                # Low score = very neutral
                final_score = round(1 - confidence, 2)
                if final_score < 0.35:
                    label = "Neutral"
                else:
                    label = "Slight Bias"
            else:
                # Biased — decide how strongly
                final_score = round(confidence, 2)
                if confidence > 0.80:
                    label = "Strong Bias"
                else:
                    label = "Slight Bias"

            print(f"Bias ML result: {label_raw} ({confidence:.2f}) → {label}")
            return {"score": final_score, "label": label}

        except Exception as e:
            print(f"Bias ML inference failed, using word list fallback: {e}")

    # --- FALLBACK: Word list (if model not loaded or inference failed) ---
    print("Using word list fallback for bias detection.")
    return _analyze_bias_wordlist(text)


# ───────────────────────────────────────────────
# SUMMARIZATION
# ───────────────────────────────────────────────

def _scrape_article(url: str) -> str:
    """Try to scrape full article text. Returns empty string on failure."""
    try:
        from newspaper import Article as NewsArticle
        news_art = NewsArticle(url, browser_user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        news_art.download()
        news_art.parse()
        if news_art.text and len(news_art.text.split()) > 50:
            print(f"Scraped {len(news_art.text.split())} words from {url}")
            return news_art.text
    except Exception as e:
        print(f"Scraping failed for {url}: {e}")
    return ""

def _summarize_with_distilbart(text: str) -> str:
    """Run DistilBART on text. Returns empty string on failure."""
    global summarizer
    if summarizer is None:
        return ""
    try:
        words = text.split()
        if len(words) > 900:
            text = " ".join(words[:900])
        result = summarizer(text, max_length=150, min_length=50, do_sample=False)
        summary = result[0]['summary_text'].strip()
        print(f"DistilBART summary: {summary[:80]}...")
        return summary
    except Exception as e:
        print(f"DistilBART failed: {e}")
        return ""

def _summarize_with_gemini(text: str, title: str, description: str) -> str:
    """Send actual text to Gemini for summarization. Returns empty string on failure."""
    if not GEMINI_API_KEY:
        print("Gemini skipped: no API key set.")
        return ""
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')

        if text and len(text.split()) >= 50:
            words = text.split()
            clipped = " ".join(words[:600])
            prompt = (
                f"You are a news summarizer. Read the following article text carefully and "
                f"write a clear, informative 4-5 sentence summary covering the main points. "
                f"Do not add any information not present in the text.\n\n"
                f"Article title: {title}\n\n"
                f"Article text:\n{clipped}"
            )
        else:
            prompt = (
                f"You are a news summarizer. Using ONLY the following title and description, "
                f"write a 3-4 sentence summary. Do not invent facts.\n\n"
                f"Title: {title}\n"
                f"Description: {description}"
            )

        response = model.generate_content(prompt)
        summary = response.text.strip()
        print(f"Gemini summary: {summary[:80]}...")
        return summary
    except Exception as e:
        print(f"Gemini failed: {e}")
        return ""

def summarize_text(text: str, article_url=None, title=None, description=None) -> str:
    safe_title = title or "Article"
    safe_desc = description or ""

    # --- LEVEL 1: Scrape if needed, then try DistilBART ---
    content = text if text and len(text.split()) >= 50 else ""
    if not content and article_url:
        content = _scrape_article(article_url)

    if content:
        result = _summarize_with_distilbart(content)
        if result:
            return result

    # --- LEVEL 2: Gemini with whatever content we have ---
    result = _summarize_with_gemini(content, safe_title, safe_desc)
    if result:
        return result

    # --- LEVEL 3: Sentence extraction last resort ---
    print("All summarization methods failed. Using sentence extraction fallback.")
    base = content if content else f"{safe_title}. {safe_desc}"
    sentences = re.split(r'(?<=[.!?])\s+', base)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    return " ".join(sentences[:4]) or "No summary available for this article."