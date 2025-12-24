import logging
import os
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Структуры данных
# polls: {poll_id: {question, options: {opt_id: {text, votes: {user_id: name}}}, creator_id, messages: List[{chat_id,message_id}], is_creating}}
polls: Dict[str, Dict] = {}
# creation_states: {user_id: {poll_id, step}}
creation_states: Dict[int, Dict] = {}
# последняя завершенная анкета автора
last_poll_by_creator: Dict[int, str] = {}


def format_poll(poll_id: str) -> str:
    poll = polls[poll_id]
    lines = [f"📊 <b>{poll['question']}</b>", ""]
    for opt_id, opt in poll["options"].items():
        voters = opt["votes"].values()
        voter_line = ", ".join(voters) if voters else "—"
        lines.append(f"• <b>{opt['text']}</b> — {len(opt['votes'])}")
        lines.append(f"    👥 {voter_line}")
        lines.append("")
    return "\n".join(lines).strip()


def build_keyboard(poll_id: str, is_creating: bool, current_chat_id: int = None) -> InlineKeyboardMarkup:
    keyboard = []
    poll = polls[poll_id]
    for opt_id, opt in poll["options"].items():
        cnt = len(opt["votes"])
        text = f"{opt['text']} ({cnt})"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"vote_{poll_id}|{opt_id}")])
    if is_creating:
        keyboard.append([InlineKeyboardButton("➕ Добавить вариант", callback_data=f"add_{poll_id}")])
        keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data=f"finish_{poll_id}")])
        keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{poll_id}")])
    else:
        # Показываем кнопки пересылки только в оригинальном чате
        if current_chat_id is not None and poll.get("original_chat_id") == current_chat_id:
            keyboard.append([InlineKeyboardButton("📤 В \"Ночная волейбольная\"", callback_data=f"sharetofixed_{poll_id}|-1003228733392")])
            keyboard.append([InlineKeyboardButton("📤 В \"5 школа волейбол\"", callback_data=f"sharetofixed_{poll_id}|-1003249941279")])
    return InlineKeyboardMarkup(keyboard)


# Постоянная клавиатура с кнопкой "Создать опрос"
POLL_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("Создать опрос")]],
    resize_keyboard=True
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, мон шэр {user.first_name}! 👋\n\n"
        "Кнопка «Создать опрос» сделает всё по красоте.\n\n",
        reply_markup=POLL_KEYBOARD
    )


async def createpoll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /createpoll и кнопки 'Создать опрос'"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    poll_id = f"poll_{user_id}_{update.message.message_id}"
    polls[poll_id] = {
        "question": "",
        "photo_file_id": None,
        "options": {},
        "creator_id": user_id,
        "messages": [],
        "is_creating": True,
        "original_chat_id": chat_id,  # Сохраняем оригинальный чат, где создан опрос
    }
    creation_states[user_id] = {"poll_id": poll_id, "step": "question"}

    await update.message.reply_text(
        "📝 Создание опроса\n\nШаг 1/3: отправьте вопрос.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{poll_id}")]]),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    # Обработка кнопки "Создать опрос"
    if update.message.text == "Создать опрос":
        await createpoll(update, context)
        return
    
    if user_id not in creation_states:
        return

    state = creation_states[user_id]
    poll_id = state["poll_id"]
    step = state["step"]

    if step == "question":
        polls[poll_id]["question"] = update.message.text.strip()
        state["step"] = "photo"
        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_photo_{poll_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{poll_id}")]
        ]
        await update.message.reply_text(
            "Шаг 2/3: отправьте картинку для опроса (или пропустите этот шаг).",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    elif step == "add_option":
        text = update.message.text.strip()
        if not text:
            return
        opt_id = f"opt_{len(polls[poll_id]['options'])}"
        polls[poll_id]["options"][opt_id] = {"text": text, "votes": {}}
        state["step"] = "options"

        preview = format_poll(poll_id)
        kb = build_keyboard(poll_id, is_creating=True)
        await update.message.reply_text(
            f"✅ Вариант добавлен.\n\nТекущий опрос:\n\n{preview}",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает загрузку фото во время создания опроса"""
    user_id = update.effective_user.id
    if user_id not in creation_states:
        return
    
    state = creation_states[user_id]
    poll_id = state["poll_id"]
    step = state["step"]
    
    if step == "photo":
        # Сохраняем file_id самой большой версии фото
        polls[poll_id]["photo_file_id"] = update.message.photo[-1].file_id
        state["step"] = "options"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить вариант", callback_data=f"add_{poll_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{poll_id}")]
        ]
        await update.message.reply_text(
            "✅ Картинка добавлена!\n\nШаг 3/3: добавьте варианты. Нажмите «➕ Добавить вариант», затем отправьте текст.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # Голосование
    if data.startswith("vote_"):
        try:
            poll_id, opt_id = data.replace("vote_", "", 1).split("|", 1)
        except ValueError:
            return
        if poll_id not in polls:
            return
        poll = polls[poll_id]
        if opt_id not in poll["options"]:
            return
        option = poll["options"][opt_id]
        # Тоггл голоса
        if user_id in option["votes"]:
            del option["votes"][user_id]
        else:
            name = query.from_user.username or query.from_user.full_name
            option["votes"][user_id] = f"@{name}" if query.from_user.username else name

        # регистрируем сообщение, если его ещё нет (для пересланных копий)
        msg_chat_id = query.message.chat.id
        msg_id = query.message.message_id
        if not any(m["chat_id"] == msg_chat_id and m["message_id"] == msg_id for m in poll["messages"]):
            poll["messages"].append({"chat_id": msg_chat_id, "message_id": msg_id})

        text = format_poll(poll_id)
        # обновляем все копии опроса (оригинал + пересылки)
        for m in list(poll["messages"]):
            try:
                # Для каждого сообщения создаем клавиатуру с учетом его chat_id
                kb = build_keyboard(poll_id, is_creating=False, current_chat_id=m["chat_id"])
                # Обновляем сообщение с фото или без
                if poll.get("photo_file_id"):
                    await context.bot.edit_message_media(
                        chat_id=m["chat_id"],
                        message_id=m["message_id"],
                        media=InputMediaPhoto(
                            media=poll["photo_file_id"],
                            caption=text,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=kb,
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=m["chat_id"],
                        message_id=m["message_id"],
                        text=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
            except Exception:
                # если сообщение удалить нельзя (например, нет доступа), просто пропускаем
                continue
        return

    # Действия только для создателя
    if user_id not in creation_states:
        await query.answer("Нет активного черновика. /createpoll", show_alert=True)
        return
    state = creation_states[user_id]
    poll_id = state["poll_id"]
    if poll_id not in polls:
        return
    poll = polls[poll_id]

    if data == f"skip_photo_{poll_id}":
        if user_id not in creation_states or creation_states[user_id]["poll_id"] != poll_id:
            await query.answer("Ошибка доступа", show_alert=True)
            return
        state = creation_states[user_id]
        state["step"] = "options"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить вариант", callback_data=f"add_{poll_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{poll_id}")]
        ]
        await query.edit_message_text(
            "Шаг 3/3: добавьте варианты. Нажмите «➕ Добавить вариант», затем отправьте текст.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    elif data == f"add_{poll_id}":
        state["step"] = "add_option"
        await query.edit_message_text(
            "Отправьте текст варианта ответа:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{poll_id}")]]),
        )
    elif data == f"finish_{poll_id}":
        if len(poll["options"]) < 2 or not poll["question"]:
            await query.answer("Нужен вопрос и минимум 2 варианта.", show_alert=True)
            return
        poll["is_creating"] = False
        del creation_states[user_id]
        last_poll_by_creator[user_id] = poll_id
        text = format_poll(poll_id)
        # При публикации показываем кнопки пересылки только в оригинальном чате
        kb = build_keyboard(poll_id, is_creating=False, current_chat_id=query.message.chat.id)
        if poll.get("photo_file_id"):
            sent = await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=poll["photo_file_id"],
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        else:
            sent = await context.bot.send_message(chat_id=query.message.chat.id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        poll["messages"] = [{"chat_id": query.message.chat.id, "message_id": sent.message_id}]
        await query.edit_message_text("✅ Опрос опубликован. Голосуйте кнопками ниже.")
        # Отправляем постоянную клавиатуру в чат, если это личный чат
        if query.message.chat.type == "private":
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text="Используйте кнопку «Создать опрос» для создания нового опроса.",
                    reply_markup=POLL_KEYBOARD
                )
            except Exception:
                pass
    elif data == f"cancel_{poll_id}":
        del polls[poll_id]
        if user_id in creation_states:
            del creation_states[user_id]
        await query.edit_message_text("❌ Создание опроса отменено.")
    elif data.startswith("sharetofixed_"):
        try:
            poll_id, cid = data.replace("sharetofixed_", "", 1).split("|", 1)
            target_chat = int(cid)
        except ValueError:
            await query.answer("Неверные данные для пересылки", show_alert=True)
            return
        if poll_id not in polls:
            await query.answer("Опрос не найден", show_alert=True)
            return
        poll = polls[poll_id]
        if poll["is_creating"]:
            await query.answer("Сначала завершите создание опроса", show_alert=True)
            return
        text = format_poll(poll_id)
        # В пересланных чатах кнопки пересылки не показываем
        kb = build_keyboard(poll_id, is_creating=False, current_chat_id=target_chat)
        try:
            if poll.get("photo_file_id"):
                sent = await context.bot.send_photo(
                    chat_id=target_chat,
                    photo=poll["photo_file_id"],
                    caption=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            else:
                sent = await context.bot.send_message(chat_id=target_chat, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            await query.answer("Не удалось отправить (проверьте chat_id и права бота)", show_alert=True)
            return
        poll["messages"].append({"chat_id": target_chat, "message_id": sent.message_id})
        await query.answer("Опрос отправлен", show_alert=False)


async def share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет последний созданный опрос автора в указанный chat_id (кнопки сохраняются)"""
    user_id = update.effective_user.id
    if user_id not in last_poll_by_creator:
        await update.message.reply_text("Нет готового опроса. Сначала создайте его через /createpoll.")
        return
    if not context.args:
        await update.message.reply_text("Укажите chat_id: /share <chat_id> (например /share -1001234567890)")
        return

    poll_id = last_poll_by_creator[user_id]
    if poll_id not in polls:
        await update.message.reply_text("Опрос не найден. Создайте новый /createpoll.")
        return

    try:
        target_chat = int(context.args[0])
    except ValueError:
        await update.message.reply_text("chat_id должен быть числом, например -1001234567890")
        return

    poll = polls[poll_id]
    if poll["is_creating"]:
        await update.message.reply_text("Сначала завершите создание опроса.")
        return

    text = format_poll(poll_id)
    # В пересланных чатах кнопки пересылки не показываем
    kb = build_keyboard(poll_id, is_creating=False, current_chat_id=target_chat)
    try:
        if poll.get("photo_file_id"):
            sent = await context.bot.send_photo(
                chat_id=target_chat,
                photo=poll["photo_file_id"],
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        else:
            sent = await context.bot.send_message(chat_id=target_chat, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Не удалось отправить. Проверьте chat_id и права бота в чате.")
        return
    poll["messages"].append({"chat_id": target_chat, "message_id": sent.message_id})
    await update.message.reply_text("Опрос отправлен. Голоса и списки будут синхронизированы во всех копиях.")


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN или добавьте её в .env")
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("createpoll", createpoll))
    app.add_handler(CommandHandler("share", share))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
