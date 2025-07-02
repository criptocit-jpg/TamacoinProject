import os
import telebot
from telebot import types
import datetime
import time # Для сна, если потребуется (пока не используется напрямую)
from flask import Flask, request # Для вебхуков

# Убедимся, что текущая рабочая директория - это директория скрипта
# Это важно для корректного поиска файлов изображений на сервере на Render.com
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Импортируем наши менеджеры
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
# ВАЖНО: НЕ ВПИСЫВАЙТЕ ТОКЕН НАПРЯМУЮ ЗДЕСЬ! Используйте переменные окружения Render.com
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
# Зависит от прошедшего времени и базовых параметров decay
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
        pet_data['health'] = max(0.0, pet_data['health'] - (HEALTH_DECAY_PER_HOUR * time_diff_hours)) # базовое снижение
        
        # Ухудшение здоровья при низком голоде/счастье
        if pet_data['hunger'] < HUNGER_THRESHOLD_SAD:
            pet_data['health'] = max(0.0, pet_data['health'] - (HEALTH_DECAY_PER_HOUR * time_diff_hours * 0.5)) # Дополнительное снижение
        if pet_data['happiness'] < HAPPINESS_THRESHOLD_SAD:
            pet_data['health'] = max(0.0, pet_data['health'] - (HEALTH_DECAY_PER_HOUR * time_diff_hours * 0.5)) # Дополнительное снижение
        
        pet_data['last_state_update'] = get_current_iso_time()

        # Проверка на смерть
        if pet_data['hunger'] <= 0 or pet_data['happiness'] <= 0 or pet_data['health'] <= 0:
            if pet_data['is_alive']: # Убедимся, что не убиваем уже мертвого
                db.kill_pet(pet_data['owner_id'])
                pet_data['is_alive'] = 0
                # Уведомляем пользователя о смерти питомца
                user = db.get_user_by_db_id(pet_data['owner_id'])
                if user:
                    bot.send_message(user['telegram_id'],
                                     f"К сожалению, ваш питомец *{pet_data['name']}* умер 😔. "
                                     f"Вы можете завести нового питомца за {NEW_PET_COST} Tamacoin с помощью команды /buy_pet.",
                                     parse_mode='Markdown')
            
        # Обновляем состояние питомца в БД (только если жив или только что умер)
        db.update_pet_state(pet_data['owner_id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])
    
    return pet_data

# Функция для получения актуального статуса питомца и его изображения
def get_pet_status_and_image(user_id, pet_data):
    # Обновляем статистику питомца перед отображением
    pet_data = update_pet_stats(pet_data)

    if not pet_data or not pet_data['is_alive']:
        return "У вас пока нет питомца или он мертв. Используйте /start, чтобы завести нового или /buy_pet, чтобы приобрести.", PET_IMAGES['dead_pet']

    status_text = f"Ваш питомец: *{pet_data['name']}* ({PET_TYPES[pet_data['pet_type']]['name']})\n\n"
    status_text += f"Голод: `{pet_data['hunger']:.1f}%`\n"
    status_text += f"Счастье: `{pet_data['happiness']:.1f}%`\n"
    status_text += f"Здоровье: `{pet_data['health']:.1f}%`\n"

    # Выбираем изображение в зависимости от состояния
    image_key = pet_data['pet_type'] # Базовое изображение
    
    if pet_data['hunger'] < HUNGER_THRESHOLD_SAD or \
       pet_data['happiness'] < HAPPINESS_THRESHOLD_SAD or \
       pet_data['health'] < HEALTH_THRESHOLD_SICK:
        
        # Если есть специфичное изображение для "грустного" состояния, используем его
        if PET_IMAGES.get(pet_data['pet_type'] + '_hungry'):
            image_key = pet_data['pet_type'] + '_hungry'
        # Иначе остаемся с базовым изображением

    # Если есть конкретное изображение для "больного" состояния, оно имеет приоритет
    if pet_data['health'] < HEALTH_THRESHOLD_SICK and PET_IMAGES.get(pet_data['pet_type'] + '_sick'):
        image_key = pet_data['pet_type'] + '_sick'


    if PET_IMAGES.get(image_key):
        return status_text, PET_IMAGES[image_key]
    else:
        # Если ни специфичного, ни базового изображения не найдено, возвращаем заглушку или первое попавшееся
        # Убедимся, что PET_IMAGES не пуст
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
        if PET_IMAGES.get(pet_key): # Проверяем наличие базового изображения
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

    pet_data = db.get_pet(user['id']) # Получаем питомца по owner_id (user['id'])
    
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


# --- Обработчик инлайн-кнопок ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('choose_pet_'))
def callback_choose_pet(call):
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id
    
    user = db.get_user(user_telegram_id)
    if not user:
        user = db.create_user(user_telegram_id, call.from_user.username)

    user_pet = db.get_pet(user['id'])

    if user_pet and user_pet['is_alive']:
        bot.answer_callback_query(call.id, "У вас уже есть живой питомец!")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text="У вас уже есть питомец. Используйте /status для проверки его состояния.",
                              reply_markup=None)
        return

    pet_type_key = call.data.replace('choose_pet_', '')
    if pet_type_key not in PET_TYPES:
        bot.answer_callback_query(call.id, "Неизвестный тип питомца.")
        return

    # Если питомец мертв или отсутствует, создаем нового
    pet_name = PET_TYPES[pet_type_key]['name'] # Используем дефолтное имя типа как имя питомца
    new_pet = db.create_pet(user['id'], pet_type_key, pet_name)
    
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


# --- Команды для взаимодействия с питомцем ---

def _perform_pet_action(message, action_type, reward_amount, stat_to_increase, increase_value, success_message, cooldown_message):
    user_telegram_id = message.from_user.id
    user = db.get_user(user_telegram_id)

    if not user or not user['pet_id']:
        bot.send_message(message.chat.id, "У вас пока нет питомца. Используйте /start, чтобы завести его!")
        return

    pet_data = db.get_pet(user['id'])
    if not pet_data or not pet_data['is_alive']:
        bot.send_message(message.chat.id, "Ваш питомец не активен или мертв. Вы не можете выполнять действия. Используйте /buy_pet, чтобы приобрести нового.")
        return
    
    pet_data = update_pet_stats(pet_data) # Обновляем состояние питомца перед проверкой и действием

    last_action_time_str = pet_data.get(action_type)
    if is_action_on_cooldown(last_action_time_str):
        bot.send_message(message.chat.id, cooldown_message)
        return

    # Выполняем действие
    current_time_iso = get_current_iso_time()
    db.update_pet_action_time(user['id'], action_type, current_time_iso)

    # Увеличиваем соответствующий параметр, но не более 100
    pet_data[stat_to_increase] = min(100.0, pet_data[stat_to_increase] + increase_value)
    
    # Сохраняем обновленное состояние питомца в БД
    db.update_pet_state(user['id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])

    # Выдаем награду
    db.update_user_balance(user_telegram_id, reward_amount) # update_user_balance теперь инкрементирует total_distributed_coins

    updated_balance = db.get_user(user_telegram_id)['balance']

    # Увеличиваем счетчик действий для приветственного бонуса
    actions_count = db.increment_welcome_bonus_actions(user_telegram_id)
    if actions_count >= WELCOME_BONUS_ACTIONS_REQUIRED and user.get('welcome_bonus_actions_count', 0) < WELCOME_BONUS_ACTIONS_REQUIRED:
        # Проверяем, что бонус еще не был выдан (предыдущее значение было меньше)
        db.update_user_balance(user_telegram_id, WELCOME_BONUS_AMOUNT)
        db.reset_welcome_bonus_actions(user_telegram_id) # Сбрасываем счетчик
        bot.send_message(message.chat.id,
                         f"🎉 Поздравляем! Вы совершили {WELCOME_BONUS_ACTIONS_REQUIRED} действий и получили приветственный бонус: *{WELCOME_BONUS_AMOUNT} Tamacoin*!",
                         parse_mode='Markdown')
    
    bot.send_message(message.chat.id, f"{success_message} Ваш баланс: *{updated_balance} Tamacoin*.", parse_mode='Markdown')


@bot.message_handler(commands=['feed'])
def feed_pet(message):
    _perform_pet_action(
        message, 'last_fed', FEED_REWARD, 'hunger', 20.0, # Увеличивает голод на 20%
        "Вы покормили питомца! Он стал более сытым.",
        f"Вы уже кормили питомца менее чем {ACTION_COOLDOWN_HOURS} час назад. Попробуйте позже."
    )

@bot.message_handler(commands=['play'])
def play_with_pet(message):
    _perform_pet_action(
        message, 'last_played', PLAY_REWARD, 'happiness', 25.0, # Увеличивает счастье на 25%
        "Вы поиграли с питомцем! Он очень счастлив.",
        f"Вы уже играли с питомцем менее чем {ACTION_COOLDOWN_HOURS} час назад. Попробуйте позже."
    )

@bot.message_handler(commands=['clean'])
def clean_for_pet(message):
    _perform_pet_action(
        message, 'last_cleaned', CLEAN_REWARD, 'health', 15.0, # Увеличивает здоровье на 15%
        "Вы убрали за питомцем! Он стал чище и здоровее.",
        f"Вы уже убирали за питомцем менее чем {ACTION_COOLDOWN_HOURS} час назад. Попробуйте позже."
    )


@bot.message_handler(commands=['daily_bonus'])
def get_daily_bonus(message):
    user_telegram_id = message.from_user.id
    user = db.get_user(user_telegram_id)

    if not user:
        bot.send_message(message.chat.id, "Вы еще не зарегистрированы. Используйте /start, чтобы начать игру.")
        return

    last_bonus_time_str = user.get('last_daily_bonus')
    current_time = datetime.datetime.now(datetime.timezone.utc)

    if last_bonus_time_str:
        last_bonus_time = parse_iso_time(last_bonus_time_str)
        time_diff_hours = (current_time - last_bonus_time).total_seconds() / 3600
        if time_diff_hours < DAILY_BONUS_INTERVAL_HOURS:
            remaining_time_seconds = (DAILY_BONUS_INTERVAL_HOURS * 3600) - (current_time - last_bonus_time).total_seconds()
            hours = int(remaining_time_seconds // 3600)
            minutes = int((remaining_time_seconds % 3600) // 60)
            bot.send_message(message.chat.id, f"Ежедневный бонус будет доступен через {hours} ч {minutes} мин.")
            return

    db.update_user_balance(user_telegram_id, DAILY_BONUS_AMOUNT)
    db.update_last_daily_bonus(user_telegram_id, get_current_iso_time())
    updated_balance = db.get_user(user_telegram_id)['balance']
    bot.send_message(message.chat.id,
                     f"Вы получили ежедневный бонус: *{DAILY_BONUS_AMOUNT} Tamacoin*! Ваш баланс: *{updated_balance} Tamacoin*.",
                     parse_mode='Markdown')

# --- Магазин и покупка нового питомца ---
@bot.message_handler(commands=['shop'])
def show_shop(message):
    user = db.get_user(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "Вы еще не зарегистрированы. Используйте /start, чтобы начать игру.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    item_food = types.InlineKeyboardButton(f"Купить Еду ({FOOD_COST}🪙)", callback_data='buy_item_food')
    item_medicine = types.InlineKeyboardButton(f"Купить Лекарство ({MEDICINE_COST}🪙)", callback_data='buy_item_medicine')
    markup.add(item_food, item_medicine)

    bot.send_message(message.chat.id, f"Добро пожаловать в магазин! Ваш баланс: *{user['balance']} Tamacoin*.\nЧто хотите купить?",
                     reply_markup=markup, parse_mode='Markdown')

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
        pet_data = update_pet_stats(pet_data) # Обновляем состояние перед применением эффекта
        if item_type == 'food':
            pet_data['hunger'] = min(100.0, pet_data['hunger'] + 30.0) # Еда восстанавливает голод
            db.update_pet_state(user['id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])
            bot.send_message(chat_id, f"Вы купили и использовали Еду. Ваш питомец стал сытнее! Ваш баланс: *{updated_balance} Tamacoin*.", parse_mode='Markdown')
        elif item_type == 'medicine':
            pet_data['health'] = min(100.0, pet_data['health'] + 40.0) # Лекарство восстанавливает здоровье
            db.update_pet_state(user['id'], pet_data['hunger'], pet_data['happiness'], pet_data['health'], pet_data['last_state_update'])
            bot.send_message(chat_id, f"Вы купили и использовали Лекарство. Ваш питомец стал здоровее! Ваш баланс: *{updated_balance} Tamacoin*.", parse_mode='Markdown')
    else:
        # Если питомец мертв или не существует
        bot.send_message(chat_id, f"Вы купили *{item_name}* за {cost} Tamacoin. Ваш баланс: *{updated_balance} Tamacoin*. Но ваш питомец неактивен, поэтому предмет не был использован.", parse_mode='Markdown')

    bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                          text=f"Выбранный товар: *{item_name}*. Текущий баланс: *{updated_balance} Tamacoin*.",
                          parse_mode='Markdown', reply_markup=None)

@bot.message_handler(commands=['buy_pet'])
def buy_new_pet_command(message):
    user = db.get_user(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "Вы еще не зарегистрированы. Используйте /start, чтобы начать игру.")
        return

    user_pet = db.get_pet(user['id'])

    if user_pet and user_pet['is_alive']:
        bot.send_message(message.chat.id, "У вас уже есть живой питомец! Если хотите завести нового, предыдущий должен умереть.")
        return

    if user['balance'] < NEW_PET_COST:
        bot.send_message(message.chat.id, f"Недостаточно Tamacoin для покупки нового питомца. Вам нужно *{NEW_PET_COST} Tamacoin*. Ваш баланс: *{user['balance']}*.", parse_mode='Markdown')
        return

    # Предлагаем выбор питомца после оплаты
    markup = types.InlineKeyboardMarkup(row_width=1)
    for pet_key, pet_info in PET_TYPES.items():
        markup.add(types.InlineKeyboardButton(pet_info['name'], callback_data=f'confirm_buy_pet_{pet_key}'))
    
    bot.send_message(message.chat.id, f"Вы собираетесь приобрести нового питомца за *{NEW_PET_COST} Tamacoin*. Ваш баланс: *{user['balance']} Tamacoin*.\nВыберите тип питомца:",
                     reply_markup=markup, parse_mode='Markdown')


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_buy_pet_'))
def callback_confirm_buy_pet(call):
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id
    
    user = db.get_user(user_telegram_id)
    if not user:
        bot.answer_callback_query(call.id, "Ошибка пользователя.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Ошибка. Попробуйте /start.", reply_markup=None)
        return

    user_pet = db.get_pet(user['id'])
    if user_pet and user_pet['is_alive']:
        bot.answer_callback_query(call.id, "У вас уже есть живой питомец!")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text="У вас уже есть питомец. Используйте /status.", reply_markup=None)
        return

    if user['balance'] < NEW_PET_COST:
        bot.answer_callback_query(call.id, "Недостаточно Tamacoin для покупки нового питомца.")
        bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                              text=f"Недостаточно Tamacoin для покупки нового питомца. Вам нужно *{NEW_PET_COST} Tamacoin*. Ваш баланс: *{user['balance']}*.",
                              parse_mode='Markdown', reply_markup=None)
        return

    pet_type_key = call.data.replace('confirm_buy_pet_', '')
    if pet_type_key not in PET_TYPES:
        bot.answer_callback_query(call.id, "Неизвестный тип питомца.")
        return

    # Списываем стоимость
    db.update_user_balance(user_telegram_id, -NEW_PET_COST)
    updated_balance = db.get_user(user_telegram_id)['balance']

    # Создаем нового питомца
    pet_name = PET_TYPES[pet_type_key]['name']
    new_pet = db.create_pet(user['id'], pet_type_key, pet_name)

    bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                          text=f"Поздравляем! Вы купили нового питомца: *{pet_name}* за {NEW_PET_COST} Tamacoin! Ваш баланс: *{updated_balance} Tamacoin*.",
                          parse_mode='Markdown', reply_markup=None)
    
    # Отправляем первое сообщение о состоянии нового питомца
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

    bot.answer_callback_query(call.id, "Питомец куплен!")


# --- Административные команды ---
@bot.message_handler(commands=['admin_stats'])
def admin_stats(message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        bot.send_message(message.chat.id, "У вас нет прав для этой команды.")
        return
    
    total_users = db.get_total_users()
    total_pets_alive = db.get_total_users_with_pets()
    total_tamacoin_distributed = db.get_total_tamacoin_distributed()
    
    stats_text = (
        f"*Статистика системы Tamacoin Game:*\n\n"
        f"Всего зарегистрировано пользователей: *{total_users}*\n"
        f"Живых питомцев: *{total_pets_alive}*\n"
        f"Распределено Tamacoin: *{total_tamacoin_distributed} из {TOTAL_INITIAL_SUPPLY}*\n"
        f"Осталось Tamacoin для распределения: *{TOTAL_INITIAL_SUPPLY - total_tamacoin_distributed}*"
    )
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')


# --- Точка входа для вебхуков Render.com ---
@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        # Для других типов запросов или некорректного content-type
        return '', 403 # Forbidden


if __name__ == '__main__':
    # Инициализация базы данных при запуске
    db.init_db()
    
    # Запуск Flask-сервера
    # Render.com предоставляет порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

