from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CopyTextButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


class BTN:
    MENU     = "🏠 Меню"
    MY_LINK  = "🔗 Моя ссылка"
    STATS    = "📊 Статистика"
    REPLY    = "💬 Ответить"
    COPY     = "📋 Скопировать ссылку"
    BAN      = "🚫 Забанить"
    UNBAN    = "✅ Разбанить"
    WRITE    = "✉️ Написать ещё"
    GET_LINK = "🔗 Получить ссылку"
    SUPPORT  = "📩 Поддержка"
    EDIT     = "✏️ Редактировать"
    APPEND   = "➕ Дополнить"
    THANK    = "🙏 Сказать спасибо"


def _footer_buttons() -> list:
    return [
        [InlineKeyboardButton(text=BTN.MY_LINK, callback_data="get_my_link")],
        [InlineKeyboardButton(text=BTN.MENU,    callback_data="main_menu")],
    ]


def persistent_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN.MENU)],
        ],
        resize_keyboard=True,
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN.MY_LINK, callback_data="my_link")],
        [InlineKeyboardButton(text="📨 Непрочитанные", callback_data="unread")],
        [InlineKeyboardButton(text=BTN.STATS, callback_data="stats")],
        [InlineKeyboardButton(text=BTN.UNBAN, callback_data="unban_menu")],
        [InlineKeyboardButton(text=BTN.SUPPORT, callback_data="support_menu")],
    ])


def sender_after_send_keyboard(recipient_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN.WRITE, callback_data=f"send_again:{recipient_token}")],
        *_footer_buttons(),
    ])


def reply_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN.REPLY, callback_data=f"reply:{message_id}")],
        [InlineKeyboardButton(text=BTN.BAN,   callback_data=f"ban:{message_id}")],
        [InlineKeyboardButton(text=BTN.MENU,  callback_data="main_menu")],
    ])


def copy_link_keyboard(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN.COPY, copy_text=CopyTextButton(text=link))],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])


def reply_after_reply_keyboard(sender_token: str, message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN.WRITE, callback_data=f"send_again:{sender_token}")],
        [InlineKeyboardButton(text=BTN.BAN,   callback_data=f"ban:{message_id}")],
        *_footer_buttons(),
    ])


def unban_list_keyboard(ban_list: list) -> InlineKeyboardMarkup:
    buttons = []
    for ban in ban_list:
        preview = ban["last_message"] if ban["last_message"] else "нет текста"
        buttons.append([InlineKeyboardButton(
            text=f"Разбанить · «{preview}»",
            callback_data=f"unban:{ban['token']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def support_category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐛 Нашёл баг", callback_data="support:bug")],
        [InlineKeyboardButton(text="🚫 Жалоба на пользователя", callback_data="support:complaint")],
        [InlineKeyboardButton(text="💡 Предложение / идея", callback_data="support:idea")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])


def owner_support_keyboard(ticket_id: int, status: str = "open") -> InlineKeyboardMarkup:
    emoji = {"open": "🟡", "closed": "🟢", "blocked": "🔴"}.get(status, "🟡")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{emoji} Ответить", callback_data=f"support_reply:{ticket_id}")],
    ])


def owner_close_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔒 Закрыть тикет", callback_data=f"support_close:{ticket_id}:close")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"support_close:{ticket_id}:block")],
    ])


def user_support_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать", callback_data=f"support_append:{ticket_id}")],
        [InlineKeyboardButton(text=BTN.EDIT, callback_data=f"support_edit:{ticket_id}")],
        [InlineKeyboardButton(text=BTN.MENU, callback_data="main_menu")],
    ])



