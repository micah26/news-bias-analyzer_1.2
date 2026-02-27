-- Create Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Unique ID for each user
    username TEXT NOT NULL UNIQUE,         -- Username, must be unique
    email TEXT NOT NULL UNIQUE,            -- Email, must be unique
    password TEXT NOT NULL                 -- Hashed password (secure)
);

-- Create Search History table
CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Unique ID for each search
    user_id INTEGER NOT NULL,              -- Links to the user who searched
    topic TEXT NOT NULL,                   -- The search topic (e.g., "climate change")
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,  -- When the search happened
    FOREIGN KEY (user_id) REFERENCES users(id)  -- Connects to users table
);

-- Create Bookmarks table (for later)
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Unique ID
    user_id INTEGER NOT NULL,              -- Links to user
    article_title TEXT NOT NULL,           -- Title of saved article
    article_url TEXT NOT NULL,             -- URL of saved article
    FOREIGN KEY (user_id) REFERENCES users(id)
);