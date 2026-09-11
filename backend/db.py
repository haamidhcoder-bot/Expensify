"""
db.py
Handles all SQLite database setup and connection management for the
Expense Tracker backend. Uses plain sqlite3 (no ORM) for transparency
and zero extra dependencies.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")

DEFAULT_CATEGORIES = [
    # name,              icon,  color,      monthly_budget
    ("Food & Dining",    "🍔", "#FF6B6B", 0),
    ("Groceries",        "🛒", "#4ECDC4", 0),
    ("Transportation",   "🚗", "#45B7D1", 0),
    ("Shopping",         "🛍️", "#F7B267", 0),
    ("Entertainment",    "🎬", "#9B5DE5", 0),
    ("Bills & Utilities","💡", "#F15BB5", 0),
    ("Healthcare",       "🏥", "#00BBF9", 0),
    ("Education",        "📚", "#00F5D4", 0),
    ("Travel",           "✈️", "#FEE440", 0),
    ("Other",            "📦", "#9CA3AF", 0),
]


def get_connection():
    """Create a new SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """Context manager that yields a connection and always closes it."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they do not exist yet, and seed default categories."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT UNIQUE NOT NULL,
                icon           TEXT DEFAULT '📦',
                color          TEXT DEFAULT '#9CA3AF',
                monthly_budget REAL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                amount          REAL NOT NULL,
                category_id     INTEGER NOT NULL,
                description     TEXT DEFAULT '',
                date            TEXT NOT NULL,
                payment_method  TEXT DEFAULT 'Cash',
                notes           TEXT DEFAULT '',
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories (id)
                    ON DELETE RESTRICT
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category_id)
        """)

        existing = conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
        if existing == 0:
            conn.executemany(
                "INSERT INTO categories (name, icon, color, monthly_budget) VALUES (?, ?, ?, ?)",
                DEFAULT_CATEGORIES,
            )
