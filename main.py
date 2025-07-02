import os
import telebot
from telebot import types
import datetime
import time
from flask import Flask, request

# Убедимся, что текущая рабочая директория - это директория скрипта
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Импортируем наши менеджеры
# Убедитесь, что db_manager.py и pet_config.py находятся в той же директории
from db_manager import db
from pet_config import (
    PET_TYPES, PET_IMAGES,
    WELCOME_BONUS_AMOUNT, WELCOME_BONUS_ACTIONS_REQUIRED,
    DAILY_BONUS_AMOUNT, DAILY_BONUS_INTERVAL_HOURS,
    FOOD_COST, MEDICINE_COST, NEW_PET_COST,
    FEED_REWARD, PLAY_REWARD, CLEAN_REWARD,
    ACTION_COOLDOWN_HOURS,
    HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR, HEALTH_DECAY_PER_HOUR,
    HUNGER_THRESHOLD_SAD, HAPPINESS_THRESHOLD_SAD, HEALTH_THRESHOLD_SICK,
    INFO_TEXT, HELP_TEXT, TOTAL_INITIAL_SUPPLY, ADMIN_TELEGRAM_ID
)

# --- Настройка бота и вебхуков ---
# Получаем токен бота из переменных окружения
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if BOT_TOKEN is None:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set. Please set it on Render.com")

bot = telebot.TeleBot(BOT_TOKEN)

# Настройка Flask для вебхуков
app = Flask(__name__)

# --- Вспомогательные функции ---

# Функция для получения текущего времени в UTC и формате ISO
def get_current_iso_time():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

# Функция для конвертации ISO строки в datetime объект
def parse_iso_time(iso_str):
    if iso_str:
        return datetime.datetime.fromisoformat(iso_str)
    return None

# Функция для обновления состояния питомца (голод, счастье, здоровье)
def update_pet_stats(pet_data):
    if not pet_data or not pet_data['is_alive']:
        return pet_data

    last_update_time = parse_iso_time(pet_data['last_state_update'])
    if not last_update_time: # Если время последнего обновления не установлено, устанавливаем текущее
        pet_data['last_state_update'] = get_current_iso_time()
        # Обновляем в БД, чтобы не было постоянных вызовов
        db.update_pet_state(pet_data['owner_id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])
        return pet_data

    current_time = datetime.datetime.now(datetime.timezone.utc)
    time_diff_hours = (current_time - last_update_time).total_seconds() / 3600

    if time_diff_hours > 0:
        pet_data['hunger'] = max(0.0, pet_data['hunger'] - (HUNGER_DECAY_PER_HOUR * time_diff_hours))
        pet_data['happiness'] = max(0.0, pet_data['happiness'] - (HAPPINESS_DECAY_PER_HOUR * time_diff_hours))
        pet_data['health'] = max(0.0, pet_data['health'] - (HEALTH_DECAY_PER_HOUR * time_diff_hours))
        
        # Ухудшение здоровья при низком голоде/счастье
        if pet_data['hunger'] < HUNGER_THRESHOLD_SAD:
            pet_data['health'] = max(0.0, pet_data['health'] - (HEALTH_DECAY_PER_HOUR * time_diff_hours * 0.5))
        if pet_data['happiness'] < HAPPINESS_THRESHOLD_SAD:
            pet_data['health'] = max(0.0, pet_data['health'] - (HEALTH_DECAY_PER_HOUR * time_diff_hours * 0.5))
        
        pet_data['last_state_update'] = get_current_iso_time()

        # Проверка на смерть
        if pet_data['hunger'] <= 0 or pet_data['happiness'] <= 0 or pet_data['health'] <= 0:
            if pet_data['is_alive']:
                db.kill_pet(pet_data['owner_id'])
                pet_data['is_alive'] = 0
                user = db.get_user_by_db_id(pet_data['owner_id'])
                if user:
                    bot.send_message(user['telegram_id'],
                                     f"К сожалению, ваш питомец *{pet_data['name']}* умер 😔. "
                                     f"Вы можете завести нового питомца за {NEW_PET_COST} Tamacoin с помощью команды /buy_pet.",
                                     parse_mode='Markdown')
            
        db.update_pet_state(pet_data['owner_id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])
    
    return pet_data

# Функция для получения актуального статуса питомца и его изображения
def get_pet_status_and_image(user_id, pet_data):
    pet_data = update_pet_stats(pet_data)

    if not pet_data or not pet_data['is_alive']:
        return "У вас пока нет питомца или он мертв. Используйте /start, чтобы завести нового или /buy_pet, чтобы приобрести.", PET_IMAGES.get('dead_pet')

    status_text = f"Ваш питомец: *{pet_data['name']}* ({PET_TYPES[pet_data['pet_type']]['name']})\n\n"
    status_text += f"Голод: `{pet_data['hunger']:.1f}%`\n"
    status_text += f"Счастье: `{pet_data['happiness']:.1f}%`\n"
    status_text += f"Здоровье: `{pet_data['health']:.1f}%`\n"

    image_key = pet_data['pet_type']
    
    if pet_data['hunger'] < HUNGER_THRESHOLD_SAD or \
       pet_data['happiness'] < HAPPINESS_THRESHOLD_SAD or \
       pet_data['health'] < HEALTH_THRESHOLD_SICK:
        
        if PET_IMAGES.get(pet_data['pet_type'] + '_hungry'):
            image_key = pet_data['pet_type'] + '_hungry'

    if pet_data['health'] < HEALTH_THRESHOLD_SICK and PET_IMAGES.get(pet_data['pet_type'] + '_sick'):
        image_key = pet_data['pet_type'] + '_sick'


    if PET_IMAGES.get(image_key):
        return status_text, PET_IMAGES[image_key]
    else:
        return status_text, list(PET_IMAGES.values())[0] if PET_IMAGES else None


# Проверка кулдауна действия
def is_action_on_cooldown(last_action_time_str):
    if last_action_time_str:
        last_action_time = parse_iso_time(last_action_time_str)
        current_time = datetime.datetime.now(datetime.timezone.utc)
        time_diff_hours = (current_time - last_action_time).total_seconds() / 3600
        return time_diff_hours < ACTION_COOLDOWN_HOURS
    return False

# --- Обработчики команд ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = db.get_user(message.from_user.id)
    if not user:
        user = db.create_user(message.from_user.id, message.from_user.username)

    user_pet = db.get_pet(user['id'])

    if user_pet and user_pet['is_alive']:
        bot.send_message(message.chat.id, "У вас уже есть питомец! Используйте /status для проверки его состояния или /help для списка команд.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    itembtn1 = types.InlineKeyboardButton(PET_TYPES['toothless']['name'], callback_data='choose_pet_toothless')
    itembtn2 = types.InlineKeyboardButton(PET_TYPES['light_fury']['name'], callback_data='choose_pet_light_fury')
    itembtn3 = types.InlineKeyboardButton(PET_TYPES['stormfly']['name'], callback_data='choose_pet_stormfly')
    markup.add(itembtn1, itembtn2, itembtn3)

    bot.send_message(message.chat.id, "Привет! Выберите своего первого питомца:", reply_markup=markup)
    # Отправляем изображения питомцев
    for pet_key, pet_info in PET_TYPES.items():
        if PET_IMAGES.get(pet_key):
            try:
                with open(PET_IMAGES[pet_key], 'rb') as photo:
                    bot.send_photo(message.chat.id, photo, caption=pet_info['name'])
            except FileNotFoundError:
                bot.send_message(message.chat.id, f"Изображение для {pet_info['name']} не найдено. Проверьте путь: {PET_IMAGES[pet_key]}")
        else:
            bot.send_message(message.chat.id, f"Изображение для {pet_info['name']} не указано в конфигурации.")


@bot.message_handler(commands=['status', 'profile'])
def show_status(message):
    user = db.get_user(message.from_user.id)
    if not user or not user['pet_id']:
        bot.send_message(message.chat.id, "У вас пока нет питомца. Используйте /start, чтобы завести его!")
        return

    pet_data = db.get_pet(user['id'])
    
    if not pet_data:
        bot.send_message(message.chat.id, "Проблема с данными питомца. Пожалуйста, попробуйте /start снова.")
        return

    status_text, pet_image_path = get_pet_status_and_image(user['id'], pet_data)
    
    # Добавляем баланс
    status_text += f"\n\nБаланс Tamacoin: `{user['balance']}🪙`"

    if pet_image_path:
        try:
            with open(pet_image_path, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=status_text, parse_mode='Markdown')
        except FileNotFoundError:
            bot.send_message(message.chat.id, status_text + f"\n\n_Изображение питомца не найдено. Проверьте путь: {pet_image_path}_", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, status_text, parse_mode='Markdown')


@bot.message_handler(commands=['help'])
def send_help(message):
    bot.send_message(message.chat.id, HELP_TEXT, parse_mode='Markdown')

@bot.message_handler(commands=['info'])
def send_info(message):
    bot.send_message(message.chat.id, INFO_TEXT, parse_mode='Markdown')

@bot.message_handler(commands=['users_count'])
def send_users_count(message):
    count = db.get_total_users_with_pets()
    bot.send_message(message.chat.id, f"Общее количество живых питомцев: *{count}*.", parse_mode='Markdown')

# --- Временный общий обработчик колбэков для отладки (ПЕРВЫЙ ОБРАБОТЧИК ДЛЯ CALLBACK_QUERY) ---
@bot.callback_query_handler(func=lambda call: True)
def debug_all_callbacks(call):
    print(f"DEBUG_ALL_CALLBACKS: Received callback_data: '{call.data}' from user {call.from_user.id}")
    # Важно: НЕ вызывайте bot.answer_callback_query здесь, чтобы не перехватывать ее у других обработчиков
    # и не мешать их работе. Этот обработчик должен быть временным и удален после отладки.


# --- Обработчик инлайн-кнопок ВЫБОРА ПИТОМЦА ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('choose_pet_'))
def callback_choose_pet(call):
    print(f"DEBUG: callback_choose_pet called for user {call.from_user.id} with data '{call.data}'")
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id
    
    try:
        user = db.get_user(user_telegram_id)
        print(f"DEBUG: User data retrieved: {user}")
        if not user:
            user = db.create_user(user_telegram_id, call.from_user.username)
            print(f"DEBUG: User created: {user}")

        user_pet = db.get_pet(user['id'])
        print(f"DEBUG: Pet data retrieved: {user_pet}")

        if user_pet and user_pet['is_alive']:
            bot.answer_callback_query(call.id, "У вас уже есть живой питомец!")
            bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                  text="У вас уже есть питомец. Используйте /status для проверки его состояния.",
                                  reply_markup=None)
            print("DEBUG: Already has a pet, returning.")
            return

        pet_type_key = call.data.replace('choose_pet_', '')
        print(f"DEBUG: Pet type key: {pet_type_key}")
        if pet_type_key not in PET_TYPES:
            bot.answer_callback_query(call.id, "Неизвестный тип питомца.")
            print("DEBUG: Unknown pet type, returning.")
            return

        # Если питомец мертв или отсутствует, создаем нового
        pet_name = PET_TYPES[pet_type_key]['name'] # Используем дефолтное имя типа как имя питомца
        new_pet = db.create_pet(user['id'], pet_type_key, pet_name)
        print(f"DEBUG: New pet created: {new_pet}")
        
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text=f"Поздравляем! Вы выбрали питомца: *{pet_name}*!",
                              parse_mode='Markdown', reply_markup=None)
        
        # Отправляем первое сообщение о состоянии питомца
        status_text, pet_image_path = get_pet_status_and_image(user['id'], new_pet)
        status_text += f"\n\nБаланс Tamacoin: `{user['balance']}🪙`" # Пока 0

        if pet_image_path:
            try:
                with open(pet_image_path, 'rb') as photo:
                    bot.send_photo(chat_id, photo, caption=status_text, parse_mode='Markdown')
            except FileNotFoundError:
                bot.send_message(chat_id, status_text + f"\n\n_Изображение питомца не найдено. Проверьте путь: {pet_image_path}_", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, status_text, parse_mode='Markdown')
        
        bot.send_message(chat_id, "Теперь начните ухаживать за ним! Помните, что вам нужно совершить 5 действий, чтобы получить приветственный бонус.")
        
        bot.answer_callback_query(call.id, "Питомец выбран!") # Добавил для уверенности, чтобы закрыть индикатор загрузки кнопки

    except Exception as e:
        print(f"ERROR: An unhandled exception occurred in callback_choose_pet: {e}")
        import traceback
        traceback.print_exc() # Выведет полный стек вызовов в логи
        bot.answer_callback_query(call.id, "Произошла внутренняя ошибка. Попробуйте позже.")
        bot.send_message(chat_id, f"Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте снова. Ошибка: `{e}`", parse_mode='Markdown')
        return

# --- Обработчик инлайн-кнопок МАГАЗИНА ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_item_'))
def callback_buy_item(call):
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id

    user = db.get_user(user_telegram_id)
    if not user:
        bot.answer_callback_query(call.id, "Вы не зарегистрированы.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text="Вы не зарегистрированы. Используйте /start.", reply_markup=None)
        return

    item_type = call.data.replace('buy_item_', '')
    cost = 0
    item_name = ""
    
    if item_type == 'food':
        cost = FOOD_COST
        item_name = "Еда"
    elif item_type == 'medicine':
        cost = MEDICINE_COST
        item_name = "Лекарство"
    else:
        bot.answer_callback_query(call.id, "Неизвестный товар.")
        return

    if user['balance'] < cost:
        bot.answer_callback_query(call.id, "Недостаточно Tamacoin!")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text=f"Недостаточно Tamacoin для покупки *{item_name}*. Ваш баланс: *{user['balance']}*.",
                              parse_mode='Markdown', reply_markup=None)
        return

    # Списываем монеты
    db.update_user_balance(user_telegram_id, -cost)
    updated_balance = db.get_user(user_telegram_id)['balance']

    # Применяем эффект на питомца (если жив)
    pet_data = db.get_pet(user['id'])
    if pet_data and pet_data['is_alive']:
        pet_data = update_pet_stats(pet_data)
        if item_type == 'food':
            pet_data['hunger'] = min(100.0, pet_data['hunger'] + 30.0)
            bot.answer_callback_query(call.id, f"Вы купили еду! Голод питомца увеличен.")
        elif item_type == 'medicine':
            pet_data['health'] = min(100.0, pet_data['health'] + 40.0)
            bot.answer_callback_query(call.id, f"Вы купили лекарство! Здоровье питомца восстановлено.")
        
        db.update_pet_state(user['id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])
        
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text=f"Вы успешно купили *{item_name}*! Ваш новый баланс: *{updated_balance} Tamacoin*.\n"
                                   f"Голод: `{pet_data['hunger']:.1f}%`, Здоровье: `{pet_data['health']:.1f}%`",
                              parse_mode='Markdown', reply_markup=None)
    else:
        bot.answer_callback_query(call.id, "У вас нет активного питомца, чтобы применить товар.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text=f"Вы успешно купили *{item_name}*! Ваш новый баланс: *{updated_balance} Tamacoin*.\n"
                                   f"У вас нет активного питомца, чтобы применить товар. Он останется на вашем счету (хотя пока не реализовано хранение предметов).",
                              parse_mode='Markdown', reply_markup=None)

@bot.message_handler(commands=['buy_pet'])
def buy_new_pet(message):
    user_telegram_id = message.from_user.id
    user = db.get_user(user_telegram_id)

    if not user:
        bot.send_message(message.chat.id, "Вы еще не зарегистрированы. Используйте /start, чтобы начать игру.")
        return

    pet_data = db.get_pet(user['id'])
    if pet_data and pet_data['is_alive']:
        bot.send_message(message.chat.id, "У вас уже есть живой питомец! Вы не можете завести нового.")
        return

    if user['balance'] < NEW_PET_COST:
        bot.send_message(message.chat.id, f"У вас недостаточно Tamacoin для покупки нового питомца. Стоимость: *{NEW_PET_COST} Tamacoin*. Ваш баланс: *{user['balance']}*.", parse_mode='Markdown')
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    itembtn1 = types.InlineKeyboardButton(PET_TYPES['toothless']['name'], callback_data='buy_pet_toothless')
    itembtn2 = types.InlineKeyboardButton(PET_TYPES['light_fury']['name'], callback_data='buy_pet_light_fury')
    itembtn3 = types.InlineKeyboardButton(PET_TYPES['stormfly']['name'], callback_data='buy_pet_stormfly')
    markup.add(itembtn1, itembtn2, itembtn3)

    bot.send_message(message.chat.id, f"Выберите нового питомца за {NEW_PET_COST} Tamacoin. Ваш баланс: *{user['balance']} Tamacoin*.",
                     reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_pet_'))
def callback_buy_new_pet(call):
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id
    
    user = db.get_user(user_telegram_id)
    if not user:
        bot.answer_callback_query(call.id, "Вы не зарегистрированы.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text="Вы не зарегистрированы. Используйте /start.", reply_markup=None)
        return

    pet_data = db.get_pet(user['id'])
    if pet_data and pet_data['is_alive']:
        bot.answer_callback_query(call.id, "У вас уже есть живой питомец!")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text="У вас уже есть живой питомец.", reply_markup=None)
        return

    if user['balance'] < NEW_PET_COST:
        bot.answer_callback_query(call.id, "Недостаточно Tamacoin!")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text=f"Недостаточно Tamacoin для покупки нового питомца. Ваш баланс: *{user['balance']}*.",
                              parse_mode='Markdown', reply_markup=None)
        return

    pet_type_key = call.data.replace('buy_pet_', '')
    if pet_type_key not in PET_TYPES:
        bot.answer_callback_query(call.id, "Неизвестный тип питомца.")
        return

    # Списываем стоимость
    db.update_user_balance(user_telegram_id, -NEW_PET_COST)

    # Создаем нового питомца
    pet_name = PET_TYPES[pet_type_key]['name']
    new_pet = db.create_pet(user['id'], pet_type_key, pet_name)
    
    updated_balance = db.get_user(user_telegram_id)['balance']

    bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                          text=f"Вы успешно купили питомца: *{pet_name}*! Ваш новый баланс: *{updated_balance} Tamacoin*.",
                          parse_mode='Markdown', reply_markup=None)
    
    status_text, pet_image_path = get_pet_status_and_image(user['id'], new_pet)
    status_text += f"\n\nБаланс Tamacoin: `{updated_balance}🪙`"

    if pet_image_path:
        try:
            with open(pet_image_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=status_text, parse_mode='Markdown')
        except FileNotFoundError:
            bot.send_message(chat_id, status_text + f"\n\n_Изображение питомца не найдено. Проверьте путь: {pet_image_path}_", parse_mode='Markdown')
    else:
        bot.send_message(chat_id, status_text, parse_mode='Markdown')
    
    bot.send_message(chat_id, "Начните ухаживать за ним! Помните, что вам нужно совершить 5 действий, чтобы получить приветственный бонус (если вы его ещё не получали).")


# --- Административные команды (для админа) ---
@bot.message_handler(commands=['admin_get_balance'])
def admin_get_balance(message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        bot.send_message(message.chat.id, "У вас нет прав для этой команды.")
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        bot.send_message(message.chat.id, "Использование: /admin_get_balance <telegram_id_пользователя>")
        return
    
    try:
        target_telegram_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "ID пользователя должен быть числом.")
        return

    user = db.get_user(target_telegram_id)
    if user:
        bot.send_message(message.chat.id, f"Баланс пользователя {target_telegram_id}: *{user['balance']} Tamacoin*.", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, f"Пользователь с ID {target_telegram_id} не найден.")

@bot.message_handler(commands=['admin_add_balance'])
def admin_add_balance(message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        bot.send_message(message.chat.id, "У вас нет прав для этой команды.")
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        bot.send_message(message.chat.id, "Использование: /admin_add_balance <telegram_id_пользователя> <сумма>")
        return
    
    try:
        target_telegram_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "ID пользователя и сумма должны быть числами.")
        return

    user = db.get_user(target_telegram_id)
    if user:
        db.update_user_balance(target_telegram_id, amount)
        updated_balance = db.get_user(target_telegram_id)['balance']
        bot.send_message(message.chat.id, f"Пользователю {target_telegram_id} добавлено {amount} Tamacoin. Новый баланс: *{updated_balance} Tamacoin*.", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, f"Пользователь с ID {target_telegram_id} не найден.")

@bot.message_handler(commands=['admin_total_supply'])
def admin_total_supply(message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        bot.send_message(message.chat.id, "У вас нет прав для этой команды.")
        return
    
    total_distributed = db.get_total_distributed_coins()
    bot.send_message(message.chat.id, f"Общий объем распределенных монет (Total Supply): *{total_distributed}* из *{TOTAL_INITIAL_SUPPLY}*.", parse_mode='Markdown')


# --- Вебхук ---
# Это основной обработчик для Flask, который получает обновления от Telegram
@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '!', 200 # Возвращаем 200 OK для Telegram

# Запуск Flask-приложения (для вебхуков)
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
