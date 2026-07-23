"""
TIA-Solutions Ticketing System
Database initialisation and helper utilities (PostgreSQL / Neon).
"""

import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    """Return a live connection with dict-like rows (RealDictRow)."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add your Neon connection string as the "
            "DATABASE_URL environment variable."
        )
    conn = psycopg2.connect(DATABASE_URL, sslmode="require",
                             cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        SERIAL PRIMARY KEY,
            name      TEXT    NOT NULL,
            email     TEXT    NOT NULL UNIQUE,
            password  TEXT    NOT NULL,
            role      TEXT    NOT NULL DEFAULT 'client',
            company   TEXT,
            phone     TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Tickets
    c.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id                SERIAL  PRIMARY KEY,
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
            created_at        TIMESTAMP DEFAULT NOW(),
            updated_at        TIMESTAMP DEFAULT NOW()
        )
    """)

    # Safe column migrations (idempotent on Postgres 9.6+)
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
        c.execute(f"ALTER TABLE tickets ADD COLUMN IF NOT EXISTS {col} {col_def}")

    # Comments
    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id         SERIAL  PRIMARY KEY,
            ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            body       TEXT    NOT NULL,
            is_internal INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Notifications
    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         SERIAL  PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            message    TEXT    NOT NULL,
            link       TEXT,
            is_read    INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()

    # Seed default admin + demo agent
    from werkzeug.security import generate_password_hash
    c.execute("SELECT id FROM users WHERE email = %s", ("admin@tia-solutions.co.za",))
    existing = c.fetchone()
    if not existing:
        c.execute(
            "INSERT INTO users (name, email, password, role, company) VALUES (%s,%s,%s,%s,%s)",
            ("TIA Admin", "admin@tia-solutions.co.za",
             generate_password_hash("Admin@1234"), "admin", "TIA Solutions")
        )
        c.execute(
            "INSERT INTO users (name, email, password, role, company) VALUES (%s,%s,%s,%s,%s)",
            ("Support Agent", "agent@tia-solutions.co.za",
             generate_password_hash("Agent@1234"), "agent", "TIA Solutions")
        )
        conn.commit()

    c.close()
    conn.close()


def next_ticket_no():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT nextval('ticket_no_seq') as num")
    num = c.fetchone()["num"]
    c.close()
    conn.close()
    return f"TIA-{num:05d}"
