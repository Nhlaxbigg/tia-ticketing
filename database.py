"""
TIA-Solutions Ticketing System
Database initialisation and helper utilities.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "tia_tickets.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT    NOT NULL,
            email     TEXT    NOT NULL UNIQUE,
            password  TEXT    NOT NULL,
            role      TEXT    NOT NULL DEFAULT 'client',
            company   TEXT,
            phone     TEXT,
            created_at TEXT   DEFAULT (datetime('now'))
        )
    """)

    # Tickets
    c.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_no         TEXT    NOT NULL UNIQUE,
            title             TEXT    NOT NULL,
            description       TEXT    NOT NULL,
            category          TEXT    NOT NULL,
            priority          TEXT    NOT NULL DEFAULT 'medium',
            request_level     TEXT    NOT NULL DEFAULT 'Level 1',
            status            TEXT    NOT NULL DEFAULT 'open',
            support_type      TEXT    DEFAULT 'remote',
            work_implemented  TEXT,
            start_time        TEXT,
            end_time          TEXT,
            hours_worked      TEXT,
            invoice_no        TEXT,
            created_by        INTEGER NOT NULL REFERENCES users(id),
            assigned_to       INTEGER REFERENCES users(id),
            created_at        TEXT    DEFAULT (datetime('now')),
            updated_at        TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Migrate existing tables — add any missing columns safely
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(tickets)").fetchall()}
    migrations = [
        ("request_level",    "TEXT NOT NULL DEFAULT 'Level 1'"),
        ("support_type",     "TEXT DEFAULT 'remote'"),
        ("work_implemented", "TEXT"),
        ("start_time",       "TEXT"),
        ("end_time",         "TEXT"),
        ("hours_worked",     "TEXT"),
        ("invoice_no",       "TEXT"),
    ]
    for col, col_def in migrations:
        if col not in existing_cols:
            c.execute(f"ALTER TABLE tickets ADD COLUMN {col} {col_def}")

    # Comments
    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            body       TEXT    NOT NULL,
            is_internal INTEGER DEFAULT 0,
            created_at TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Notifications
    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            message    TEXT    NOT NULL,
            link       TEXT,
            is_read    INTEGER DEFAULT 0,
            created_at TEXT    DEFAULT (datetime('now'))
        )
    """)

    conn.commit()

    # Seed default admin
    from werkzeug.security import generate_password_hash
    existing = c.execute("SELECT id FROM users WHERE email = 'admin@tia-solutions.co.za'").fetchone()
    if not existing:
        c.execute(
            "INSERT INTO users (name, email, password, role, company) VALUES (?,?,?,?,?)",
            ("TIA Admin", "admin@tia-solutions.co.za",
             generate_password_hash("Admin@1234"), "admin", "TIA Solutions")
        )
        # Seed a demo agent
        c.execute(
            "INSERT INTO users (name, email, password, role, company) VALUES (?,?,?,?,?)",
            ("Support Agent", "agent@tia-solutions.co.za",
             generate_password_hash("Agent@1234"), "agent", "TIA Solutions")
        )
        # Seed a demo technician
        c.execute(
            "INSERT INTO users (name, email, password, role, company) VALUES (?,?,?,?,?)",
            ("TIA Technician", "technician@tia-solutions.co.za",
             generate_password_hash("Tech@1234"), "technician", "TIA Solutions")
        )
        # Seed requested technicians if not present
        technicians = [
            ("Keitumetse Ndaba", "keitumetse@tia-solutions.co.za", "_ig4A99LX9IMzmBK"),
            ("Lebogang Setlago", "lebogang@tia-solutions.co.za", "TFWHoDEIXVjLAd7-"),
            ("Mlungisi Khoza", "mlungisi@tia-solutions.co.za", "eX8_SJZAaN018mny"),
            ("Nhlanhla Mkhwebane", "nhlanhla@tia-solutions.co.za", "Xx3EPfWgzYaftCKn"),
        ]
        for t_name, t_email, t_pw in technicians:
            if not c.execute("SELECT id FROM users WHERE email = ?", (t_email,)).fetchone():
                c.execute(
                    "INSERT INTO users (name, email, password, role, company) VALUES (?,?,?,?,?)",
                    (t_name, t_email, generate_password_hash(t_pw), "technician", "TIA Solutions")
                )
        conn.commit()

    # Ensure the requested technicians exist even if admin seed already ran
    from werkzeug.security import generate_password_hash
    conn = get_db()
    c = conn.cursor()
    technicians = [
        ("Keitumetse Ndaba", "keitumetse@tia-solutions.co.za", "_ig4A99LX9IMzmBK"),
        ("Lebogang Setlago", "lebogang@tia-solutions.co.za", "TFWHoDEIXVjLAd7-"),
        ("Mlungisi Khoza", "mlungisi@tia-solutions.co.za", "eX8_SJZAaN018mny"),
        ("Nhlanhla Mkhwebane", "nhlanhla@tia-solutions.co.za", "Xx3EPfWgzYaftCKn"),
    ]
    for t_name, t_email, t_pw in technicians:
        if not c.execute("SELECT id FROM users WHERE email = ?", (t_email,)).fetchone():
            c.execute(
                "INSERT INTO users (name, email, password, role, company) VALUES (?,?,?,?,?)",
                (t_name, t_email, generate_password_hash(t_pw), "technician", "TIA Solutions")
            )
    conn.commit()
    conn.close()


def next_ticket_no():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM tickets").fetchone()
    num = (row["cnt"] or 0) + 1
    conn.close()
    return f"TIA-{num:05d}"
