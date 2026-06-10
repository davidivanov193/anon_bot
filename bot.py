import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, Message, CallbackQuery

from config import BOT_TOKEN, OWNER_ID
from database import init_db, migrate_db, get_unanswered_for_reminder
from handlers import router


class BotMiddleware:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def __call__(self, handler, event: Message | CallbackQuery, data: dict):
        data["bot"] = self.bot
        data["owner_id"] = OWNER_ID
        return await handler(event, data)


async def reminder_loop(bot: Bot):
    while True:
        try:
            rows = await get_unanswered_for_reminder(hours=6)
            for row in rows:
                recipient_id = row["recipient_id"]
                cnt = row["cnt"]
                senders = row["senders"]
                await bot.send_message(
                    chat_id=recipient_id,
                    text=f"⚠️ У вас {cnt} неотвеченных сообщений (6+ часов)\n\n"
                         f"Отправители: {senders}\n\n"
                         f"Ответьте на них, чтобы помочь собеседникам!",
                )
        except Exception as e:
            logging.error(f"Ошибка в reminder_loop: {e}")

        await asyncio.sleep(6 * 60 * 60)


async def main():
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден. Проверьте файл .env")
    if not OWNER_ID:
        raise ValueError("OWNER_ID не найден. Проверьте файл .env")

    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    middleware = BotMiddleware(bot)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)

    dp.include_router(router)

    await init_db()
    await migrate_db()

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="cancel", description="Отмена"),
        BotCommand(command="banlist", description="Список забаненных"),
        BotCommand(command="unban", description="Разбанить"),
    ])

    logging.info("Бот запущен!")
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
