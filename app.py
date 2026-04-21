import os
import re
import secrets
import datetime
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from sqlalchemy import or_
import resend
from nlp_utils import (
    summarize_text, analyze_sentiment, analyze_bias,
    init_nlp_models, _analyze_bias_wordlist, set_gemini_key, set_groq_key
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NEWS_API_BASE = 'https://newsapi.org/v2'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now(datetime.timezone.utc)}

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- DATABASE MODELS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self): return True

    @property
    def is_authenticated(self): return True

    @property
    def is_anonymous(self): return False

    def get_id(self): return str(self.id)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    search_query = db.Column(db.String(200), nullable=False)
    searched_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(1000), unique=True, nullable=False)
    image_url = db.Column(db.String(1000))
    source_name = db.Column(db.String(200))
    category = db.Column(db.String(50))
    published_at = db.Column(db.String(100))
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    content = db.Column(db.Text)
    summary = db.Column(db.Text)
    bias_score = db.Column(db.Float)
    bias_label = db.Column(db.String(50))
    sentiment_score = db.Column(db.Float)
    sentiment_label = db.Column(db.String(50))

class SavedArticle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    saved_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    __table_args__ = (db.UniqueConstraint('user_id', 'article_id', name='_user_article_uc'),)

class ReadHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

# --- HELPER FUNCTIONS ---

def send_reset_email(to_email, username, reset_link):
    resend.api_key = os.getenv('RESEND_API_KEY')
    year = datetime.datetime.now().year
    html = f"""
    <!DOCTYPE html>
    <html><body style="margin:0;padding:0;background-color:#0f0f0f;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
        <tr><td align="center">
          <table width="480" cellpadding="0" cellspacing="0" style="background-color:#1e1e1e;border-radius:12px;">
            <tr>
              <td style="background-color:#0f0f0f;padding:28px 40px;text-align:center;border-bottom:1px solid #374151;">
                <span style="font-size:1.6rem;font-weight:800;color:#ffffff;">News<span style="color:#ff0028;">Lens</span></span>
              </td>
            </tr>
            <tr>
              <td style="padding:40px;">
                <h2 style="color:#f9f9f9;font-size:1.4rem;margin:0 0 12px 0;">Reset Your Password</h2>
                <p style="color:#9ca3af;font-size:0.95rem;line-height:1.6;margin:0 0 10px 0;">
                  Hi <strong style="color:#f9f9f9;">{username}</strong>,
                </p>
                <p style="color:#9ca3af;font-size:0.95rem;line-height:1.6;margin:0 0 28px 0;">
                  We received a request to reset your NewsLens password. Click below to set a new one.
                </p>
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td align="center" style="padding-bottom:28px;">
                      <a href="{reset_link}" style="display:inline-block;padding:14px 36px;background-color:#ff0028;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:1rem;">
                        Reset Password
                      </a>
                    </td>
                  </tr>
                </table>
                <div style="background-color:#27272a;border-radius:8px;padding:16px 20px;margin-bottom:28px;">
                  <p style="color:#9ca3af;font-size:0.85rem;margin:0;">
                    This link expires in <strong style="color:#f9f9f9;">15 minutes</strong>.
                  </p>
                </div>
                <p style="color:#6b7280;font-size:0.85rem;margin:0;">
                  If you didn't request this, you can safely ignore this email.
                </p>
              </td>
            </tr>
            <tr>
              <td style="background-color:#0f0f0f;padding:20px 40px;text-align:center;border-top:1px solid #374151;">
                <p style="color:#4b5563;font-size:0.8rem;margin:0;">© {year} NewsLens. All rights reserved.</p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """
    try:
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": to_email,
            "subject": "NewsLens — Reset Your Password",
            "html": html
        })
        return True
    except Exception as e:
        print(f"Resend error: {e}")
        return False

def is_valid_email(email):
    return re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email) is not None

def format_date(date_string):
    try:
        if not date_string:
            return 'N/A'
        dt = datetime.datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except:
        return date_string

def process_and_save_article(item, category):
    title, url = item.get('title'), item.get('url')
    if not title or not url or '[Removed]' in title:
        return None

    existing = Article.query.filter_by(url=url).first()
    if existing:
        return existing

    desc = item.get('description') or ''
    raw_content = item.get('content') or ''
    raw_content = re.sub(r'\s*\[\+\d+ chars\]$', '', raw_content).strip()

    # Include raw_content in base_text for better fetch-time analysis
    base_text = f"{title}. {desc} {raw_content}".strip()

    sentiment = analyze_sentiment(base_text)
    bias = _analyze_bias_wordlist(base_text)

    image_url = item.get('urlToImage') or ''
    if len(image_url) < 10:
        image_url = ''

    new_article = Article(
        title=title, description=desc, url=url,
        content=raw_content,
        image_url=image_url,
        source_name=item.get('source', {}).get('name', 'Unknown'),
        category=category,
        published_at=format_date(item.get('publishedAt', '')),
        bias_score=bias['score'], bias_label=bias['label'],
        sentiment_score=sentiment['score'], sentiment_label=sentiment['label']
    )
    db.session.add(new_article)
    return new_article

def fetch_category_news(category):
    saved_count = 0

    def fetch_api(endpoint, params):
        params.update({'apiKey': NEWS_API_KEY, 'language': 'en', 'pageSize': 100})
        try:
            res = requests.get(f'{NEWS_API_BASE}/{endpoint}', params=params, timeout=10)
            return res.json().get('articles', []) if res.status_code == 200 else []
        except:
            return []

    articles_data = []
    if category in ['tech', 'science', 'culture', 'general', 'health']:
        cat_map = {'tech': 'technology', 'culture': 'entertainment'}
        articles_data = fetch_api('top-headlines', {'category': cat_map.get(category, category)})
    elif category == 'politics':
        articles_data = fetch_api('everything', {'q': 'politics OR government OR election OR policy', 'sortBy': 'publishedAt'})
    elif category == 'ai':
        tech = fetch_api('top-headlines', {'category': 'technology'})
        ai_kw = ['artificial intelligence', 'chatgpt', 'openai', 'llm', 'machine learning',
                 'large language model', 'generative ai', 'neural network', 'deepmind', 'gemini']
        articles_data = [i for i in tech if any(kw in ((i.get('title') or '') + (i.get('description') or '')).lower() for kw in ai_kw)]
        articles_data.extend(fetch_api('everything', {'q': 'artificial intelligence OR ChatGPT OR OpenAI', 'sortBy': 'publishedAt'}))

    for item in articles_data:
        if process_and_save_article(item, category):
            saved_count += 1
    db.session.commit()
    return saved_count

def cleanup_old_articles():
    """
    FIX: Smarter deletion — only delete articles that:
      1. Are older than 5 days (raised from 3 days — gives more breathing room)
      2. AND have no summary yet (unvisited — no one ever read them)
      3. AND are not saved by any user
      4. AND are not in anyone's read history

    This means:
      - Articles users have read or saved are NEVER deleted
      - Articles with full summaries (visited) are kept longer
      - Only truly stale, unread, unsaved articles get cleaned up
      - You always have enough articles because visited ones accumulate

    Old logic deleted ALL articles older than 3 days regardless — this
    broke saved article links and reading history, and left the site
    with very few articles right after a cleanup.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
    cutoff_naive = cutoff.replace(tzinfo=None)

    # Find article IDs that are protected (saved or read by someone)
    saved_ids = {s.article_id for s in SavedArticle.query.all()}
    read_ids = {r.article_id for r in ReadHistory.query.all()}
    protected_ids = saved_ids | read_ids

    # Delete only: old + no summary + not protected
    deleted = 0
    old_unvisited = Article.query.filter(
        Article.fetched_at < cutoff_naive,
        Article.summary == None
    ).all()

    for article in old_unvisited:
        if article.id not in protected_ids:
            db.session.delete(article)
            deleted += 1

    if deleted > 0:
        db.session.commit()
        print(f"Cleanup: removed {deleted} old unvisited articles")

# --- ROUTES ---

@app.route('/')
def home():
    latest = Article.query.order_by(Article.fetched_at.desc()).first()
    now = datetime.datetime.now(datetime.timezone.utc)

    if not latest or (now - latest.fetched_at.replace(tzinfo=datetime.timezone.utc)).total_seconds() > 3600:
        # FIX: Run smarter cleanup before fetching fresh articles.
        # Old code deleted everything older than 3 days unconditionally.
        # New cleanup only removes old unvisited unsaved articles.
        cleanup_old_articles()

        for cat in ['tech', 'ai', 'science', 'culture', 'general', 'health', 'politics']:
            fetch_category_news(cat)

    arts = Article.query.order_by(Article.published_at.desc()).limit(29).all()
    return render_template('index.html',
                           hero=arts[0] if arts else None,
                           trending=arts[1:11],
                           grid=arts[11:29])

@app.route('/category/<category>')
def category_view(category):
    articles = Article.query.filter_by(category=category).order_by(Article.published_at.desc()).limit(50).all()
    return render_template('category.html', articles=articles, category=category)

@app.route('/article/<int:id>')
def article_detail(id):
    article = db.session.get(Article, id)
    if not article:
        abort(404)

    if not article.summary or not str(article.summary).strip():
        # FIX: Scrape once here. Pass the result as `text` to summarize_text().
        # summarize_text() will NOT scrape again if we pass good text.
        # Old code: article_detail scraped, then summarize_text scraped again = 2 hits.
        # New code: scrape once here, pass result in, summarize_text trusts it.
        full_text = ""
        try:
            from newspaper import Article as NewsArticle
            news_art = NewsArticle(
                article.url,
                browser_user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                request_timeout=15,
                fetch_images=False,
                memoize_articles=False,
            )
            news_art.download()
            news_art.parse()
            if news_art.text and len(news_art.text.split()) > 50:
                full_text = news_art.text
                print(f"article_detail scraped {len(full_text.split())} words")
            else:
                print(f"article_detail scrape returned too little — using title+desc fallback")
        except Exception as e:
            print(f"article_detail scraping failed: {e}")

        # If scraping failed, fall back to title + description
        if not full_text:
            full_text = f"{article.title}. {article.description or ''}"

        try:
            result = summarize_text(
                full_text,           # pass scraped text — summarize_text won't re-scrape
                article_url=article.url,  # kept as backup only if full_text is too short
                title=article.title,
                description=article.description,
                content=article.content
            )

            # Re-run bias with full text
           
            article.summary = result.get('summary', 'Summary not available.')
            article.bias_label = result.get('bias_label', article.bias_label)
            article.bias_score = result.get('bias_score', article.bias_score)
            # Re-run sentiment with full text
            if full_text and len(full_text.split()) > 30:
                sentiment_res = analyze_sentiment(full_text)
                article.sentiment_score = sentiment_res['score']
                article.sentiment_label = sentiment_res['label']

        except Exception as e:
            print(f"NLP failed: {e}")
            article.summary = "Summary not available."

        db.session.commit()

    if current_user.is_authenticated:
        if not ReadHistory.query.filter_by(user_id=current_user.id, article_id=id).first():
            db.session.add(ReadHistory(user_id=current_user.id, article_id=id))
            db.session.commit()

    related = Article.query.filter(
        Article.category == article.category,
        Article.id != article.id
    ).order_by(Article.published_at.desc()).limit(3).all()

    saved = (current_user.is_authenticated and
             SavedArticle.query.filter_by(user_id=current_user.id, article_id=article.id).first() is not None)

    return render_template('article.html', article=article, related=related, saved=saved)

@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    grouped = {}
    if q:
        db.session.add(SearchHistory(user_id=current_user.id, search_query=q))

        try:
            res = requests.get(f'{NEWS_API_BASE}/everything', params={
                'apiKey': NEWS_API_KEY, 'q': q, 'language': 'en',
                'sortBy': 'relevancy', 'pageSize': 100
            }, timeout=15)
            if res.status_code == 200:
                for item in res.json().get('articles', []):
                    process_and_save_article(item, 'search')
        except Exception as e:
            print(f"Search fetch error: {e}")

        db.session.commit()

        keywords = q.split()
        db_filters = []
        for kw in keywords:
            db_filters.append(Article.title.ilike(f'%{kw}%'))
            db_filters.append(Article.description.ilike(f'%{kw}%'))
            db_filters.append(Article.summary.ilike(f'%{kw}%'))

        candidates = Article.query.filter(or_(*db_filters)).all()
        scored = []
        for art in candidates:
            title_text = art.title or ''
            desc_text = f"{art.description or ''} {art.summary or ''} {art.source_name or ''}"
            score = 0
            matches_all = True
            for kw in keywords:
                pattern = re.compile(
                    rf'\b{re.escape(kw)}\b' if len(kw) <= 3 else re.escape(kw),
                    re.IGNORECASE
                )
                t = len(pattern.findall(title_text))
                d = len(pattern.findall(desc_text))
                if t == 0 and d == 0:
                    matches_all = False
                    break
                score += (t * 5) + d
            if matches_all:
                scored.append((score, art.published_at or '', art))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for _, _, art in scored[:100]:
            source = art.source_name or 'Unknown'
            if source not in grouped:
                grouped[source] = []
            if len(grouped[source]) < 4:
                grouped[source].append(art)

    return render_template('search_results.html', grouped_articles=grouped, q=q)

@app.route('/dashboard')
@login_required
def dashboard():
    reads = ReadHistory.query.filter_by(user_id=current_user.id).all()
    read_ids = [r.article_id for r in reads]
    read_articles = Article.query.filter(Article.id.in_(read_ids)).all() if read_ids else []

    saved_count = SavedArticle.query.filter_by(user_id=current_user.id).count()
    total = len(read_articles) or 1
    avg_bias = sum(a.bias_score for a in read_articles if a.bias_score) / total if read_articles else 0

    bias_breakdown = {
        'neutral': (len([a for a in read_articles if a.bias_label == 'Neutral']) / total) * 100,
        'slight':  (len([a for a in read_articles if 'Slight' in (a.bias_label or '')]) / total) * 100,
        'strong':  (len([a for a in read_articles if 'Strong' in (a.bias_label or '')]) / total) * 100,
    }
    sentiment_breakdown = {
        'positive': (len([a for a in read_articles if a.sentiment_label == 'Positive']) / total) * 100,
        'negative': (len([a for a in read_articles if a.sentiment_label == 'Negative']) / total) * 100,
        'neutral':  (len([a for a in read_articles if a.sentiment_label == 'Neutral']) / total) * 100,
    }

    cat_counts = {}
    for a in read_articles:
        cat_counts[a.category] = cat_counts.get(a.category, 0) + 1

    top_categories = [
        {'name': c, 'pct': (n / total) * 100}
        for c, n in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    recent_read = Article.query.join(ReadHistory).filter(
        ReadHistory.user_id == current_user.id
    ).order_by(ReadHistory.read_at.desc()).limit(5).all()

    recent_saved = Article.query.join(SavedArticle).filter(
        SavedArticle.user_id == current_user.id
    ).order_by(SavedArticle.saved_at.desc()).limit(4).all()

    return render_template('dashboard.html',
        reads_count=len(reads),
        saved_count=saved_count,
        avg_bias=avg_bias,
        total_ai_summaries=len(read_articles),
        bias_breakdown=bias_breakdown,
        sentiment_breakdown=sentiment_breakdown,
        top_categories=top_categories,
        recent_read=recent_read,
        recent_saved=recent_saved
    )

@app.route('/saved')
@login_required
def saved():
    articles = Article.query.join(SavedArticle).filter(
        SavedArticle.user_id == current_user.id
    ).order_by(SavedArticle.saved_at.desc()).all()
    return render_template('saved.html', articles=articles)

@app.route('/history')
@login_required
def history():
    articles = Article.query.join(ReadHistory).filter(
        ReadHistory.user_id == current_user.id
    ).order_by(ReadHistory.read_at.desc()).all()
    return render_template('history.html', articles=articles)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        un = request.form.get('username', '').strip()
        em = request.form.get('email', '').strip()
        pw = request.form.get('password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if len(un) < 3:
            flash('Username must be at least 3 characters.', 'error')
            return redirect(url_for('register'))
        if not is_valid_email(em):
            flash('Invalid email address.', 'error')
            return redirect(url_for('register'))
        if len(pw) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return redirect(url_for('register'))
        if pw != confirm_pw:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('register'))
        if User.query.filter((User.username == un) | (User.email == em)).first():
            flash('Username or email already taken.', 'error')
            return redirect(url_for('register'))

        user = User(username=un, email=em)
        user.set_password(pw)
        db.session.add(user)
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(request.args.get('next') or url_for('home'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/save/<int:article_id>', methods=['POST'])
@login_required
def toggle_save(article_id):
    existing = SavedArticle.query.filter_by(user_id=current_user.id, article_id=article_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'saved': False})
    db.session.add(SavedArticle(user_id=current_user.id, article_id=article_id))
    db.session.commit()
    return jsonify({'saved': True})

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            PasswordResetToken.query.filter_by(user_id=user.id, used=False).delete()
            token = secrets.token_urlsafe(48)
            expires = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
            db.session.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires))
            db.session.commit()
            send_reset_email(user.email, user.username, url_for('reset_password', token=token, _external=True))

        flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    record = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not record or record.expires_at < datetime.datetime.utcnow():
        flash('This link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        pw = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(pw) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('reset_password.html', token=token)
        if pw != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        user = db.session.get(User, record.user_id)
        user.set_password(pw)
        record.used = True
        db.session.commit()
        flash('Password updated! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)

# --- SETTINGS ROUTES ---

@app.route('/settings')
@login_required
def settings():
    reads_count = ReadHistory.query.filter_by(user_id=current_user.id).count()
    saved_count = SavedArticle.query.filter_by(user_id=current_user.id).count()
    return render_template('settings.html', reads_count=reads_count, saved_count=saved_count)

@app.route('/settings/username', methods=['POST'])
@login_required
def settings_username():
    new_username = request.form.get('new_username', '').strip()
    current_password = request.form.get('current_password', '')

    if not current_user.check_password(current_password):
        flash('Incorrect current password.', 'error')
        return redirect(url_for('settings') + '#change-username')
    if len(new_username) < 3:
        flash('Username must be at least 3 characters.', 'error')
        return redirect(url_for('settings') + '#change-username')
    if new_username == current_user.username:
        flash('That is already your username.', 'error')
        return redirect(url_for('settings') + '#change-username')
    if User.query.filter_by(username=new_username).first():
        flash('That username is already taken.', 'error')
        return redirect(url_for('settings') + '#change-username')

    current_user.username = new_username
    db.session.commit()
    flash('Username updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/password', methods=['POST'])
@login_required
def settings_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_new_password = request.form.get('confirm_new_password', '')

    if not current_user.check_password(current_password):
        flash('Incorrect current password.', 'error')
        return redirect(url_for('settings') + '#change-password')
    if len(new_password) < 8:
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('settings') + '#change-password')
    if new_password != confirm_new_password:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('settings') + '#change-password')
    if current_user.check_password(new_password):
        flash('New password must be different from your current password.', 'error')
        return redirect(url_for('settings') + '#change-password')

    current_user.set_password(new_password)
    db.session.commit()
    flash('Password updated successfully!', 'success')
    return redirect(url_for('settings'))

# --- SEARCH HISTORY API ---

@app.route('/api/search-history')
@login_required
def get_search_history():
    history = SearchHistory.query.filter_by(user_id=current_user.id).order_by(
        SearchHistory.searched_at.desc()
    ).limit(10).all()
    return jsonify({'history': [{'id': h.id, 'query': h.search_query} for h in history]})

@app.route('/api/search-history/<int:id>', methods=['DELETE'])
@login_required
def delete_search_history(id):
    entry = SearchHistory.query.filter_by(id=id, user_id=current_user.id).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
    return jsonify({'deleted': True})

@app.route('/api/search-history/clear', methods=['DELETE'])
@login_required
def clear_search_history():
    SearchHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({'cleared': True})

# --- FETCH NEWS (protected by secret key) ---

@app.route('/fetch-news')
def fetch_news():
    secret = request.args.get('secret', '')
    if secret != os.getenv('FETCH_SECRET', ''):
        return jsonify({'error': 'Unauthorized'}), 403

    cleanup_old_articles()
    total = 0
    for cat in ['tech', 'ai', 'science', 'culture', 'general', 'health', 'politics']:
        total += fetch_category_news(cat)
    return jsonify({'count': total})

# --- INITIALIZATION ---

GROQ_API_KEY = os.getenv('GROQ_API_KEY')

with app.app_context():
    db.create_all()
    set_gemini_key(GEMINI_API_KEY)  # kept for compatibility, does nothing
    set_groq_key(GROQ_API_KEY)
    init_nlp_models()
    if Article.query.count() == 0:
        print("DB empty — fetching initial news...")
        for cat in ['tech', 'ai', 'science', 'culture', 'general', 'health', 'politics']:
            fetch_category_news(cat)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)