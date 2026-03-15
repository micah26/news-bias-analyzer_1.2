# app.py - Main Flask application for the news aggregator
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
import re
import datetime
import requests
from functools import wraps
from nlp_utils import summarize_text, analyze_sentiment, analyze_bias, init_nlp_models

app = Flask(__name__)
app.secret_key = '1b568c10470d11afff78269b170efc6b82a4e0782252c087387cc6e839c53a5d'

# --- CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

NEWS_API_KEY = '008bf08478f2492b87f0cd850b569efe'
GEMINI_API_KEY = 'AIzaSyCoO99xN4pQeB8jn7dtoawkBKz4eFtqZ3Q'
NEWS_API_BASE = 'https://newsapi.org/v2'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    search_query = db.Column(db.String(200), nullable=False)
    searched_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(1000), unique=True, nullable=False)
    image_url = db.Column(db.String(1000))
    source_name = db.Column(db.String(200))
    category = db.Column(db.String(50))
    published_at = db.Column(db.String(100))
    fetched_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    summary = db.Column(db.Text)
    bias_score = db.Column(db.Float)
    bias_label = db.Column(db.String(50))
    sentiment_score = db.Column(db.Float)
    sentiment_label = db.Column(db.String(50))

class SavedArticle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    saved_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'article_id', name='_user_article_uc'),)

class ReadHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# --- HELPER FUNCTIONS ---
def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(pattern, email) is not None

def format_date(date_string):
    try:
        if not date_string:
            return 'N/A'
        dt = datetime.datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except:
        return date_string

def process_and_save_article(item, category):
    title = item.get('title')
    url = item.get('url')
    
    if not title or not url or '[Removed]' in title:
        return None
        
    existing = Article.query.filter_by(url=url).first()
    if existing:
        return existing
        
    description = item.get('description') or ''
    
    # Attempt to scrape full text
    full_text = ""
    try:
        from newspaper import Article as NewsArticle
        news_art = NewsArticle(url, browser_user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        news_art.download()
        news_art.parse()
        if news_art.text and len(news_art.text.split()) > 50:
            full_text = news_art.text
    except Exception as e:
        print(f"Scraping failed for {url}: {e}")
        
    if not full_text:
        full_text = f"{title}. {description}"
    
    # NLP
    bias_result = analyze_bias(full_text)
    sentiment_result = analyze_sentiment(full_text)
    summary = summarize_text(full_text, article_url=url, title=title, description=description)
    
    image_url = item.get('urlToImage')
    if not image_url or image_url == 'null' or len(image_url) < 10:
        image_url = ''
        
    new_article = Article(
        title=title,
        description=description,
        url=url,
        image_url=image_url,
        source_name=item.get('source', {}).get('name', 'Unknown'),
        category=category,
        published_at=format_date(item.get('publishedAt', '')),
        summary=summary,
        bias_score=bias_result['score'],
        bias_label=bias_result['label'],
        sentiment_score=sentiment_result['score'],
        sentiment_label=sentiment_result['label']
    )
    
    db.session.add(new_article)
    return new_article

def fetch_category_news(category):
    saved_count = 0
    
    def fetch_api(endpoint, params):
        try:
            params['apiKey'] = NEWS_API_KEY
            params['language'] = 'en'
            params['pageSize'] = 100
            res = requests.get(f'{NEWS_API_BASE}/{endpoint}', params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('status') == 'ok':
                    return data.get('articles', [])
        except Exception as e:
            print(f"Fetch error for {category}: {e}")
        return []

    articles_data = []
    
    if category in ['tech', 'science', 'culture', 'general', 'health']:
        cat_map = {'tech': 'technology', 'culture': 'entertainment'}
        api_cat = cat_map.get(category, category)
        articles_data = fetch_api('top-headlines', {'category': api_cat})
        
    elif category == 'politics':
        articles_data = fetch_api('everything', {'q': 'politics OR government OR election OR policy OR parliament OR senate', 'sortBy': 'publishedAt'})
        
    elif category == 'ai':
        # Part 1: tech fetch matched keywords
        tech_data = fetch_api('top-headlines', {'category': 'technology'})
        ai_keywords = ['artificial intelligence', 'machine learning', 'chatgpt', 'openai', 'llm', 'large language model', 'generative ai', 'neural network', 'deepmind', 'gpt-4', 'gpt-5', 'copilot', 'gemini', 'claude', 'midjourney', 'stable diffusion', 'ai model', 'ai tool', 'ai system']
        for item in tech_data:
            text = (item.get('title', '') + " " + (item.get('description', '') or '')).lower()
            if any(kw in text for kw in ai_keywords):
                articles_data.append(item)
                
        # Part 2: direct search
        everything_data = fetch_api('everything', {'q': 'artificial intelligence OR ChatGPT OR OpenAI OR machine learning', 'sortBy': 'publishedAt'})
        articles_data.extend(everything_data)
        
    for item in articles_data:
        saved = process_and_save_article(item, category)
        if saved:
            saved_count += 1
            
    db.session.commit()
    return saved_count

# --- ROUTES ---
@app.route('/')
def home():
    latest_articles = Article.query.order_by(Article.published_at.desc()).limit(29).all()
    hero = latest_articles[0] if latest_articles else None
    trending = latest_articles[1:11] if len(latest_articles) > 1 else []
    grid = latest_articles[11:29] if len(latest_articles) > 11 else []
    
    return render_template('index.html', hero=hero, trending=trending, grid=grid)

@app.route('/category/<category>')
def category_view(category):
    articles = Article.query.filter_by(category=category).order_by(Article.published_at.desc()).limit(50).all()
    return render_template('category.html', articles=articles, category=category)

@app.route('/article/<int:id>')
def article_detail(id):
    article = Article.query.get_or_404(id)
    
    if current_user.is_authenticated:
        # Save to read history
        existing = ReadHistory.query.filter_by(user_id=current_user.id, article_id=id).first()
        if not existing:
            new_read = ReadHistory(user_id=current_user.id, article_id=id)
            db.session.add(new_read)
            db.session.commit()
            
    related = Article.query.filter(Article.category == article.category, Article.id != article.id).order_by(Article.published_at.desc()).limit(3).all()
    
    saved = False
    if current_user.is_authenticated:
        saved = SavedArticle.query.filter_by(user_id=current_user.id, article_id=article.id).first() is not None
        
    return render_template('article.html', article=article, related=related, saved=saved)

@app.route('/search', methods=['GET'])
@login_required
def search():
    q = request.args.get('q', '').strip()
    grouped_articles = {}
    
    if q:
        # Save search query
        new_search = SearchHistory(user_id=current_user.id, search_query=q)
        db.session.add(new_search)
        db.session.commit()
        
        fetched_articles = []
        
        # 1. Fetch live from NewsAPI to ensure we have broad, multi-source coverage for the exact query
        try:
            res = requests.get(f'{NEWS_API_BASE}/everything', params={
                'apiKey': NEWS_API_KEY, 'q': q, 'language': 'en', 'sortBy': 'relevancy', 'pageSize': 100
            }, timeout=15)
            if res.status_code == 200:
                data = res.json()
                for item in data.get('articles', []):
                    art = process_and_save_article(item, 'general')
                    if art:
                        fetched_articles.append(art)
                db.session.commit()
        except Exception as e:
            print(f"Search fetch error: {e}")
            
        # 2. If API failed or returned 0, fallback to a more flexible local DB search
        if not fetched_articles:
            from sqlalchemy import and_, or_
            keywords = q.split()
            conditions = []
            for kw in keywords:
                kw_like = f"%{kw}%"
                conditions.append(
                    or_(
                        Article.title.ilike(kw_like),
                        Article.description.ilike(kw_like),
                        Article.summary.ilike(kw_like),
                        Article.source_name.ilike(kw_like)
                    )
                )
            if conditions:
                fetched_articles = Article.query.filter(and_(*conditions)).order_by(Article.published_at.desc()).limit(100).all()
        
        # 3. Group by source (limit to ~4 per source to keep UI clean)
        for art in fetched_articles:
            source_name = art.source_name or 'Unknown'
            if source_name not in grouped_articles:
                grouped_articles[source_name] = []
            if len(grouped_articles[source_name]) < 4:
                grouped_articles[source_name].append(art)
                
    return render_template('search_results.html', grouped_articles=grouped_articles, q=q)

@app.route('/dashboard')
@login_required
def dashboard():
    # User stats
    reads = ReadHistory.query.filter_by(user_id=current_user.id).all()
    read_ids = [r.article_id for r in reads]
    
    saved = SavedArticle.query.filter_by(user_id=current_user.id).all()
    
    read_articles = Article.query.filter(Article.id.in_(read_ids)).all() if read_ids else []
    
    avg_bias = sum(a.bias_score for a in read_articles) / len(read_articles) if read_articles else 0
    total_ai_summaries = len(read_articles) # assuming user viewed summary if read
    
    neutral_count = len([a for a in read_articles if a.bias_label == 'Neutral'])
    slight_count = len([a for a in read_articles if a.bias_label == 'Slight Bias'])
    strong_count = len([a for a in read_articles if a.bias_label == 'Strong Bias'])
    
    total = len(read_articles) or 1
    bias_breakdown = {
        'neutral': (neutral_count / total) * 100,
        'slight': (slight_count / total) * 100,
        'strong': (strong_count / total) * 100
    }
    
    # Using python to tally categories
    cat_counts = {}
    for a in read_articles:
        cat_counts[a.category] = cat_counts.get(a.category, 0) + 1
    top_categories = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_categories_pct = [{'name': c[0], 'pct': (c[1]/total)*100} for c in top_categories]
    
    # Sentiment breakdown
    pos_count = len([a for a in read_articles if a.sentiment_label == 'Positive'])
    neg_count = len([a for a in read_articles if a.sentiment_label == 'Negative'])
    neu_count = len([a for a in read_articles if a.sentiment_label == 'Neutral'])
    
    sentiment_breakdown = {
        'positive': (pos_count / total) * 100,
        'negative': (neg_count / total) * 100,
        'neutral': (neu_count / total) * 100
    }
    
    recent_read = Article.query.join(ReadHistory).filter(ReadHistory.user_id == current_user.id).order_by(ReadHistory.read_at.desc()).limit(5).all()
    recent_saved = Article.query.join(SavedArticle).filter(SavedArticle.user_id == current_user.id).order_by(SavedArticle.saved_at.desc()).limit(4).all()
    
    return render_template('dashboard.html', 
        reads_count=len(reads),
        saved_count=len(saved),
        avg_bias=avg_bias,
        total_ai_summaries=total_ai_summaries,
        bias_breakdown=bias_breakdown,
        sentiment_breakdown=sentiment_breakdown,
        top_categories=top_categories_pct,
        recent_read=recent_read,
        recent_saved=recent_saved
    )

@app.route('/saved')
@login_required
def saved():
    articles = Article.query.join(SavedArticle).filter(SavedArticle.user_id == current_user.id).order_by(SavedArticle.saved_at.desc()).all()
    return render_template('saved.html', articles=articles)

@app.route('/history')
@login_required
def history():
    articles = Article.query.join(ReadHistory).filter(ReadHistory.user_id == current_user.id).order_by(ReadHistory.read_at.desc()).all()
    return render_template('history.html', articles=articles)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not username or len(username) < 3:
            flash('Username must be at least 3 characters.', 'error')
            return redirect(url_for('register'))
            
        if not is_valid_email(email):
            flash('Invalid email.', 'error')
            return redirect(url_for('register'))
            
        if len(password) < 8 or password != confirm_password:
            flash('Passwords must be at least 8 characters and match.', 'error')
            return redirect(url_for('register'))
            
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash('Username or email taking.', 'error')
            return redirect(url_for('register'))
            
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('home'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            # Redirect to originally requested page
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
            
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
    else:
        new_save = SavedArticle(user_id=current_user.id, article_id=article_id)
        db.session.add(new_save)
        db.session.commit()
        return jsonify({'saved': True})

@app.route('/api/search-history')
@login_required
def get_search_history():
    history = SearchHistory.query.filter_by(user_id=current_user.id).order_by(SearchHistory.searched_at.desc()).limit(10).all()
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

@app.route('/fetch-news')
def fetch_news():
    # Delete older than 3 days
    three_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=3)
    Article.query.filter(Article.fetched_at < three_days_ago).delete()
    db.session.commit()
    
    total = 0
    categories = ['tech', 'ai', 'science', 'culture', 'general', 'health', 'politics']
    for cat in categories:
        total += fetch_category_news(cat)
        
    return jsonify({'count': total})

def auto_fetch_if_empty():
    with app.app_context():
        if Article.query.count() == 0:
            print("Database empty. Initializing automatic news fetch...")
            # Trigger initial fetch manually inside app context
            categories = ['tech', 'ai', 'science', 'culture', 'general', 'health', 'politics']
            for cat in categories:
                fetch_category_news(cat)

with app.app_context():
    db.create_all()
    from nlp_utils import set_gemini_key
    set_gemini_key(GEMINI_API_KEY)
    init_nlp_models()
    auto_fetch_if_empty()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)