import os
import logging
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from datetime import datetime, timedelta

from db_manager import DBManager # Импортируем класс DBManager
import pet_config # Убедитесь, что этот файл существует и содержит PET_TYPES_DISPLAY, PET_IDS, PET_IMAGES
from game_logic import PetGame # Импортируем класс PetGame

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Получение токена бота и хоста вебхука из переменных окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")

if not TOKEN or not WEBHOOK_HOST:
    logger.error("API_TOKEN or WEBHOOK_HOST environment variable not set.")
    raise ValueError("API_TOKEN or WEBHOOK_HOST environment variable not set.")

PORT = int(os.environ.get('PORT', 10000))

# Инициализация DBManager (синглтон)
db_manager = DBManager()

# Инициализация PetGame с экземпляром DBManager. Объект бота будет передаваться в методы PetGame.
game_instance = PetGame(db_manager)

# --- Текстовые константы ---
START_MESSAGE = "Добро пожаловать в Tamacoin Game! Выберите своего первого питомца:"
SELECT_PET_MESSAGE = "Кого вы хотите завести?"
SHOP_CLOSED_MESSAGE = "Магазин пока закрыт на реконструкцию. Заходите позже!"
DAILY_BONUS_UNAVAILABLE = "Ежедневный бонус будет доступен скоро! (Логика пока не реализована)"
INFO_TEXT = """
**TAMACOIN Game - Играй, развивай, зарабатывай!**

Добро пожаловать в мир Tamacoin, где ты можешь завести своего уникального питомца и заботиться о нём! Твои действия влияют на его настроение, здоровье и голод.

**🎮 Геймплей:**
* **Заботься о питомце:** Корми его, играй с ним, убирай за ним. От этого зависит его состояние.
* **Зарабатывай Tamacoin:** Выполняй ежедневные задания, участвуй в мини-играх (скоро!), торгуй на рынке (скоро!).
* **Развивайся:** Покупай улучшения и новые предметы в магазине.

**💰 Что такое Tamacoin (Jetton на TON)?**
Tamacoin - это не просто игровая валюта, это настоящий **Jetton на блокчейне TON**! Это означает, что все твои заработанные монеты - это реальные активы, которые можно вывести и использовать вне игры. Мы стремимся к полной децентрализации и прозрачности!

**🛡️ Безопасность и Технологии:**
Игра построена на передовых блокчейн-технологиях TON, обеспечивая безопасность и прозрачность всех транзакций. Твой прогресс и активы надежно защищены.

**🚀 Будущее игры:**
Мы постоянно работаем над добавлением нового функционала:
* Мини-игры и квесты
* Торговая площадка для питомцев и предметов
* Система обмена Tamacoin на другие криптовалюты
* Социальные функции и рейтинги

Присоединяйся к нашему сообществу и стань частью будущего Tamacoin!
"""


# --- Функции-обработчики команд ---

async def start_command(update: Update, context):
    telegram_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name

    user = db_manager.get_user(telegram_id)
    if user is None:
        internal_user_id = db_manager.add_user(telegram_id, username, first_name, last_name)
        logger.info(f"New user registered: {telegram_id}")
    else:
        internal_user_id = user[0] # Получаем внутренний ID пользователя
        logger.info(f"User {telegram_id} already exists. Checking for pet.")

    pet = db_manager.get_pet(internal_user_id)
    if pet is None:
        keyboard = [
            [InlineKeyboardButton(pet_config.PET_TYPES_DISPLAY[pet_id], callback_data=f"select_pet_{pet_id}")
             for pet_id in pet_config.PET_IDS] # Используем PET_IDS для callback_data и PET_TYPES_DISPLAY для текста кнопки
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(START_MESSAGE, reply_markup=reply_markup)
        await update.message.reply_text(SELECT_PET_MESSAGE)
    else:
        await update.message.reply_text("Добро пожаловать обратно! У вас уже есть питомец.")
        await game_instance.send_pet_status(update.effective_chat.id, internal_user_id, context.bot)

async def button_callback_handler(update: Update, context):
    query = update.callback_query
    await query.answer() # Важно ответить на callback_query, чтобы кнопка перестала мигать
    
    telegram_id = query.from_user.id
    
    user_record = db_manager.get_user(telegram_id)
    if user_record:
        internal_user_id = user_record[0]
    else:
        await query.edit_message_text("Произошла ошибка: не удалось найти вашего пользователя. Пожалуйста, начните с /start.")
        return

    data = query.data
    if data.startswith("select_pet_"):
        pet_id_from_callback = data.split("_")[2] # Это будет 'toothless', 'light_fury' и т.д.
        
        # Проверяем, что pet_id_from_callback является одним из разрешенных ID питомцев
        if pet_id_from_callback not in pet_config.PET_IDS:
            await query.edit_message_text("Неизвестный тип питомца. Пожалуйста, выберите из предложенных вариантов.")
            return

        pet_type_for_db = pet_id_from_callback # Для базы данных используем ID ('toothless')
        pet_display_name = pet_config.PET_TYPES_DISPLAY.get(pet_id_from_callback) # Для отображения используем русское имя
        
        existing_pet = db_manager.get_pet(internal_user_id)
        if existing_pet:
            await query.edit_message_text(f"У вас уже есть питомец: {existing_pet[3]} ({existing_pet[2]}).")
            await game_instance.send_pet_status(query.message.chat_id, internal_user_id, context.bot)
            return

        success = db_manager.create_pet(internal_user_id, pet_type_for_db, pet_display_name)
        if success:
            await query.edit_message_text(f"Поздравляем! Вы завели питомца: {pet_display_name} ({pet_type_for_db}).")
            
            image_path = pet_config.PET_IMAGES.get(pet_type_for_db + "_normal") # Используем ID питомца + "_normal" для поиска изображения
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as image_file:
                    await context.bot.send_photo(chat_id=query.message.chat_id, photo=InputFile(image_file), caption=f"{pet_display_name} ({pet_type_for_db})")
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"Изображение для {pet_display_name} ({pet_type_for_db}) не найдено. Убедитесь, что файл {pet_type_for_db}_normal.png существует.")

            await game_instance.send_pet_status(query.message.chat_id, internal_user_id, context.bot)
        else:
            await query.edit_message_text("Не удалось завести питомца. Возможно, у вас уже есть питомец или произошла ошибка.")

async def status_command(update: Update, context):
    telegram_id = update.effective_user.id
    user = db_manager.get_user(telegram_id)
    if user is None:
        await update.message.reply_text("Пожалуйста, начните игру с команды /start.")
        return

    internal_user_id = user[0]
    pet = db_manager.get_pet(internal_user_id)
    if pet is None:
        await update.message.reply_text("У вас еще нет питомца! Выберите его, используя команду /start.")
    else:
        await game_instance.send_pet_status(update.effective_chat.id, internal_user_id, context.bot)

async def feed_command(update: Update, context):
    telegram_id = update.effective_user.id
    user = db_manager.get_user(telegram_id)
    if user is None:
        await update.message.reply_text("Пожалуйста, начните игру с команды /start.")
        return

    internal_user_id = user[0]
    pet = db_manager.get_pet(internal_user_id)
    if pet is None:
        await update.message.reply_text("У вас еще нет питомца! Выберите его, используя команду /start.")
    else:
        await game_instance.feed_pet(update.effective_chat.id, internal_user_id, context.bot)

async def play_command(update: Update, context):
    telegram_id = update.effective_user.id
    user = db_manager.get_user(telegram_id)
    if user is None:
        await update.message.reply_text("Пожалуйста, начните игру с команды /start.")
        return

    internal_user_id = user[0]
    pet = db_manager.get_pet(internal_user_id)
    if pet is None:
        await update.message.reply_text("У вас еще нет питомца! Выберите его, используя команду /start.")
    else:
        await game_instance.play_with_pet(update.effective_chat.id, internal_user_id, context.bot)

async def clean_command(update: Update, context):
    telegram_id = update.effective_user.id
    user = db_manager.get_user(telegram_id)
    if user is None:
        await update.message.reply_text("Пожалуйста, начните игру с команды /start.")
        return

    internal_user_id = user[0]
    pet = db_manager.get_pet(internal_user_id)
    if pet is None:
        await update.message.reply_text("У вас еще нет питомца! Выберите его, используя команду /start.")
    else:
        await game_instance.clean_pet_area(update.effective_chat.id, internal_user_id, context.bot)

async def shop_command(update: Update, context):
    await update.message.reply_text(SHOP_CLOSED_MESSAGE)

async def daily_bonus_command(update: Update, context):
    await update.message.reply_text(DAILY_BONUS_UNAVAILABLE)

async def info_command(update: Update, context):
    await update.message.reply_text(INFO_TEXT, parse_mode='Markdown')

async def users_count_command(update: Update, context):
    count = db_manager.get_total_users_count()
    await update.message.reply_text(f"Общее количество пользователей: {count}.")

async def admin_stats_command(update: Update, context):
    # !!! Важно: в реальном приложении нужно добавить проверку на администратора !!!
    # Например: if update.effective_user.id != YOUR_ADMIN_TELEGRAM_ID: return
    
    stats = db_manager.get_game_stats()
    if stats:
        await update.message.reply_text(
            f"Административная статистика:\n"
            f"Всего эмитировано Tamacoin: {stats.get('total_emitted_tamacoin', 0)}\n"
            f"Всего пользователей: {stats.get('total_users', 0)}"
        )
    else:
        await update.message.reply_text("Произошла ошибка при получении административной статистики.")

async def echo(update: Update, context):
    await update.message.reply_text("Я не понимаю этой команды. Используйте /help для списка команд.")


def main():
    application = Application.builder().token(TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("feed", feed_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("clean", clean_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("daily_bonus", daily_bonus_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("users_count", users_count_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))

    # Обработчик callback-кнопок
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    # Обработчик для всех остальных сообщений (опционально)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Запуск бота на Render с вебхуками
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_HOST + '/' + TOKEN
    )

if __name__ == "__main__":
    main()
