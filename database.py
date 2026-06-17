import os
import secrets
import string
from typing import Optional, List

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
                token TEXT UNIQUE,
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
                banned_at TEXT DEFAULT (datetime('now')),
                last_message TEXT,
                UNIQUE(owner_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                text TEXT,
                media_type TEXT,
                media_file_id TEXT,
                owner_message_id INTEGER,
                status TEXT DEFAULT 'open',
                is_resolved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_support_user_category ON support_tickets(user_id, category, is_resolved)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS category_cooldowns (
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                cooldown_until TEXT NOT NULL,
                PRIMARY KEY (user_id, category)
            )
        """)
        await db.commit()


def generate_token() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(8))


async def migrate_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN token TEXT")
            await db.commit()
        except Exception:
            pass

        async with db.execute("SELECT user_id FROM users WHERE token IS NULL") as cursor:
            rows = await cursor.fetchall()
        for (uid,) in rows:
            await db.execute("UPDATE users SET token = ? WHERE user_id = ?",
                             (generate_token(), uid))
        await db.commit()

        for column, definition in [
            ("banned_at", "TEXT DEFAULT (datetime('now'))"),
            ("last_message", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE bans ADD COLUMN {column} {definition}")
                await db.commit()
            except Exception:
                pass

        try:
            await db.execute("ALTER TABLE support_tickets ADD COLUMN owner_message_id INTEGER")
            await db.commit()
        except Exception:
            pass

        try:
            await db.execute("ALTER TABLE support_tickets ADD COLUMN status TEXT DEFAULT 'open'")
            await db.commit()
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS category_cooldowns (
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                cooldown_until TEXT NOT NULL,
                PRIMARY KEY (user_id, category)
            )
        """)
        await db.commit()


async def add_user(user_id: int, username: Optional[str], full_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        token = generate_token()
        await db.execute(
            """INSERT INTO users (user_id, username, full_name, token)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username = excluded.username,
                 full_name = excluded.full_name""",
            (user_id, username, full_name, token),
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


async def get_user_by_token(token: str) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE token = ?", (token,)
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


async def get_unread_messages(recipient_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM messages
               WHERE recipient_id = ? AND is_answered = 0
               ORDER BY created_at DESC""",
            (recipient_id,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_unread_count(recipient_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE recipient_id = ? AND is_answered = 0",
            (recipient_id,),
        ) as cursor:
            return (await cursor.fetchone())[0]


async def mark_all_read(recipient_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE messages SET is_answered = 1 WHERE recipient_id = ? AND is_answered = 0",
            (recipient_id,),
        )
        await db.commit()
        return cursor.rowcount


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

        return {
            "sent": sent,
            "received": received,
            "ban_count": ban_count,
        }


async def get_global_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
            total_messages = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM bans") as cursor:
            total_bans = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM support_tickets WHERE is_resolved = 0") as cursor:
            open_tickets = (await cursor.fetchone())[0]

        return {
            "total_users": total_users,
            "total_messages": total_messages,
            "total_bans": total_bans,
            "open_tickets": open_tickets,
        }


async def add_ban(owner_id: int, user_id: int, last_message: str = None) -> None:
    truncated = (last_message[:20] + "...") if last_message and len(last_message) > 20 else last_message
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO bans (owner_id, user_id, last_message) VALUES (?, ?, ?)",
            (owner_id, user_id, truncated),
        )
        await db.execute(
            "INSERT OR IGNORE INTO bans (owner_id, user_id, last_message) VALUES (?, ?, ?)",
            (user_id, owner_id, truncated),
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


async def get_ban_list(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT DISTINCT
                CASE WHEN owner_id = ? THEN user_id ELSE owner_id END as banned_id,
                last_message
            FROM bans
            WHERE owner_id = ? OR user_id = ?
        """, (user_id, user_id, user_id)) as cursor:
            rows = await cursor.fetchall()

    result = []
    for row in rows:
        user = await get_user(row["banned_id"])
        if user and user["token"]:
            result.append({
                "token": user["token"],
                "last_message": row["last_message"],
            })
    return result


async def add_support_ticket(
    user_id: int,
    category: str,
    text: str,
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
    owner_message_id: Optional[int] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """INSERT INTO support_tickets (user_id, category, text, media_type, media_file_id, owner_message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, category, text, media_type, media_file_id, owner_message_id),
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


async def update_ticket_owner_message_id(ticket_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET owner_message_id = ? WHERE id = ?",
            (message_id, ticket_id),
        )
        await db.commit()


async def update_ticket_status(ticket_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE support_tickets SET status = ? WHERE id = ?",
            (status, ticket_id),
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


async def set_category_cooldown(user_id: int, category: str, hours: int = 24) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO category_cooldowns (user_id, category, cooldown_until)
               VALUES (?, ?, datetime('now', ?))
               ON CONFLICT(user_id, category) DO UPDATE SET
                 cooldown_until = excluded.cooldown_until""",
            (user_id, category, f"+{hours} hours"),
        )
        await db.commit()


async def is_category_cooldown_active(user_id: int, category: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM category_cooldowns WHERE user_id = ? AND category = ? AND cooldown_until > datetime('now')",
            (user_id, category),
        ) as cursor:
            return await cursor.fetchone() is not None


async def get_unanswered_for_reminder(hours: int = 6) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT recipient_id, COUNT(*) as cnt,
                      GROUP_CONCAT(sender_full_name, ', ') as senders
               FROM messages
               WHERE is_answered = 0
                 AND created_at < datetime('now', ?)
               GROUP BY recipient_id""",
            (f"-{hours} hours",),
        ) as cursor:
            return await cursor.fetchall()


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
