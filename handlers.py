import logging
import time
from collections import defaultdict
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import MAX_MESSAGE_LENGTH, OWNER_ID
from keyboards import (
    main_menu_keyboard,
    sender_after_send_keyboard,
    reply_keyboard,
    copy_link_keyboard,
    persistent_keyboard,
    reply_after_reply_keyboard,
    unban_list_keyboard,
    rating_keyboard,
    confirm_send_keyboard,
    support_category_keyboard,
    support_action_keyboard,
)

router = Router()

BOT_USERNAME = None

_rate_limit: dict = defaultdict(list)
RATE_LIMIT = 5
RATE_PERIOD = 60


class SendState(StatesGroup):
    waiting_for_message = State()
    confirming_low_rating = State()


class ReplyState(StatesGroup):
    waiting_for_reply = State()


class UnbanState(StatesGroup):
    waiting_for_input = State()


class SupportState(StatesGroup):
    waiting_for_message = State()
    waiting_for_append = State()
    waiting_for_edit = State()


def _check_rate_limit(user_id: int) -> bool:
    now = time.time()
    _rate_limit[user_id] = [t for t in _rate_limit[user_id] if now - t < RATE_PERIOD]
    if len(_rate_limit[user_id]) >= RATE_LIMIT:
        return False
    _rate_limit[user_id].append(now)
    return True


def _sender_display(user) -> str:
    if user.username:
        return f"@{user.username}"
    return f"[{user.full_name}](tg://user?id={user.id})"


def _parse_username(text: str) -> Optional[str]:
    text = text.strip()
    if text.startswith("@"):
        return text[1:]
    if "t.me/" in text:
        parts = text.split("t.me/")
        if len(parts) > 1:
            return parts[1].split("/")[0].split("?")[0]
    return text


async def get_bot_username(bot: Bot):
    global BOT_USERNAME
    if BOT_USERNAME is None:
        me = await bot.get_me()
        BOT_USERNAME = me.username
    return BOT_USERNAME


def get_personal_link(user_id: int, bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start={user_id}"


async def _forward_to_recipient(bot: Bot, recipient_id: int, message: Message,
                                 msg_id: int, sender_user, owner_id: int,
                                 media_type: str = None, media_file_id: str = None):
    text = message.caption or message.text or ""

    rating_avg, _ = await db.get_user_rating(sender_user.id)

    if recipient_id == owner_id:
        main_text = f"💬 Анонимное сообщение:\n\n{text}\n\n🔍 Отправитель: {_sender_display(sender_user)}"
    else:
        main_text = f"💬 Анонимное сообщение:\n\n{text}"

    if rating_avg < 2.0:
        main_text += f"\n\n⚠️ Сообщение от пользователя с низким рейтингом ({rating_avg})"

    if media_type == "photo":
        caption = main_text if text else "💬 Анонимное сообщение (фото)"
        if rating_avg < 2.0 and not text:
            caption += f"\n\n⚠️ Сообщение от пользователя с низким рейтингом ({rating_avg})"
        await bot.send_photo(
            chat_id=recipient_id,
            photo=media_file_id,
            caption=caption,
            reply_markup=reply_keyboard(msg_id, sender_user.id, rating_avg),
        )
    elif media_type == "audio":
        caption = main_text if text else "💬 Анонимное сообщение (аудио)"
        await bot.send_audio(
            chat_id=recipient_id,
            audio=media_file_id,
            caption=caption,
            reply_markup=reply_keyboard(msg_id, sender_user.id, rating_avg),
        )
    elif media_type == "voice":
        caption = main_text if text else "💬 Анонимное сообщение (голосовое)"
        await bot.send_voice(
            chat_id=recipient_id,
            voice=media_file_id,
            caption=caption,
            reply_markup=reply_keyboard(msg_id, sender_user.id, rating_avg),
        )
    elif media_type == "sticker":
        await bot.send_sticker(
            chat_id=recipient_id,
            sticker=media_file_id,
        )
        await bot.send_message(
            chat_id=recipient_id,
            text="💬 Анонимное сообщение (стикер)",
            reply_markup=reply_keyboard(msg_id, sender_user.id, rating_avg),
        )
    elif media_type == "document":
        caption = main_text if text else "💬 Анонимное сообщение (файл)"
        await bot.send_document(
            chat_id=recipient_id,
            document=media_file_id,
            caption=caption,
            reply_markup=reply_keyboard(msg_id, sender_user.id, rating_avg),
        )
    else:
        await bot.send_message(
            chat_id=recipient_id,
            text=main_text,
            reply_markup=reply_keyboard(msg_id, sender_user.id, rating_avg),
        )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    await db.add_user(user.id, user.username, user.full_name)

    args = message.text.split()

    if len(args) > 1 and args[1].isdigit():
        recipient_id = int(args[1])

        if recipient_id <= 0:
            await message.answer(
                "❌ Некорректный ID получателя.",
                reply_markup=persistent_keyboard(),
            )
            return

        if recipient_id == user.id:
            await message.answer(
                "Вы не можете отправить сообщение самому себе.",
                reply_markup=persistent_keyboard(),
            )
            return

        if await db.is_banned(recipient_id, user.id):
            await message.answer(
                "❌ Вы заблокированы получателем.",
                reply_markup=persistent_keyboard(),
            )
            return

        recipient = await db.get_user(recipient_id)
        if not recipient:
            await message.answer(
                "Получатель ещё не запускал бота. Попробуйте позже.",
                reply_markup=persistent_keyboard(),
            )
            return

        rating_avg, _ = await db.get_user_rating(recipient_id)
        if rating_avg < 2.0:
            await state.update_data(recipient_id=recipient_id, rating_avg=rating_avg)
            await state.set_state(SendState.confirming_low_rating)
            await message.answer(
                f"⚠️ Получатель имеет низкий рейтинг ({rating_avg})\n"
                f"Ваше сообщение может быть проигнорировано.\n\n"
                f"Отправить сообщение?",
                reply_markup=confirm_send_keyboard(recipient_id),
            )
            return

        await state.update_data(recipient_id=recipient_id)
        await state.set_state(SendState.waiting_for_message)
        await message.answer(
            "Отправьте анонимное сообщение.\n"
            "Можно: текст, фото, аудио, стикер, документ\n"
            f"Максимум: {MAX_MESSAGE_LENGTH} слов"
        )
        return

    bot_username = await get_bot_username(bot)
    link = get_personal_link(user.id, bot_username)

    await message.answer(
        f"👋 Привет! Я — бот для анонимных сообщений.\n\n"
        f"Твоя ссылка для получения сообщений:\n{link}\n\n"
        f"Поделись ей, чтобы получать анонимные сообщения!",
        reply_markup=persistent_keyboard(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=persistent_keyboard())
    else:
        await message.answer("🤷 Нечего отменять.")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    stats = await db.get_stats(message.from_user.id)
    await message.answer(
        f"📊 Статистика:\n"
        f"📨 Отправлено: {stats['sent']}\n"
        f"📥 Получено: {stats['received']}\n"
        f"🚫 Забанено: {stats['ban_count']}\n"
        f"⭐ Рейтинг: {stats['rating_avg']} ({stats['rating_count']} оценок)",
    )


@router.message(Command("allstats"))
async def cmd_allstats(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Только владелец может использовать эту команду.")
        return
    stats = await db.get_global_stats()
    await message.answer(
        f"📊 Глобальная статистика:\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"📨 Всего сообщений: {stats['total_messages']}\n"
        f"🚫 Всего банов: {stats['total_bans']}\n"
        f"⭐ Средний рейтинг: {stats['avg_rating']}\n"
        f"📩 Открытых тикетов: {stats['open_tickets']}",
    )


@router.message(Command("banlist"))
async def cmd_banlist(message: Message):
    ban_list = await db.get_ban_list(message.from_user.id)
    if not ban_list:
        await message.answer("📋 Ваш список забаненных пуст.", reply_markup=persistent_keyboard())
        return

    lines = ["📋 Забаненные пользователи:"]
    for uid in ban_list:
        user = await db.get_user(uid)
        name = _sender_display(user) if user else str(uid)
        lines.append(f"• {name} — /unban {uid}")

    await message.answer("\n".join(lines), reply_markup=persistent_keyboard())


@router.message(Command("unban"))
async def cmd_unban(message: Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /unban <user_id>", reply_markup=persistent_keyboard())
        return

    user_id = int(args[1])
    await db.remove_ban(message.from_user.id, user_id)
    await message.answer(f"✅ Пользователь {user_id} разблокирован.", reply_markup=persistent_keyboard())


@router.message(SendState.confirming_low_rating)
async def handle_confirm_low_rating(message: Message, state: FSMContext):
    text = message.text.lower()
    if text in ("да", "отправить", "yes", "y"):
        data = await state.get_data()
        await state.update_data(recipient_id=data["recipient_id"])
        await state.set_state(SendState.waiting_for_message)
        await message.answer(
            "Отправьте анонимное сообщение.\n"
            "Можно: текст, фото, аудио, стикер, документ\n"
            f"Максимум: {MAX_MESSAGE_LENGTH} слов"
        )
    else:
        await state.clear()
        await message.answer("❌ Отправка отменена.", reply_markup=persistent_keyboard())


@router.callback_query(F.data.startswith("confirm_send:"))
async def callback_confirm_send(callback: CallbackQuery, state: FSMContext):
    try:
        recipient_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await state.update_data(recipient_id=recipient_id)
    await state.set_state(SendState.waiting_for_message)
    await callback.message.edit_text(
        "Отправьте анонимное сообщение.\n"
        "Можно: текст, фото, аудио, стикер, документ\n"
        f"Максимум: {MAX_MESSAGE_LENGTH} слов"
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_send")
async def callback_cancel_send(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отправка отменена.")
    await callback.answer()


@router.message(SendState.waiting_for_message, F.text)
async def handle_text_message(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    await _process_send(message, state, bot, owner_id, text=message.text)


@router.message(SendState.waiting_for_message, F.photo)
async def handle_photo_message(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    photo = message.photo[-1]
    await _process_send(message, state, bot, owner_id, text=message.caption or "",
                        media_type="photo", media_file_id=photo.file_id)


@router.message(SendState.waiting_for_message, F.audio)
async def handle_audio_message(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    await _process_send(message, state, bot, owner_id, text=message.caption or "",
                        media_type="audio", media_file_id=message.audio.file_id)


@router.message(SendState.waiting_for_message, F.voice)
async def handle_voice_message(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    await _process_send(message, state, bot, owner_id, text=message.caption or "",
                        media_type="voice", media_file_id=message.voice.file_id)


@router.message(SendState.waiting_for_message, F.sticker)
async def handle_sticker_message(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    await _process_send(message, state, bot, owner_id, text="",
                        media_type="sticker", media_file_id=message.sticker.file_id)


@router.message(SendState.waiting_for_message, F.document)
async def handle_document_message(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    await _process_send(message, state, bot, owner_id, text=message.caption or "",
                        media_type="document", media_file_id=message.document.file_id)


async def _process_send(message: Message, state: FSMContext, bot: Bot, owner_id: int,
                         text: str = "", media_type: str = None, media_file_id: str = None):
    user = message.from_user

    if not _check_rate_limit(user.id):
        await message.answer("⏳ Слишком много сообщений. Подождите 1 минуту.")
        return

    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    if not recipient_id:
        await state.clear()
        await message.answer("Произошла ошибка. Попробуйте снова.", reply_markup=persistent_keyboard())
        return

    await state.clear()

    if text and len(text.split()) > MAX_MESSAGE_LENGTH:
        await message.answer(
            f"❌ Сообщение слишком длинное. Максимум {MAX_MESSAGE_LENGTH} слов.",
            reply_markup=persistent_keyboard(),
        )
        return

    if await db.is_banned(recipient_id, user.id):
        await message.answer(
            "❌ Вы заблокированы получателем.",
            reply_markup=persistent_keyboard(),
        )
        return

    msg_id = await db.add_message(
        sender_id=user.id,
        sender_username=user.username,
        sender_full_name=user.full_name,
        recipient_id=recipient_id,
        text=text,
        media_type=media_type,
        media_file_id=media_file_id,
    )

    bot_username = await get_bot_username(bot)
    sender_link = get_personal_link(user.id, bot_username)

    await message.answer(
        "✅ Сообщение отправлено анонимно!\n\n"
        f"💡 Хотите получать анонимные сообщения?\n"
        f"Ваша ссылка: {sender_link}",
        reply_markup=sender_after_send_keyboard(recipient_id),
    )

    try:
        await _forward_to_recipient(bot, recipient_id, message, msg_id, user,
                                    owner_id, media_type, media_file_id)
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения пользователю {recipient_id}: {e}")


@router.callback_query(F.data.startswith("send_again:"))
async def callback_send_again(callback: CallbackQuery, state: FSMContext):
    try:
        recipient_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    if await db.is_banned(recipient_id, callback.from_user.id):
        await callback.answer("❌ Вы заблокированы получателем.", show_alert=True)
        return

    recipient = await db.get_user(recipient_id)
    if not recipient:
        await callback.answer("Получатель более недоступен", show_alert=True)
        return

    await state.update_data(recipient_id=recipient_id)
    await state.set_state(SendState.waiting_for_message)
    await callback.message.answer(
        "Отправьте ещё одно анонимное сообщение.\n"
        "Можно: текст, фото, аудио, стикер, документ\n"
        f"Максимум: {MAX_MESSAGE_LENGTH} слов"
    )
    await callback.answer()


@router.callback_query(F.data == "my_link")
async def callback_my_link(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    bot_username = await get_bot_username(bot)
    link = get_personal_link(user.id, bot_username)

    await callback.message.edit_text(
        f"🔗 Твоя ссылка для анонимных сообщений:\n{link}",
        reply_markup=copy_link_keyboard(link),
    )
    await callback.answer()


@router.callback_query(F.data == "get_my_link")
async def callback_get_my_link(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    bot_username = await get_bot_username(bot)
    link = get_personal_link(user.id, bot_username)

    await callback.message.edit_text(
        f"🔗 Твоя ссылка для анонимных сообщений:\n{link}",
        reply_markup=copy_link_keyboard(link),
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    stats = await db.get_stats(callback.from_user.id)
    await callback.message.edit_text(
        f"📊 Статистика:\n"
        f"📨 Отправлено: {stats['sent']}\n"
        f"📥 Получено: {stats['received']}\n"
        f"🚫 Забанено: {stats['ban_count']}\n"
        f"⭐ Рейтинг: {stats['rating_avg']} ({stats['rating_count']} оценок)",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reply:"))
async def callback_reply(callback: CallbackQuery, state: FSMContext):
    try:
        message_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    msg = await db.get_message(message_id)

    if not msg:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    if msg["is_answered"]:
        await callback.answer("На это сообщение уже отвечено", show_alert=True)
        return

    await state.update_data(reply_message_id=message_id)
    await state.set_state(ReplyState.waiting_for_reply)
    await callback.message.answer("Введите ответ:")
    await callback.answer()


@router.message(ReplyState.waiting_for_reply, F.text)
async def process_reply(message: Message, state: FSMContext, bot: Bot, owner_id: int):
    data = await state.get_data()
    message_id = data.get("reply_message_id")
    is_support = data.get("is_support_reply", False)

    if not message_id:
        await message.answer("Произошла ошибка.")
        await state.clear()
        return

    if is_support:
        ticket = await db.get_ticket(message_id)
        if not ticket:
            await message.answer("Тикет не найден.")
            await state.clear()
            return

        try:
            await bot.send_message(
                chat_id=ticket["user_id"],
                text=f"📩 Ответ поддержки:\n\n{message.text}",
            )
            await message.answer("✅ Ответ отправлен!", reply_markup=persistent_keyboard())
        except Exception as e:
            logging.error(f"Ошибка отправки ответа поддержки: {e}")
            await message.answer("Не удалось отправить ответ.")
    else:
        msg = await db.get_message(message_id)

        if not msg:
            await message.answer("Сообщение не найдено.")
            await state.clear()
            return

        sender_id = msg["sender_id"]
        await db.mark_answered(message_id)

        try:
            reply_text = f"📨 Ответ на ваше анонимное сообщение:\n\n{message.text}"

            replier = message.from_user
            if replier.id != owner_id:
                reply_text += f"\n\n🔍 Ответил: {_sender_display(replier)}"

            await bot.send_message(chat_id=sender_id, text=reply_text)

            await message.answer(
                "✅ Ответ отправлен!",
                reply_markup=reply_after_reply_keyboard(sender_id, message_id),
            )
        except Exception as e:
            logging.error(f"Ошибка отправки ответа пользователю {sender_id}: {e}")
            await message.answer("Не удалось отправить ответ. Возможно, пользователь заблокировал бота.")

    await state.clear()


@router.callback_query(F.data.startswith("rate:"))
async def callback_rate(callback: CallbackQuery):
    try:
        message_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await callback.message.answer(
        "Оцените собеседника:",
        reply_markup=rating_keyboard(message_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rate_submit:"))
async def callback_rate_submit(callback: CallbackQuery, bot: Bot, owner_id: int):
    try:
        parts = callback.data.split(":")
        message_id = int(parts[1])
        rating = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    msg = await db.get_message(message_id)
    if not msg:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    rated_id = msg["sender_id"]
    rater_id = callback.from_user.id

    if rater_id == rated_id:
        await callback.answer("Нельзя оценить самого себя", show_alert=True)
        return

    is_new = await db.add_rating(rater_id, rated_id, rating)

    await callback.message.edit_text(f"⭐ Оценка: {rating} из 5")
    await callback.answer()

    if is_new:
        try:
            await bot.send_message(
                chat_id=rated_id,
                text=f"⭐ Вас оценили на {rating}",
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("ban:"))
async def callback_ban(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    if user_id == callback.from_user.id:
        await callback.answer("Нельзя забанить самого себя", show_alert=True)
        return

    await db.add_ban(callback.from_user.id, user_id)
    await callback.answer("Пользователь заблокирован", show_alert=True)
    await callback.message.answer("🚫 Пользователь заблокирован.")


@router.callback_query(F.data == "unban_menu")
async def callback_unban_menu(callback: CallbackQuery, state: FSMContext):
    ban_list = await db.get_ban_list(callback.from_user.id)
    if not ban_list:
        await callback.message.edit_text(
            "📋 Ваш список забаненных пуст.",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "Выберите пользователя для разбана:",
        reply_markup=unban_list_keyboard(ban_list),
    )
    await state.set_state(UnbanState.waiting_for_input)
    await callback.answer()


@router.callback_query(F.data.startswith("unban_user:"))
async def callback_unban_user(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await db.remove_ban(callback.from_user.id, user_id)
    await state.clear()
    await callback.message.edit_text(
        f"✅ Пользователь {user_id} разблокирован.",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "unban_manual")
async def callback_unban_manual(callback: CallbackQuery):
    await callback.message.answer(
        "Отправьте @username или ссылку t.me/username:"
    )
    await callback.answer()


@router.message(UnbanState.waiting_for_input)
async def process_unban_input(message: Message, state: FSMContext):
    username = _parse_username(message.text)
    if not username:
        await message.answer("❌ Не удалось распознать username. Попробуйте @username или t.me/username")
        return

    user = await db.get_user_by_username(username)
    if not user:
        await message.answer(f"❌ Пользователь @{username} не найден в базе.")
        return

    await db.remove_ban(message.from_user.id, user["user_id"])
    await state.clear()
    await message.answer(
        f"✅ Пользователь {_sender_display(user)} разблокирован.",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "support_menu")
async def callback_support_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📩 Поддержка\n\nВыберите категорию:",
        reply_markup=support_category_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support:"))
async def callback_support_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":")[1]

    pending = await db.get_pending_ticket(callback.from_user.id, category)
    if pending:
        cat_names = {"bug": "🐛 Баг", "complaint": "🚫 Жалоба", "idea": "💡 Идея"}
        await callback.message.edit_text(
            f"У вас уже есть открытое обращение в категории «{cat_names.get(category, category)}».\n"
            f"Дождитесь ответа или используйте дополнить/редактировать.",
        )
        await callback.answer()
        return

    category_names = {
        "bug": "🐛 Нашли баг",
        "complaint": "🚫 Жалоба на пользователя",
        "idea": "💡 Предложение / идея",
    }

    hint = ""
    if category == "complaint":
        hint = "\n\n⚠️ Обязательно приложите минимум 1 скриншот!"

    await state.update_data(support_category=category)
    await state.set_state(SupportState.waiting_for_message)
    await callback.message.edit_text(
        f"Опишите ваше обращение ({category_names.get(category, category)}).{hint}"
    )
    await callback.answer()


@router.message(SupportState.waiting_for_message)
async def process_support_message(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category = data.get("support_category")

    if category == "complaint":
        if not message.photo:
            await message.answer(
                "❌ Для жалоб обязательно приложите минимум 1 скриншот.\n"
                "Отправьте сообщение повторно с фото."
            )
            return

    text = message.text or message.caption or ""
    media_type = None
    media_file_id = None

    if message.photo:
        media_type = "photo"
        media_file_id = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        media_file_id = message.video.file_id
    elif message.video_note:
        media_type = "video_note"
        media_file_id = message.video_note.file_id

    ticket_id = await db.add_support_ticket(
        user_id=message.from_user.id,
        category=category,
        text=text,
        media_type=media_type,
        media_file_id=media_file_id,
    )

    await state.clear()

    category_names = {
        "bug": "🐛 Нашёл баг",
        "complaint": "🚫 Жалоба на пользователя",
        "idea": "💡 Предложение / идея",
    }

    user = message.from_user
    owner_text = (
        f"📩 Поддержка [{category_names.get(category, category)}]\n"
        f"От: {_sender_display(user)} (id: {user.id})\n\n"
        f"{text}"
    )

    if media_type == "photo":
        await bot.send_photo(
            chat_id=OWNER_ID,
            photo=media_file_id,
            caption=owner_text,
            reply_markup=support_action_keyboard(ticket_id),
        )
    elif media_type == "video":
        await bot.send_video(
            chat_id=OWNER_ID,
            video=media_file_id,
            caption=owner_text,
            reply_markup=support_action_keyboard(ticket_id),
        )
    elif media_type == "video_note":
        await bot.send_message(chat_id=OWNER_ID, text=owner_text)
        await bot.send_video_note(
            chat_id=OWNER_ID,
            video_note=media_file_id,
        )
        await bot.send_message(
            chat_id=OWNER_ID,
            text="Действия:",
            reply_markup=support_action_keyboard(ticket_id),
        )
    else:
        await bot.send_message(
            chat_id=OWNER_ID,
            text=owner_text,
            reply_markup=support_action_keyboard(ticket_id),
        )

    await message.answer(
        "✅ Обращение принято! Ожидайте ответа.",
        reply_markup=persistent_keyboard(),
    )


@router.callback_query(F.data.startswith("support_reply:"))
async def callback_support_reply(callback: CallbackQuery, state: FSMContext):
    try:
        ticket_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await state.update_data(reply_message_id=ticket_id, is_support_reply=True)
    await state.set_state(ReplyState.waiting_for_reply)
    await callback.message.answer("Введите ответ пользователю:")
    await callback.answer()


@router.callback_query(F.data.startswith("support_append:"))
async def callback_support_append(callback: CallbackQuery, state: FSMContext):
    try:
        ticket_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await state.update_data(append_ticket_id=ticket_id)
    await state.set_state(SupportState.waiting_for_append)
    await callback.message.answer("Отправьте дополнение к вашему обращению:")
    await callback.answer()


@router.message(SupportState.waiting_for_append)
async def process_support_append(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ticket_id = data.get("append_ticket_id")

    if not ticket_id:
        await message.answer("Произошла ошибка.")
        await state.clear()
        return

    await db.append_ticket_text(ticket_id, message.text or "")
    await state.clear()

    ticket = await db.get_ticket(ticket_id)
    if ticket:
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"➕ Дополнение к обращению #{ticket_id}:\n\n{message.text}",
        )

    await message.answer(
        "✅ Дополнение добавлено!",
        reply_markup=persistent_keyboard(),
    )


@router.callback_query(F.data.startswith("support_edit:"))
async def callback_support_edit(callback: CallbackQuery, state: FSMContext):
    try:
        ticket_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    await state.update_data(edit_ticket_id=ticket_id)
    await state.set_state(SupportState.waiting_for_edit)
    await callback.message.answer("Отправьте новое сообщение (старое будет заменено):")
    await callback.answer()


@router.message(SupportState.waiting_for_edit)
async def process_support_edit(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ticket_id = data.get("edit_ticket_id")

    if not ticket_id:
        await message.answer("Произошла ошибка.")
        await state.clear()
        return

    await db.update_ticket_text(ticket_id, message.text or "")
    await state.clear()

    await bot.send_message(
        chat_id=OWNER_ID,
        text=f"✏️ Обращение #{ticket_id} отредактировано:\n\n{message.text}",
    )

    await message.answer(
        "✅ Обращение отредактировано!",
        reply_markup=persistent_keyboard(),
    )


@router.callback_query(F.data.startswith("support_thank:"))
async def callback_support_thank(callback: CallbackQuery, bot: Bot):
    try:
        ticket_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    await db.resolve_ticket(ticket_id)

    category = ticket["category"]
    user_id = ticket["user_id"]

    deltas = {"bug": 0.2, "complaint": 0.1, "idea": 0.1}
    delta = deltas.get(category, 0.1)
    await db.adjust_rating(user_id, delta)

    thank_messages = {
        "bug": "Спасибо за найденный баг! Мы уже работаем над исправлением.",
        "complaint": "Спасибо за обращение! Мы рассмотрим вашу жалобу.",
        "idea": "Спасибо за предложение! Мы ценим ваш вклад в развитие бота.",
    }

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"📩 Ответ поддержки:\n\n{thank_messages.get(category, 'Спасибо за обращение!')}\n\n"
                 f"Ваш рейтинг повышен на {delta} ⭐",
        )
    except Exception:
        pass

    await callback.message.edit_text(
        f"✅ Спасибо отправлено пользователю. Тикет #{ticket_id} закрыт.",
    )
    await callback.answer()


@router.message(F.text == "🏠 Меню")
async def btn_menu(message: Message):
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.photo)
async def handle_media_photo(message: Message, bot: Bot):
    await _forward_media_to_owner(bot, message, "photo", message.photo[-1].file_id)


@router.message(F.video)
async def handle_media_video(message: Message, bot: Bot):
    await _forward_media_to_owner(bot, message, "video", message.video.file_id)


@router.message(F.video_note)
async def handle_media_video_note(message: Message, bot: Bot):
    await _forward_media_to_owner(bot, message, "video_note", message.video_note.file_id)


async def _forward_media_to_owner(bot: Bot, message: Message, media_type: str, file_id: str):
    user = message.from_user
    if user.id == OWNER_ID:
        return

    if await db.is_banned(OWNER_ID, user.id):
        return

    caption = f"📷 {media_type.upper()} от {_sender_display(user)} (id: {user.id})"

    try:
        if media_type == "photo":
            await bot.send_photo(chat_id=OWNER_ID, photo=file_id, caption=caption)
        elif media_type == "video":
            await bot.send_video(chat_id=OWNER_ID, video=file_id, caption=caption)
        elif media_type == "video_note":
            await bot.send_message(chat_id=OWNER_ID, text=caption)
            await bot.send_video_note(chat_id=OWNER_ID, video_note=file_id)
    except Exception as e:
        logging.error(f"Ошибка пересылки медиа владельцу: {e}")
