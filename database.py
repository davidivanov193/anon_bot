import os
from typing import Optional, Tuple, List

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "anon_bot.db")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                rating_avg REAL DEFAULT 4.0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                sender_username TEXT,
                sender_full_name TEXT,
                recipient_id INTEGER NOT NULL,
                text TEXT,
                media_type TEXT,
                media_file_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                is_answered INTEGER NOT NULL DEFAULT 0 CHECK(is_answered IN (0, 1))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_recipient_answered
            ON messages(recipient_id, is_answered)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(owner_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rater_id INTEGER NOT NULL,
                rated_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(rater_id, rated_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ratings_rated ON ratings(rated_id)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                text TEXT,
                media_type TEXT,
                media_file_id TEXT,
                is_resolved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_support_user_category ON support_tickets(user_id, category, is_resolved)")
        await db.commit()


async def migrate_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "rating_avg" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN rating_avg REAL DEFAULT 4.0")
        await db.commit()


async def add_user(user_id: int, username: Optional[str], full_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, username, full_name)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username = excluded.username,
                 full_name = excluded.full_name""",
            (user_id, username, full_name),
        )
        await db.commit()


async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone()


async def get_user_by_username(username: str) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ) as cursor:
            return await cursor.fetchone()


async def add_message(
    sender_id: int,
    sender_username: Optional[str],
    sender_full_name: str,
    recipient_id: int,
    text: str,
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """INSERT INTO messages
               (sender_id, sender_username, sender_full_name, recipient_id, text, media_type, media_file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sender_id, sender_username, sender_full_name, recipient_id, text, media_type, media_file_id),
        ) as cursor:
            await db.commit()
            return cursor.lastrowid


async def get_message(message_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ) as cursor:
            return await cursor.fetchone()


async def mark_answered(message_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE messages SET is_answered = 1 WHERE id = ?", (message_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_id = ?", (user_id,)
        ) as cursor:
            sent = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE recipient_id = ?", (user_id,)
        ) as cursor:
            received = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM bans WHERE owner_id = ? OR user_id = ?", (user_id, user_id)
        ) as cursor:
            ban_count = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT AVG(rating), COUNT(*) FROM ratings WHERE rated_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            rating_avg = row[0] if row[0] is not None else 4.0
            rating_count = row[1]

        return {
            "sent": sent,
            "received": received,
            "ban_count": ban_count,
            "rating_avg": round(rating_avg, 1),
            "rating_count": rating_count,
        }


async def get_global_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
            total_messages = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM bans") as cursor:
            total_bans = (await cursor.fetchone())[0]

        async with db.execute("SELECT AVG(rating_avg) FROM users WHERE rating_avg != 4.0") as cursor:
            row = await cursor.fetchone()
            avg_rating = round(row[0], 1) if row[0] is not None else 4.0

        async with db.execute("SELECT COUNT(*) FROM support_tickets WHERE is_resolved = 0") as cursor:
            open_tickets = (await cursor.fetchone())[0]

        return {
            "total_users": total_users,
            "total_messages": total_messages,
            "total_bans": total_bans,
            "avg_rating": avg_rating,
            "open_tickets": open_tickets,
        }


async def add_ban(owner_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO bans (owner_id, user_id) VALUES (?, ?)",
            (owner_id, user_id),
        )
        await db.execute(
            "INSERT OR IGNORE INTO bans (owner_id, user_id) VALUES (?, ?)",
            (user_id, owner_id),
        )
        await db.commit()


async def remove_ban(owner_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM bans WHERE (owner_id = ? AND user_id = ?) OR (owner_id = ? AND user_id = ?)",
            (owner_id, user_id, user_id, owner_id),
        )
        await db.commit()


async def is_banned(owner_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM bans WHERE (owner_id = ? AND user_id = ?) OR (owner_id = ? AND user_id = ?)",
            (owner_id, user_id, user_id, owner_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def get_ban_list(user_id: int) -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM bans WHERE owner_id = ? UNION SELECT owner_id FROM bans WHERE user_id = ?",
            (user_id, user_id),
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def add_rating(rater_id: int, rated_id: int, rating: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM ratings WHERE rater_id = ? AND rated_id = ?",
            (rater_id, rated_id),
        )
        is_new = await cursor.fetchone() is None

        await db.execute(
            "DELETE FROM ratings WHERE rater_id = ? AND rated_id = ?",
            (rater_id, rated_id),
        )
        await db.execute(
            "INSERT INTO ratings (rater_id, rated_id, rating) VALUES (?, ?, ?)",
            (rater_id, rated_id, rating),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT AVG(rating) FROM ratings WHERE rated_id = ?", (rated_id,)
        )
        row = await cursor.fetchone()
        avg = row[0] if row[0] is not None else 4.0

        await db.execute(
            "UPDATE users SET rating_avg = ? WHERE user_id = ?",
            (round(avg, 1), rated_id),
        )
        await db.commit()

        return is_new


async def get_user_rating(user_id: int) -> Tuple[float, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT AVG(rating), COUNT(*) FROM ratings WHERE rated_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            avg = round(row[0], 1) if row[0] is not None else 4.0
            count = row[1]
            return avg, count


async def adjust_rating(user_id: int, delta: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET rating_avg = MIN(5.0, MAX(0.0, rating_avg + ?)) WHERE user_id = ?",
            (delta, user_id),
        )
        await db.commit()


async def add_support_ticket(
    user_id: int,
    category: str,
    text: str,
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """INSERT INTO support_tickets (user_id, category, text, media_type, media_file_id)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, category, text, media_type, media_file_id),
        ) as cursor:
            await db.commit()
            return cursor.lastrowid


async def get_pending_ticket(user_id: int, category: str) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM support_tickets WHERE user_id = ? AND category = ? AND is_resolved = 0 ORDER BY id DESC LIMIT 1",
            (user_id, category),
        ) as cursor:
            return await cursor.fetchone()


async def resolve_ticket(ticket_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET is_resolved = 1 WHERE id = ?", (ticket_id,)
        )
        await db.commit()


async def update_ticket_text(ticket_id: int, new_text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET text = ? WHERE id = ?",
            (new_text, ticket_id),
        )
        await db.commit()


async def append_ticket_text(ticket_id: int, addition: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT text FROM support_tickets WHERE id = ?", (ticket_id,)
        ) as cursor:
            row = await cursor.fetchone()
            old_text = row[0] if row[0] else ""
        new_text = f"{old_text}\n\n---\n\n{addition}" if old_text else addition
        await db.execute(
            "UPDATE support_tickets SET text = ? WHERE id = ?",
            (new_text, ticket_id),
        )
        await db.commit()


async def get_ticket(ticket_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)
        ) as cursor:
            return await cursor.fetchone()


async def purge_old_messages(days: int = 90) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """DELETE FROM messages
               WHERE is_answered = 1
                 AND created_at < datetime('now', ?)""",
            (f"-{days} days",),
        ) as cursor:
            await db.commit()
            return cursor.rowcount
