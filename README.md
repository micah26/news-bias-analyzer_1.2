# NewsLens - Modern News Aggregator 🚀

A sleek, modern news aggregation platform with AI-powered insights, bias detection capabilities, and a stunning Verge-inspired design.

## ✨ Features

### Core Functionality
- **Real-time News**: Fetches up to 20 articles from NewsAPI.org
- **Smart Search**: Search across thousands of news sources globally
- **Search History**: YouTube-style search history with quick access
- **Bookmarks**: Save articles for later reading
- **User Authentication**: Secure login and registration system

### Design & UX
- **Modern Dark Theme**: Inspired by The Verge's editorial design
- **Smooth Animations**: Staggered card animations, hover effects, transitions
- **Responsive Design**: Works perfectly on mobile, tablet, and desktop
- **Premium Typography**: Playfair Display + Inter font pairing
- **Micro-interactions**: Bookmark animations, toast notifications, hover states

### Technical Features
- **Optimized Code**: Better error handling, logging, and structure
- **Database Models**: Users, SearchHistory, Bookmarks
- **API Integration**: NewsData.io with proper error handling
- **Session Management**: Secure Flask sessions
- **Form Validation**: Email and password validation

## 🛠️ Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: Bootstrap 5 + Custom CSS
- **API**: NewsAPI.org
- **Fonts**: Google Fonts (Playfair Display, Inter)
- **Icons**: Bootstrap Icons

## 📦 Installation

### Prerequisites
```bash
Python 3.8+
pip
```

### Setup Steps

1. **Extract the project files** to your desired location

2. **Install dependencies**:
```bash
pip install flask flask-sqlalchemy requests --break-system-packages
```

3. **Run the application**:
```bash
python app.py
```

4. **Open your browser**:
```
http://localhost:5000
```

## 📁 File Structure

```
NewsLens/
├── app.py                 # Main Flask application
├── database.db           # SQLite database (auto-created)
├── static/
│   └── style.css         # Modern custom styles
└── templates/
    ├── base.html         # Base template with navigation
    ├── login.html        # Login page
    ├── register.html     # Registration page
    ├── dashboard.html    # Main news dashboard
    └── bookmarks.html    # Bookmarked articles page
```

## 🎨 Design Philosophy

### Color System
- **Primary Background**: Deep black (#0a0a0a)
- **Accent Color**: Bold red (#ff4444)
- **Secondary Accent**: Lime green (#00ff88)
- **Tertiary Accent**: Purple (#8855ff)

### Typography
- **Headlines**: Playfair Display (Editorial serif)
- **Body Text**: Inter (Clean sans-serif)
- **Accent**: Uppercase labels with letter-spacing

### Animations
- Staggered card entrance animations
- Smooth hover transitions (250ms cubic-bezier)
- Micro-interactions on buttons and bookmarks
- Toast notifications with slide animations

## 🔧 Configuration

### API Key (Already Configured)
The NewsAPI.org API key is already set in `app.py`:
```python
NEWS_API_KEY = '9c105487e69e46c89f18ee9ec0e2dad1'
```

### Database
SQLite database is automatically created on first run with three tables:
- `user` - User accounts
- `search_history` - User search history
- `bookmark` - Saved articles

### Customization
You can customize the design in `static/style.css`:
- Change color variables in `:root`
- Modify fonts in `@import` statement
- Adjust animations and transitions

## 📱 Features Guide

### Search
1. Type any topic in the search bar
2. Press Enter or click search icon
3. View results with images, titles, and summaries

### Bookmarks
1. Click the bookmark icon on any article
2. Access saved articles from "Bookmarks" in navigation
3. Remove bookmarks by clicking the filled bookmark icon

### Search History
1. Click in the search bar
2. See your recent searches appear
3. Click any search to re-run it
4. Delete searches with the × button

## 🚀 What's New (Improvements from Previous Version)

### API Changes
- ✅ Switched from NewsAPI.org to NewsData.io
- ✅ Increased article limit from 12 to 24
- ✅ Better error handling with proper logging

### Features Added
- ✅ **Bookmark System**: Fully functional save/remove bookmarks
- ✅ **Bookmarks Page**: Dedicated page to view saved articles
- ✅ **Toast Notifications**: Real-time feedback for user actions
- ✅ **Login Required Decorator**: Better authentication flow

### Code Improvements
- ✅ **Error Handling**: Try-catch blocks with proper logging
- ✅ **Code Structure**: Separated concerns, better organization
- ✅ **Database Optimization**: Efficient queries, proper relationships
- ✅ **Form Validation**: Enhanced validation with better feedback

### Design Overhaul
- ✅ **Verge-Inspired Theme**: Modern editorial design
- ✅ **Dark Mode**: Premium dark theme throughout
- ✅ **Animations**: Staggered card animations, smooth transitions
- ✅ **Typography**: Bold Playfair Display + clean Inter
- ✅ **Responsive**: Mobile-first, works on all screen sizes
- ✅ **Modern Auth Pages**: Stunning login/register designs

## 🎯 Future Enhancements

- AI-powered bias detection (planned)
- Article summarization with AI
- Reading analytics dashboard
- Social sharing features
- Dark/Light theme toggle
- Email notifications for saved searches
- Advanced filters (date, source, category)

## 📝 Notes

- **Free Tier Limit**: NewsData.io free tier has daily limits
- **Images**: Placeholder shown if article has no image
- **Security**: Change `secret_key` in production
- **Performance**: Optimized for fast loading with lazy images

## 🐛 Troubleshooting

**Articles not loading?**
- Check your internet connection
- Verify API key is valid
- Check console for error messages

**Database errors?**
- Delete `database.db` and restart the app
- It will be recreated automatically

**Styling issues?**
- Clear browser cache
- Ensure `static/style.css` is in the correct location

## 👨‍💻 Developer

Created by Mi as a college project with modern web development best practices.

## 📄 License

This project is for educational purposes.

---

**Enjoy your modern news experience! 📰✨**