from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import re
import datetime
import requests
from functools import wraps

app = Flask(__name__)
app.secret_key = 'super_secret_key_123_change_me_in_production'

# --- CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# NewsAPI.org Configuration (Better Quality)
NEWS_API_KEY = 'your api key'
NEWS_API_BASE = 'https://newsapi.org/v2'

db = SQLAlchemy(app)

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    topic = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_title = db.Column(db.String(500), nullable=False)
    article_url = db.Column(db.String(1000), nullable=False)
    article_image = db.Column(db.String(1000))
    article_source = db.Column(db.String(200))
    article_summary = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# --- DECORATORS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- HELPER FUNCTIONS ---
def is_valid_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(pattern, email) is not None

def is_valid_password(password):
    """Validate password strength"""
    return len(password) >= 6 and any(char.isdigit() for char in password)

def get_news(query='latest', page_size=20):
    """
    Fetches news from NewsAPI.org
    
    Args:
        query: Search term or 'latest' for top headlines
        page_size: Number of articles to fetch (max 100)
    
    Returns:
        List of article dictionaries
    """
    try:
        # NewsAPI.org has different endpoints
        if query == 'latest':
            # Top headlines endpoint
            url = f'{NEWS_API_BASE}/top-headlines'
            params = {
                'apiKey': NEWS_API_KEY,  # Note: apiKey not apikey
                'country': 'us',
                'pageSize': min(page_size, 100)
            }
        else:
            # Everything/search endpoint
            url = f'{NEWS_API_BASE}/everything'
            params = {
                'apiKey': NEWS_API_KEY,
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': min(page_size, 100)
            }
        
        print(f"📡 Fetching from NewsAPI.org: {query}")
        response = requests.get(url, params=params, timeout=10)
        
        # Print response for debugging
        print(f"📊 API Response Status: {response.status_code}")
        
        response.raise_for_status()
        data = response.json()
        
        # Check API response status
        if data.get('status') != 'ok':
            error_msg = data.get('message', 'Unknown error')
            print(f"❌ API Error: {error_msg}")
            return []
        
        # Parse articles from NewsAPI.org format
        articles = []
        for item in data.get('articles', []):
            # Only require title and URL
            if not item.get('title') or not item.get('url'):
                continue
            
            # Skip articles with [Removed] content
            if '[Removed]' in item.get('title', ''):
                continue
            
            # Validate and clean image URL
            image_url = item.get('urlToImage')
            if not image_url or image_url == 'null' or len(image_url) < 10:
                # Use a minimal gradient placeholder
                image_url = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="400" height="250"%3E%3Crect width="400" height="250" fill="%231a1a1a"/%3E%3Cg opacity="0.1"%3E%3Crect x="150" y="90" width="100" height="70" rx="8" fill="white"/%3E%3Ccircle cx="200" cy="110" r="12" fill="white"/%3E%3Cpath d="M170 140 L180 130 L190 138 L210 115 L230 140 Z" fill="white"/%3E%3C/g%3E%3C/svg%3E'
            
            articles.append({
                'title': item['title'],
                'summary': item.get('description') or 'No description available',
                'url': item['url'],
                'image': image_url,
                'source': item.get('source', {}).get('name', 'Unknown'),
                'published_at': format_date(item.get('publishedAt', '')),
                'category': 'general'
            })
        
        print(f"✅ Found {len(articles)} articles")
        return articles
        
    except requests.Timeout:
        print("⏱️ Request timeout")
        return []
    except requests.RequestException as e:
        print(f"🌐 Network error: {e}")
        return []
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        return []

def format_date(date_string):
    """Convert ISO date to readable format"""
    try:
        if not date_string:
            return 'N/A'
        # NewsAPI.org format: 2024-01-15T12:30:00Z
        dt = datetime.datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return dt.strftime('%b %d, %Y')
    except:
        return date_string[:10] if len(date_string) >= 10 else 'N/A'

# --- ROUTES ---
@app.route('/')
def home():
    """Redirect to dashboard or login"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        # Validation
        if not all([username, email, password]):
            flash('All fields are required!', 'error')
            return redirect(url_for('register'))
        
        if not is_valid_email(email):
            flash('Invalid email format!', 'error')
            return redirect(url_for('register'))
        
        if not is_valid_password(password):
            flash('Password must be at least 6 characters with one number!', 'error')
            return redirect(url_for('register'))
        
        # Check if user exists
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or Email already taken!', 'error')
            return redirect(url_for('register'))
        
        # Create user
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Registration failed. Please try again.', 'error')
            print(f"Registration error: {e}")
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Please enter both username and password!', 'error')
            return redirect(url_for('login'))
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not check_password_hash(user.password, password):
            flash('Invalid username or password!', 'error')
            return redirect(url_for('login'))
        
        # Set session
        session['user_id'] = user.id
        session['username'] = user.username
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Main news dashboard"""
    # Fetch user's search history
    history_objs = SearchHistory.query.filter_by(
        user_id=session['user_id']
    ).order_by(SearchHistory.timestamp.desc()).limit(10).all()
    
    history = [{
        'id': h.id,
        'topic': h.topic,
        'timestamp': h.timestamp.isoformat()
    } for h in history_objs]
    
    # Determine what to show
    query_param = request.args.get('q', '').strip()
    current_topic = query_param if query_param else 'latest'
    
    # Fetch news articles
    articles = get_news(current_topic, page_size=20)
    
    # Get user's bookmarks for checking
    bookmarked_urls = {
        b.article_url for b in Bookmark.query.filter_by(user_id=session['user_id']).all()
    }
    
    return render_template(
        'dashboard.html',
        history=history,
        articles=articles,
        current_topic=current_topic,
        bookmarked_urls=bookmarked_urls
    )

@app.route('/search', methods=['POST'])
@login_required
def search():
    """Handle search requests"""
    topic = request.form.get('topic', '').strip()
    
    if topic:
        # Remove old entry if exists (avoid duplicates)
        existing = SearchHistory.query.filter_by(
            user_id=session['user_id'],
            topic=topic
        ).first()
        
        if existing:
            db.session.delete(existing)
        
        # Add new search entry
        new_search = SearchHistory(user_id=session['user_id'], topic=topic)
        
        try:
            db.session.add(new_search)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Search history error: {e}")
        
        return redirect(url_for('dashboard', q=topic))
    
    return redirect(url_for('dashboard'))

@app.route('/bookmarks')
@login_required
def bookmarks():
    """View all bookmarked articles"""
    user_bookmarks = Bookmark.query.filter_by(
        user_id=session['user_id']
    ).order_by(Bookmark.created_at.desc()).all()
    
    bookmarked_urls = {b.article_url for b in user_bookmarks}
    
    articles = [{
        'title': b.article_title,
        'url': b.article_url,
        'image': b.article_image,
        'source': b.article_source,
        'summary': b.article_summary,
        'published_at': b.created_at.strftime('%b %d, %Y')
    } for b in user_bookmarks]
    
    return render_template(
        'bookmarks.html',
        articles=articles,
        bookmarked_urls=bookmarked_urls
    )

@app.route('/add_bookmark', methods=['POST'])
@login_required
def add_bookmark():
    """Add article to bookmarks"""
    data = request.get_json()
    
    print(f"📌 Bookmark request received: {data}")
    
    if not data or not data.get('url'):
        print("❌ Invalid data - missing URL")
        return jsonify({'error': 'Invalid data'}), 400
    
    # Check if already bookmarked
    existing = Bookmark.query.filter_by(
        user_id=session['user_id'],
        article_url=data['url']
    ).first()
    
    if existing:
        print("⚠️ Already bookmarked")
        return jsonify({'error': 'Already bookmarked'}), 409
    
    # Create bookmark
    bookmark = Bookmark(
        user_id=session['user_id'],
        article_title=data.get('title', 'Untitled'),
        article_url=data['url'],
        article_image=data.get('image'),
        article_source=data.get('source'),
        article_summary=data.get('summary')
    )
    
    try:
        db.session.add(bookmark)
        db.session.commit()
        print(f"✅ Bookmark saved: {data.get('title')}")
        return jsonify({'success': True, 'message': 'Bookmarked!'})
    except Exception as e:
        db.session.rollback()
        print(f"💥 Bookmark error: {e}")
        return jsonify({'error': 'Failed to bookmark'}), 500

@app.route('/remove_bookmark', methods=['POST'])
@login_required
def remove_bookmark():
    """Remove article from bookmarks"""
    data = request.get_json()
    
    if not data or not data.get('url'):
        return jsonify({'error': 'Invalid data'}), 400
    
    bookmark = Bookmark.query.filter_by(
        user_id=session['user_id'],
        article_url=data['url']
    ).first()
    
    if not bookmark:
        return jsonify({'error': 'Bookmark not found'}), 404
    
    try:
        db.session.delete(bookmark)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Removed from bookmarks'})
    except Exception as e:
        db.session.rollback()
        print(f"Remove bookmark error: {e}")
        return jsonify({'error': 'Failed to remove'}), 500

@app.route('/delete_history', methods=['POST'])
@login_required
def delete_history():
    """Delete search history entry"""
    data = request.get_json()
    entry = SearchHistory.query.get(data.get('id'))
    
    if not entry or entry.user_id != session['user_id']:
        return jsonify({'error': 'Not found'}), 404
    
    try:
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to delete'}), 500

@app.route('/logout')
def logout():
    """User logout"""
    username = session.get('username', 'User')
    session.clear()
    flash(f'Goodbye, {username}!', 'info')
    return redirect(url_for('login'))

# --- INITIALIZE DATABASE ---
with app.app_context():
    db.create_all()
    print("✅ Database initialized")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)