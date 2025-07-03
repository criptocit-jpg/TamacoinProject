# main.py

# ====================================================================
# ЭТА СТРОКА ДОЛЖНА БЫТЬ САМОЙ ПЕРВОЙ В ФАЙЛЕ, ПЕРЕД ВСЕМИ ИМПОРТАМИ
print("!!!!! DEBUG_MAIN: main.py started execution !!!!!")
# ====================================================================

import os
import telebot
from telebot import types
import datetime
import math
from flask import Flask, request # Import Flask and request for webhook

# Убедитесь, что db_manager.py и pet_config.py находятся в той же директории
# и содержат необходимые переменные/классы
from db_manager import db
from pet_config import (
    PET_TYPES, PET_IMAGES, INITIAL_TAMACIONS_BALANCE, WELCOME_BONUS_AMOUNT,
    WELCOME_BONUS_ACTIONS_REQUIRED, DAILY_BONUS_AMOUNT,
    DAILY_BONUS_INTERVAL_HOURS, FOOD_COST, MEDICINE_COST, NEW_PET_COST,
    FEED_REWARD, PLAY_REWARD, CLEAN_REWARD, ACTION_COOLDOWN_HOURS,
    HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR, HEALTH_DECAY_PER_HOUR,
    HUNGER_THRESHOLD_SAD, HAPPINESS_THRESHOLD_SAD, HEALTH_THRESHOLD_SICK,
    TOTAL_INITIAL_SUPPLY, ADMIN_TELEGRAM_ID, INFO_TEXT, HELP_TEXT
)

# Настройка Telegram бота
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") # Например, ваш_домен.onrender.com
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{API_TOKEN}"

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__) # Инициализация Flask приложения

# --- Вспомогательные функции ---
# Эти функции могут быть перенесены в отдельный модуль для лучшей организации
# но для отладки пока оставим их здесь.

def get_pet_status_and_image(pet):
    """
    Определяет текущее состояние питомца и соответствующее изображение.
    На основе логики из pet_config и текущих параметров питомца.
    """
    print(f"DEBUG_HELPER: get_pet_status_and_image called for pet {pet['id']}.")
    image_key = pet['pet_type'] + '_normal' # По умолчанию нормальное изображение
    status_text = f"Голод: {pet['hunger']:.1f}%\n" \
                  f"Счастье: {pet['happiness']:.1f}%\n" \
                  f"Здоровье: {pet['health']:.1f}%"

    if pet['is_alive'] == 0:
        image_key = 'dead_pet'
        status_text = "Ваш питомец мертв. 😢"
    elif pet['hunger'] < HUNGER_THRESHOLD_SAD:
        image_key = pet['pet_type'] + '_hungry'
        status_text += "\n*Питомец голоден!*"
    # Можно добавить логику для счастья, здоровья и других состояний
    # elif pet['happiness'] < HAPPINESS_THRESHOLD_SAD:
    #     image_key = pet['pet_type'] + '_sad'
    #     status_text += "\n*Питомец грустит!*"
    # elif pet['health'] < HEALTH_THRESHOLD_SICK:
    #     image_key = pet['pet_type'] + '_sick'
    #     status_text += "\n*Питомец болен!*"

    # Убедитесь, что PET_IMAGES содержит соответствующий ключ, иначе верните 'normal' или 'dead_pet'
    image_path = PET_IMAGES.get(image_key, PET_IMAGES.get(pet['pet_type'] + '_normal', 'dead_pet'))
    print(f"DEBUG_HELPER: Image path determined: {image_path} for key {image_key}.")
    return status_text, image_path

def update_pet_stats_over_time(pet):
    """
    Обновляет состояние питомца на основе прошедшего времени.
    """
    print(f"DEBUG_HELPER: update_pet_stats_over_time called for pet {pet['id']}.")
    if pet['is_alive'] == 0:
        print(f"DEBUG_HELPER: Pet {pet['id']} is dead, no state update needed.")
        return pet # Мертвый питомец не "стареет"

    last_update_time_str = pet.get('last_state_update')
    if not last_update_time_str:
        # Если last_state_update отсутствует (например, новый питомец), инициализируем его текущим временем
        print(f"DEBUG_HELPER: last_state_update missing for pet {pet['id']}, initializing.")
        db.update_pet_state(pet['owner_id'], pet['hunger'], pet['happiness'], pet['health'], datetime.datetime.now(datetime.timezone.utc).isoformat())
        pet = db.get_pet(pet['owner_id']) # Перезагрузим данные питомца
        last_update_time_str = pet['last_state_update'] # Теперь должно быть

    try:
        last_update_time = datetime.datetime.fromisoformat(last_update_time_str)
    except ValueError:
        print(f"ERROR_HELPER: Invalid last_state_update format '{last_update_time_str}' for pet {pet['id']}. Using current time.")
        last_update_time = datetime.datetime.now(datetime.timezone.utc)
        db.update_pet_state(pet['owner_id'], pet['hunger'], pet['happiness'], pet['health'], last_update_time.isoformat())
        pet = db.get_pet(pet['owner_id']) # Перезагрузим данные питомца


    current_time = datetime.datetime.now(datetime.timezone.utc)
    time_elapsed = (current_time - last_update_time).total_seconds() / 3600 # Часы

    if time_elapsed <= 0:
        print(f"DEBUG_HELPER: No significant time elapsed ({time_elapsed:.2f}h) for pet {pet['id']}.")
        return pet # Нет прошедшего времени, не обновляем

    print(f"DEBUG_HELPER: Time elapsed for pet {pet['id']}: {time_elapsed:.2f} hours.")

    # Расчет уменьшения параметров
    new_hunger = max(0.0, pet['hunger'] - (HUNGER_DECAY_PER_HOUR * time_elapsed))
    new_happiness = max(0.0, pet['happiness'] - (HAPPINESS_DECAY_PER_HOUR * time_elapsed))

    # Здоровье уменьшается медленнее, но ускоряется при низком голоде/счастье
    health_decay_multiplier = 1.0
    if new_hunger < HUNGER_THRESHOLD_SAD:
        health_decay_multiplier += 0.5 # Ускоряет потерю здоровья если голоден
        print(f"DEBUG_HELPER: Hunger below threshold for pet {pet['id']}, increasing health decay.")
    if new_happiness < HAPPINESS_THRESHOLD_SAD:
        health_decay_multiplier += 0.5 # Ускоряет потерю здоровья если несчастен
        print(f"DEBUG_HELPER: Happiness below threshold for pet {pet['id']}, increasing health decay.")

    new_health = max(0.0, pet['health'] - (HEALTH_DECAY_PER_HOUR * time_elapsed * health_decay_multiplier))

    # Проверка на смерть
    if new_hunger <= 0 or new_happiness <= 0 or new_health <= 0:
        db.kill_pet(pet['owner_id'])
        pet['is_alive'] = 0
        pet['hunger'] = 0.0
        pet['happiness'] = 0.0
        pet['health'] = 0.0
        print(f"DEBUG_PET_STATE: Pet {pet['name']} (owner {pet['owner_id']}) has died due to low stats.")
    else:
        db.update_pet_state(pet['owner_id'], new_hunger, new_happiness, new_health, current_time.isoformat())
        pet['hunger'] = new_hunger
        pet['happiness'] = new_happiness
        pet['health'] = new_health
        print(f"DEBUG_PET_STATE: Pet {pet['name']} (owner {pet['owner_id']}) state updated to H:{new_hunger:.1f}, P:{new_happiness:.1f}, L:{new_health:.1f}.")

    return pet

# --- Обработчики Telegram бота ---

# --- Временный общий обработчик колбэков для отладки ---
# Этот обработчик должен быть СТРОГО ПЕРЕД более специфичными обработчиками
# например, перед @bot.callback_query_handler(func=lambda call: call.data.startswith('choose_pet_'))
@bot.callback_query_handler(func=lambda call: True)
def debug_all_callbacks(call):
    print(f"DEBUG_ALL_CALLBACKS: Received callback_data: '{call.data}' from user {call.from_user.id}")
    # Важно: НЕ вызывайте bot.answer_callback_query здесь, чтобы не перехватывать ее у других обработчиков
    # Этот обработчик должен быть временным и удален после отладки.

# --- Обработчик команды /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    print(f"DEBUG: /start command received from user {message.from_user.id}")
    user_telegram_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else f"id{user_telegram_id}"
    chat_id = message.chat.id

    try:
        user = db.get_user(user_telegram_id)
        if not user:
            print(f"DEBUG: User {user_telegram_id} not found, creating new user.")
            user = db.create_user(user_telegram_id, username)
            if not user: # Повторная проверка, если create_user вернул None
                bot.send_message(chat_id, "Извините, не удалось создать вашу учетную запись. Пожалуйста, попробуйте еще раз.")
                print(f"ERROR: Failed to create user for telegram_id {user_telegram_id}.")
                return

            bot.send_message(chat_id, "Добро пожаловать в Tamacoin Game! Выберите своего первого питомца:")

            markup = types.InlineKeyboardMarkup()
            for pet_type_key, pet_info in PET_TYPES.items():
                markup.add(types.InlineKeyboardButton(text=pet_info['name'], callback_data=f"choose_pet_{pet_type_key}"))
            bot.send_message(chat_id, "Кого вы хотите завести?", reply_markup=markup)
            print("DEBUG: Sent pet selection message to new user.")
        else:
            print(f"DEBUG: User {user_telegram_id} already exists. Checking for pet.")
            # User exists, check if they have a pet
            pet = db.get_pet(user['id'])
            if pet:
                # Update pet state before showing status
                print(f"DEBUG: User {user_telegram_id} has pet {pet['id']}. Updating pet stats over time.")
                pet = update_pet_stats_over_time(pet)
                
                status_text, image_path = get_pet_status_and_image(pet)
                
                # Check if pet is dead
                if pet['is_alive'] == 0:
                    bot.send_message(chat_id, f"Привет снова, {user['username']}! Ваш баланс: {user['balance']} Tamacoin.")
                    bot.send_message(chat_id, f"Ваш питомец {pet['name']} мертв. 😢\n"
                                               f"Вы можете приобрести нового питомца за {NEW_PET_COST} Tamacoin, используя команду /new_pet (если она у вас есть) или нажав /start еще раз.")
                    try:
                        with open(PET_IMAGES['dead_pet'], 'rb') as photo:
                            bot.send_photo(chat_id, photo, caption="Покойся с миром, друг.")
                        print(f"DEBUG: Sent dead pet photo for user {user_telegram_id}.")
                    except FileNotFoundError:
                        bot.send_message(chat_id, "Изображение могилы не найдено.")
                        print(f"ERROR: Image not found at {PET_IMAGES['dead_pet']} for user {user_telegram_id}.")
                    except Exception as e:
                        bot.send_message(chat_id, f"Произошла ошибка при отправке фото. Ваш статус:\n{status_text}")
                        print(f"ERROR: Failed to send dead pet photo for user {user_telegram_id}: {e}")
                        import traceback
                        traceback.print_exc()

                    return # Завершаем выполнение, если питомец мертв

                bot.send_message(chat_id, f"Привет снова, {user['username']}! Ваш баланс: {user['balance']} Tamacoin.")
                
                try:
                    with open(image_path, 'rb') as photo:
                        bot.send_photo(chat_id, photo, caption=status_text)
                    print(f"DEBUG: Sent pet status photo for existing user {user_telegram_id}.")
                except FileNotFoundError:
                    bot.send_message(chat_id, f"Ой, не могу найти изображение для питомца. Ваш статус:\n{status_text}")
                    print(f"ERROR: Image not found at {image_path} for user {user_telegram_id}.")
                except Exception as e:
                    bot.send_message(chat_id, f"Произошла ошибка при отправке фото. Ваш статус:\n{status_text}")
                    print(f"ERROR: Failed to send photo for user {user_telegram_id}: {e}")
                    import traceback
                    traceback.print_exc()

                # Здесь можно добавить кнопки для действий с питомцем (Feed, Play, Clean)
                # markup_actions = types.InlineKeyboardMarkup()
                # markup_actions.add(types.InlineKeyboardButton("Кормить", callback_data="feed_pet"))
                # markup_actions.add(types.InlineKeyboardButton("Играть", callback_data="play_pet"))
                # markup_actions.add(types.InlineKeyboardButton("Убрать", callback_data="clean_pet"))
                # bot.send_message(chat_id, "Что будем делать с питомцем?", reply_markup=markup_actions)

            else:
                print(f"DEBUG: User {user_telegram_id} exists but has no pet. Prompting for selection.")
                bot.send_message(chat_id, "Добро пожаловать обратно! Вы еще не выбрали питомца. Выберите одного:")
                markup = types.InlineKeyboardMarkup()
                for pet_type_key, pet_info in PET_TYPES.items():
                    markup.add(types.InlineKeyboardButton(text=pet_info['name'], callback_data=f"choose_pet_{pet_type_key}"))
                bot.send_message(chat_id, "Кого вы хотите завести?", reply_markup=markup)
                print("DEBUG: Sent pet selection message to existing user without pet.")
    except Exception as e:
        print(f"ERROR: Unhandled exception in send_welcome for user {user_telegram_id}: {e}")
        import traceback
        traceback.print_exc()
        bot.send_message(chat_id, "Произошла непредвиденная ошибка при обработке команды /start. Пожалуйста, попробуйте позже.")


# --- Обработчик инлайн-кнопок для выбора питомца ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('choose_pet_'))
def callback_choose_pet(call):
    print(f"DEBUG: callback_choose_pet called for user {call.from_user.id} with data '{call.data}'")
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id
    
    try:
        user = db.get_user(user_telegram_id)
        if not user:
            print(f"ERROR: User {user_telegram_id} not found in DB during callback_choose_pet. This shouldn't happen after /start. Creating user.")
            username = call.from_user.username if call.from_user.username else f"id{user_telegram_id}"
            user = db.create_user(user_telegram_id, username)
            if not user:
                bot.answer_callback_query(call.id, "Не удалось создать пользователя. Попробуйте еще раз.")
                print(f"ERROR: Failed to create user {user_telegram_id} even after retry in callback_choose_pet.")
                return

        if user['pet_id']:
            bot.answer_callback_query(call.id, "У вас уже есть питомец!")
            bot.send_message(chat_id, "У вас уже есть питомец. Для получения информации используйте /status.")
            print(f"DEBUG: User {user_telegram_id} already has a pet, callback handled.")
            return

        pet_type_key = call.data.replace('choose_pet_', '')
        if pet_type_key not in PET_TYPES:
            bot.answer_callback_query(call.id, "Неизвестный тип питомца.")
            print(f"ERROR: Unknown pet type key received: {pet_type_key} from user {user_telegram_id}.")
            return

        pet_info = PET_TYPES[pet_type_key]
        pet_name = pet_info['name'] # Или можно предложить пользователю ввести имя
        
        # owner_id в таблице pets - это id из таблицы users (PRIMARY KEY)
        # Получаем user['id'] из user-объекта, возвращенного db.get_user
        owner_db_id = user['id'] 
        print(f"DEBUG: Creating pet for owner_db_id: {owner_db_id} with type {pet_type_key}.")
        new_pet = db.create_pet(owner_db_id, pet_type_key, pet_name)

        if new_pet:
            bot.answer_callback_query(call.id, f"Вы выбрали {pet_name}!")
            status_text, image_path = get_pet_status_and_image(new_pet)
            
            try:
                # Отправляем фото
                with open(image_path, 'rb') as photo:
                    bot.send_photo(chat_id, photo, caption=f"Поздравляем, вы завели {pet_name}!\n\n{status_text}")
                print(f"DEBUG: Sent new pet photo to user {user_telegram_id}.")
            except FileNotFoundError:
                bot.send_message(chat_id, f"Поздравляем, вы завели {pet_name}!\n\nОй, не могу найти изображение для питомца. Ваш статус:\n{status_text}")
                print(f"ERROR: Image not found at {image_path} for new pet of user {user_telegram_id}.")
            except Exception as e:
                bot.send_message(chat_id, f"Поздравляем, вы завели {pet_name}!\n\nПроизошла ошибка при отправке фото. Ваш статус:\n{status_text}")
                print(f"ERROR: Failed to send new pet photo for user {user_telegram_id}: {e}")
                import traceback
                traceback.print_exc()

            # Удаляем кнопки выбора питомца после выбора
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None) 
                print(f"DEBUG: Pet selection buttons removed for user {user_telegram_id}.")
            except Exception as e:
                print(f"ERROR: Failed to edit message reply markup for user {user_telegram_id}: {e}")
                # Это не критическая ошибка, но стоит отметить
                pass

            bot.send_message(chat_id, "Теперь вы можете ухаживать за своим питомцем, используя команды, такие как /feed, /play, /clean и т.д.")
        else:
            bot.answer_callback_query(call.id, "Не удалось создать питомца.")
            print(f"ERROR: Failed to create pet for user {user_telegram_id} for unknown reason.")

    except Exception as e:
        print(f"ERROR: Unhandled exception in callback_choose_pet for user {call.from_user.id}: {e}")
        import traceback
        traceback.print_exc()
        bot.answer_callback_query(call.id, "Произошла внутренняя ошибка.")
        bot.send_message(chat_id, "Произошла непредвиденная ошибка. Попробуйте позже.")

# --- Обработчик команды /info ---
@bot.message_handler(commands=['info'])
def send_info(message):
    print(f"DEBUG: /info command received from user {message.from_user.id}")
    bot.send_message(message.chat.id, INFO_TEXT, parse_mode='Markdown')
    print("DEBUG: Sent INFO_TEXT.")

# --- Обработчик команды /help ---
@bot.message_handler(commands=['help'])
def send_help(message):
    print(f"DEBUG: /help command received from user {message.from_user.id}")
    bot.send_message(message.chat.id, HELP_TEXT, parse_mode='Markdown')
    print("DEBUG: Sent HELP_TEXT.")

# --- Обработчик команды /status ---
@bot.message_handler(commands=['status'])
def send_status(message):
    print(f"DEBUG: /status command received from user {message.from_user.id}")
    user_telegram_id = message.from_user.id
    chat_id = message.chat.id

    try:
        user = db.get_user(user_telegram_id)
        if not user:
            bot.send_message(chat_id, "Вы еще не начали игру! Используйте команду /start.")
            print(f"DEBUG: User {user_telegram_id} not found for /status.")
            return

        pet = db.get_pet(user['id'])
        if not pet:
            bot.send_message(chat_id, "У вас еще нет питомца! Выберите его, используя команду /start.")
            print(f"DEBUG: User {user_telegram_id} has no pet for /status.")
            return

        pet = update_pet_stats_over_time(pet) # Обновляем состояние питомца

        status_text, image_path = get_pet_status_and_image(pet)
        user_balance_text = f"Ваш баланс: {user['balance']} Tamacoin."

        try:
            with open(image_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=f"{user_balance_text}\n\n{status_text}")
            print(f"DEBUG: Sent pet status photo for user {user_telegram_id} via /status.")
        except FileNotFoundError:
            bot.send_message(chat_id, f"{user_balance_text}\n\nОй, не могу найти изображение для питомца. Ваш статус:\n{status_text}")
            print(f"ERROR: Image not found at {image_path} for user {user_telegram_id} via /status.")
        except Exception as e:
            bot.send_message(chat_id, f"{user_balance_text}\n\nПроизошла ошибка при отправке фото. Ваш статус:\n{status_text}")
            print(f"ERROR: Failed to send photo for user {user_telegram_id} via /status: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"ERROR: Unhandled exception in send_status for user {user_telegram_id}: {e}")
        import traceback
        traceback.print_exc()
        bot.send_message(chat_id, "Произошла непредвиденная ошибка при получении статуса. Пожалуйста, попробуйте позже.")

# --- Добавьте другие обработчики здесь ---
# Если у вас есть другие команды, такие как /feed, /play, /clean, /shop, /daily_bonus,
# /users_count, /admin_stats и т.д., ВСТАВЬТЕ ИХ СЮДА.
# Пример:
# @bot.message_handler(commands=['feed'])
# def feed_pet_command(message):
#     # ... ваш код для /feed ...
#     pass

# @bot.message_handler(commands=['play'])
# def play_pet_command(message):
#     # ... ваш код для /play ...
#     pass

# @bot.message_handler(commands=['clean'])
# def clean_pet_command(message):
#     # ... ваш код для /clean ...
#     pass

# @bot.message_handler(commands=['shop'])
# def open_shop(message):
#     # ... ваш код для /shop ...
#     pass

# @bot.message_handler(commands=['daily_bonus'])
# def get_daily_bonus(message):
#     # ... ваш код для /daily_bonus ...
#     pass

# @bot.message_handler(commands=['users_count'])
# def get_users_count(message):
#     # ... ваш код для /users_count ...
#     pass

# @bot.message_handler(commands=['admin_stats'])
# def admin_stats(message):
#     # ... ваш код для /admin_stats ...
#     pass


# --- Webhook setup (для Render.com) ---
@app.route(f'/{API_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        print(f"DEBUG_WEBHOOK: Received webhook update: {json_string[:200]}...") # Логируем часть данных
        try:
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            print("DEBUG_WEBHOOK: Successfully processed update.")
            return '', 200
        except Exception as e:
            print(f"ERROR_WEBHOOK: Error processing update: {e}")
            import traceback
            traceback.print_exc()
            return '', 500 # Internal Server Error
    else:
        print("ERROR_WEBHOOK: Webhook received non-JSON content. Content-Type:", request.headers.get('content-type'))
        return '', 403 # Forbidden

# --- Запуск приложения ---
if __name__ == '__main__':
    # Установка вебхука при запуске (только если WEBHOOK_HOST определен)
    if API_TOKEN and WEBHOOK_HOST:
        print("DEBUG: API_TOKEN and WEBHOOK_HOST are set. Attempting to set webhook.")
        try:
            bot.remove_webhook() # Удаляем старый вебхук на всякий случай
            print("DEBUG: Old webhook removed (if any).")
            bot.set_webhook(url=WEBHOOK_URL)
            print(f"DEBUG: Webhook set to {WEBHOOK_URL}")
            # Flask запускается на всех адресах на порту 10000, как требует Render.com
            print("DEBUG: Starting Flask app.run on 0.0.0.0:PORT.")
            app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
            print("DEBUG: Flask app.run started.") # Эта строка может не отобразиться, если app.run блокирующий вызов
        except Exception as e:
            print(f"FATAL_ERROR: Failed to set webhook or start Flask app: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("ERROR: API_TOKEN or WEBHOOK_HOST environment variable not set.")
        print("Bot will not run via webhook on Render.com.")
        print("For local testing, consider uncommenting bot.polling(none_stop=True).")
        # bot.polling(none_stop=True) # Для локального тестирования без вебхука, если нет вебхука

