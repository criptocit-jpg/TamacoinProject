# main.py

import os
import sys # ЭТОТ ИМПОРТ ДОЛЖЕН БЫТЬ ЗДЕСЬ, В САМОМ НАЧАЛЕ СПИСКА ИМПОРТОВ
import telebot
from telebot import types
import datetime
import math
from flask import Flask, request

# Теперь вы можете разместить свою уникальную метку после всех импортов
sys.stderr.write("##### VERIFICATION_MARKER_001: main.py started execution at " + str(datetime.datetime.now()) + " #####\n")

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

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{API_TOKEN}"

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

def get_pet_status_and_image(pet):
    sys.stderr.write(f"DEBUG_HELPER: get_pet_status_and_image called for pet {pet['id']}.\n")
    image_key = pet['pet_type'] + '_normal'
    status_text = f"Голод: {pet['hunger']:.1f}%\n" \
                  f"Счастье: {pet['happiness']:.1f}%\n" \
                  f"Здоровie: {pet['health']:.1f}%"

    if pet['is_alive'] == 0:
        image_key = 'dead_pet'
        status_text = "Ваш питомец мертв. 😢"
    elif pet['hunger'] < HUNGER_THRESHOLD_SAD:
        image_key = pet['pet_type'] + '_hungry'
        status_text += "\n*Питомец голоден!*"

    image_path = PET_IMAGES.get(image_key, PET_IMAGES.get(pet['pet_type'] + '_normal', 'dead_pet'))
    sys.stderr.write(f"DEBUG_HELPER: Image path determined: {image_path} for key {image_key}.\n")
    return status_text, image_path

def update_pet_stats_over_time(pet):
    sys.stderr.write(f"DEBUG_HELPER: update_pet_stats_over_time called for pet {pet['id']}.\n")
    if pet['is_alive'] == 0:
        sys.stderr.write(f"DEBUG_HELPER: Pet {pet['id']} is dead, no state update needed.\n")
        return pet

    last_update_time_str = pet.get('last_state_update')
    if not last_update_time_str:
        sys.stderr.write(f"DEBUG_HELPER: last_state_update missing for pet {pet['id']}, initializing.\n")
        db.update_pet_state(pet['owner_id'], pet['hunger'], pet['happiness'], pet['health'], datetime.datetime.now(datetime.timezone.utc).isoformat())
        pet = db.get_pet(pet['owner_id'])
        last_update_time_str = pet['last_state_update']

    try:
        last_update_time = datetime.datetime.fromisoformat(last_update_time_str)
    except ValueError:
        sys.stderr.write(f"ERROR_HELPER: Invalid last_state_update format '{last_update_time_str}' for pet {pet['id']}. Using current time.\n")
        last_update_time = datetime.datetime.now(datetime.timezone.utc)
        db.update_pet_state(pet['owner_id'], pet['hunger'], pet['happiness'], pet['health'], last_update_time.isoformat())
        pet = db.get_pet(pet['owner_id'])

    current_time = datetime.datetime.now(datetime.timezone.utc)
    time_elapsed = (current_time - last_update_time).total_seconds() / 3600

    if time_elapsed <= 0:
        sys.stderr.write(f"DEBUG_HELPER: No significant time elapsed ({time_elapsed:.2f}h) for pet {pet['id']}.\n")
        return pet

    sys.stderr.write(f"DEBUG_HELPER: Time elapsed for pet {pet['id']}: {time_elapsed:.2f} hours.\n")

    new_hunger = max(0.0, pet['hunger'] - (HUNGER_DECAY_PER_HOUR * time_elapsed))
    new_happiness = max(0.0, pet['happiness'] - (HAPPINESS_DECAY_PER_HOUR * time_elapsed))

    health_decay_multiplier = 1.0
    if new_hunger < HUNGER_THRESHOLD_SAD:
        health_decay_multiplier += 0.5
        sys.stderr.write(f"DEBUG_HELPER: Hunger below threshold for pet {pet['id']}, increasing health decay.\n")
    if new_happiness < HAPPINESS_THRESHOLD_SAD:
        health_decay_multiplier += 0.5
        sys.stderr.write(f"DEBUG_HELPER: Happiness below threshold for pet {pet['id']}, increasing health decay.\n")

    new_health = max(0.0, pet['health'] - (HEALTH_DECAY_PER_HOUR * time_elapsed * health_decay_multiplier))

    if new_hunger <= 0 or new_happiness <= 0 or new_health <= 0:
        db.kill_pet(pet['owner_id'])
        pet['is_alive'] = 0
        pet['hunger'] = 0.0
        pet['happiness'] = 0.0
        pet['health'] = 0.0
        sys.stderr.write(f"DEBUG_PET_STATE: Pet {pet['name']} (owner {pet['owner_id']}) has died due to low stats.\n")
    else:
        db.update_pet_state(pet['owner_id'], new_hunger, new_happiness, new_health, current_time.isoformat())
        pet['hunger'] = new_hunger
        pet['happiness'] = new_happiness
        pet['health'] = new_health
        sys.stderr.write(f"DEBUG_PET_STATE: Pet {pet['name']} (owner {pet['owner_id']}) state updated to H:{new_hunger:.1f}, P:{new_happiness:.1f}, L:{new_health:.1f}.\n")

    return pet

@bot.callback_query_handler(func=lambda call: True)
def debug_all_callbacks(call):
    sys.stderr.write(f"DEBUG_ALL_CALLBACKS: Received callback_data: '{call.data}' from user {call.from_user.id}\n")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    sys.stderr.write(f"DEBUG: /start command received from user {message.from_user.id}\n")
    user_telegram_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else f"id{user_telegram_id}"
    chat_id = message.chat.id

    try:
        user = db.get_user(user_telegram_id)
        if not user:
            sys.stderr.write(f"DEBUG: User {user_telegram_id} not found, creating new user.\n")
            user = db.create_user(user_telegram_id, username)
            if not user:
                bot.send_message(chat_id, "Извините, не удалось создать вашу учетную запись. Пожалуйста, попробуйте еще раз.")
                sys.stderr.write(f"ERROR: Failed to create user for telegram_id {user_telegram_id}.\n")
                return

            bot.send_message(chat_id, "Добро пожаловать в Tamacoin Game! Выберите своего первого питомца:")

            markup = types.InlineKeyboardMarkup()
            for pet_type_key, pet_info in PET_TYPES.items():
                markup.add(types.InlineKeyboardButton(text=pet_info['name'], callback_data=f"choose_pet_{pet_type_key}"))
            bot.send_message(chat_id, "Кого вы хотите завести?", reply_markup=markup)
            sys.stderr.write("DEBUG: Sent pet selection message to new user.\n")
        else:
            sys.stderr.write(f"DEBUG: User {user_telegram_id} already exists. Checking for pet.\n")
            pet = db.get_pet(user['id'])
            if pet:
                sys.stderr.write(f"DEBUG: User {user_telegram_id} has pet {pet['id']}. Updating pet stats over time.\n")
                pet = update_pet_stats_over_time(pet)
                
                status_text, image_path = get_pet_status_and_image(pet)
                
                if pet['is_alive'] == 0:
                    bot.send_message(chat_id, f"Привет снова, {user['username']}! Ваш баланс: {user['balance']} Tamacoin.")
                    bot.send_message(chat_id, f"Ваш питомец {pet['name']} мертв. 😢\n"
                                               f"Вы можете приобрести нового питомца за {NEW_PET_COST} Tamacoin, используя команду /new_pet (если она у вас есть) или нажав /start еще раз.")
                    try:
                        with open(PET_IMAGES['dead_pet'], 'rb') as photo:
                            bot.send_photo(chat_id, photo, caption="Покойся с миром, друг.")
                        sys.stderr.write(f"DEBUG: Sent dead pet photo for user {user_telegram_id}.\n")
                    except FileNotFoundError:
                        bot.send_message(chat_id, "Изображение могилы не найдено.")
                        sys.stderr.write(f"ERROR: Image not found at {PET_IMAGES['dead_pet']} for user {user_telegram_id}.\n")
                    except Exception as e:
                        bot.send_message(chat_id, f"Произошла ошибка при отправке фото. Ваш статус:\n{status_text}")
                        sys.stderr.write(f"ERROR: Failed to send dead pet photo for user {user_telegram_id}: {e}\n")
                        import traceback
                        sys.stderr.write(traceback.format_exc())

                    return

                bot.send_message(chat_id, f"Привет снова, {user['username']}! Ваш баланс: {user['balance']} Tamacoin.")
                
                try:
                    with open(image_path, 'rb') as photo:
                        bot.send_photo(chat_id, photo, caption=status_text)
                    sys.stderr.write(f"DEBUG: Sent pet status photo for existing user {user_telegram_id}.\n")
                except FileNotFoundError:
                    bot.send_message(chat_id, f"Ой, не могу найти изображение для питомца. Ваш статус:\n{status_text}")
                    sys.stderr.write(f"ERROR: Image not found at {image_path} for user {user_telegram_id}.\n")
                except Exception as e:
                    bot.send_message(chat_id, f"Произошла ошибка при отправке фото. Ваш статус:\n{status_text}")
                    sys.stderr.write(f"ERROR: Failed to send photo for user {user_telegram_id}: {e}\n")
                    import traceback
                    sys.stderr.write(traceback.format_exc())

            else:
                sys.stderr.write(f"DEBUG: User {user_telegram_id} exists but has no pet. Prompting for selection.\n")
                bot.send_message(chat_id, "Добро пожаловать обратно! Вы еще не выбрали питомца. Выберите одного:")
                markup = types.InlineKeyboardMarkup()
                for pet_type_key, pet_info in PET_TYPES.items():
                    markup.add(types.InlineKeyboardButton(text=pet_info['name'], callback_data=f"choose_pet_{pet_type_key}"))
                bot.send_message(chat_id, "Кого вы хотите завести?", reply_markup=markup)
                sys.stderr.write("DEBUG: Sent pet selection message to existing user without pet.\n")
    except Exception as e:
        sys.stderr.write(f"ERROR: Unhandled exception in send_welcome for user {user_telegram_id}: {e}\n")
        import traceback
        sys.stderr.write(traceback.format_exc())
        bot.send_message(chat_id, "Произошла непредвиденная ошибка при обработке команды /start. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('choose_pet_'))
def callback_choose_pet(call):
    sys.stderr.write(f"DEBUG: callback_choose_pet called for user {call.from_user.id} with data '{call.data}'\n")
    chat_id = call.message.chat.id
    user_telegram_id = call.from_user.id
    message_id = call.message.message_id
    
    try:
        user = db.get_user(user_telegram_id)
        if not user:
            sys.stderr.write(f"ERROR: User {user_telegram_id} not found in DB during callback_choose_pet. This shouldn't happen after /start. Creating user.\n")
            username = call.from_user.username if call.from_user.username else f"id{user_telegram_id}"
            user = db.create_user(user_telegram_id, username)
            if not user:
                bot.answer_callback_query(call.id, "Не удалось создать пользователя. Попробуйте еще раз.")
                sys.stderr.write(f"ERROR: Failed to create user {user_telegram_id} even after retry in callback_choose_pet.\n")
                return

        if user['pet_id']:
            bot.answer_callback_query(call.id, "У вас уже есть питомец!")
            bot.send_message(chat_id, "У вас уже есть питомец. Для получения информации используйте /status.")
            sys.stderr.write(f"DEBUG: User {user_telegram_id} already has a pet, callback handled.\n")
            return

        pet_type_key = call.data.replace('choose_pet_', '')
        if pet_type_key not in PET_TYPES:
            bot.answer_callback_query(call.id, "Неизвестный тип питомца.")
            sys.stderr.write(f"ERROR: Unknown pet type key received: {pet_type_key} from user {user_telegram_id}.\n")
            return

        pet_info = PET_TYPES[pet_type_key]
        pet_name = pet_info['name']
        
        owner_db_id = user['id'] 
        sys.stderr.write(f"DEBUG: Creating pet for owner_db_id: {owner_db_id} with type {pet_type_key}.\n")
        new_pet = db.create_pet(owner_db_id, pet_type_key, pet_name)

        if new_pet:
            bot.answer_callback_query(call.id, f"Вы выбрали {pet_name}!")
            status_text, image_path = get_pet_status_and_image(new_pet)
            
            try:
                with open(image_path, 'rb') as photo:
                    bot.send_photo(chat_id, photo, caption=f"Поздравляем, вы завели {pet_name}!\n\n{status_text}")
                sys.stderr.write(f"DEBUG: Sent new pet photo to user {user_telegram_id}.\n")
            except FileNotFoundError:
                bot.send_message(chat_id, f"Поздравляем, вы завели {pet_name}!\n\nОй, не могу найти изображение для питомца. Ваш статус:\n{status_text}")
                sys.stderr.write(f"ERROR: Image not found at {image_path} for new pet of user {user_telegram_id}.\n")
            except Exception as e:
                bot.send_message(chat_id, f"Поздравляем, вы завели {pet_name}!\n\nПроизошла ошибка при отправке фото. Ваш статус:\n{status_text}")
                sys.stderr.write(f"ERROR: Failed to send new pet photo for user {user_telegram_id}: {e}\n")
                import traceback
                sys.stderr.write(traceback.format_exc())

            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None) 
                sys.stderr.write(f"DEBUG: Pet selection buttons removed for user {user_telegram_id}.\n")
            except Exception as e:
                sys.stderr.write(f"ERROR: Failed to edit message reply markup for user {user_telegram_id}: {e}\n")
                pass

            bot.send_message(chat_id, "Теперь вы можете ухаживать за своим питомцем, используя команды, такие как /feed, /play, /clean и т.д.")
        else:
            bot.answer_callback_query(call.id, "Не удалось создать питомца.")
            sys.stderr.write(f"ERROR: Failed to create pet for user {user_telegram_id} for unknown reason.\n")

    except Exception as e:
        sys.stderr.write(f"ERROR: Unhandled exception in callback_choose_pet for user {call.from_user.id}: {e}\n")
        import traceback
        sys.stderr.write(traceback.format_exc())
        bot.answer_callback_query(call.id, "Произошла внутренняя ошибка.")
        bot.send_message(chat_id, "Произошла непредвиденная ошибка. Попробуйте позже.")

@bot.message_handler(commands=['info'])
def send_info(message):
    sys.stderr.write(f"DEBUG: /info command received from user {message.from_user.id}\n")
    bot.send_message(message.chat.id, INFO_TEXT, parse_mode='Markdown')
    sys.stderr.write("DEBUG: Sent INFO_TEXT.\n")

@bot.message_handler(commands=['help'])
def send_help(message):
    sys.stderr.write(f"DEBUG: /help command received from user {message.from_user.id}\n")
    bot.send_message(message.chat.id, HELP_TEXT, parse_mode='Markdown')
    sys.stderr.write("DEBUG: Sent HELP_TEXT.\n")

@bot.message_handler(commands=['status'])
def send_status(message):
    sys.stderr.write(f"DEBUG: /status command received from user {message.from_user.id}\n")
    user_telegram_id = message.from_user.id
    chat_id = message.chat.id

    try:
        user = db.get_user(user_telegram_id)
        if not user:
            bot.send_message(chat_id, "Вы еще не начали игру! Используйте команду /start.")
            sys.stderr.write(f"DEBUG: User {user_telegram_id} not found for /status.\n")
            return

        pet = db.get_pet(user['id'])
        if not pet:
            bot.send_message(chat_id, "У вас еще нет питомца! Выберите его, используя команду /start.")
            sys.stderr.write(f"DEBUG: User {user_telegram_id} has no pet for /status.\n")
            return

        pet = update_pet_stats_over_time(pet)

        status_text, image_path = get_pet_status_and_image(pet)
        user_balance_text = f"Ваш баланс: {user['balance']} Tamacoin."

        try:
            with open(image_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=f"{user_balance_text}\n\n{status_text}")
            sys.stderr.write(f"DEBUG: Sent pet status photo for user {user_telegram_id} via /status.\n")
        except FileNotFoundError:
            bot.send_message(chat_id, f"{user_balance_text}\n\nОй, не могу найти изображение для питомца. Ваш статус:\n{status_text}")
            sys.stderr.write(f"ERROR: Image not found at {image_path} for user {user_telegram_id} via /status.\n")
        except Exception as e:
            bot.send_message(chat_id, f"{user_balance_text}\n\nПроизошла ошибка при отправке фото. Ваш статус:\n{status_text}")
            sys.stderr.write(f"ERROR: Failed to send photo for user {user_telegram_id} via /status: {e}\n")
            import traceback
            sys.stderr.write(traceback.format_exc())

    except Exception as e:
        sys.stderr.write(f"ERROR: Unhandled exception in send_status for user {user_telegram_id}: {e}\n")
        import traceback
        sys.stderr.write(traceback.format_exc())
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


@app.route(f'/{API_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        sys.stderr.write(f"DEBUG_WEBHOOK: Received webhook update: {json_string[:200]}...\n")
        try:
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            sys.stderr.write("DEBUG_WEBHOOK: Successfully processed update.\n")
            return '', 200
        except Exception as e:
            sys.stderr.write(f"ERROR_WEBHOOK: Error processing update: {e}\n")
            import traceback
            sys.stderr.write(traceback.format_exc())
            return '', 500
    else:
        sys.stderr.write("ERROR_WEBHOOK: Webhook received non-JSON content. Content-Type: " + request.headers.get('content-type') + "\n")
        return '', 403

if __name__ == '__main__':
    if API_TOKEN and WEBHOOK_HOST:
        sys.stderr.write("DEBUG: API_TOKEN and WEBHOOK_HOST are set. Attempting to set webhook.\n")
        try:
            bot.remove_webhook()
            sys.stderr.write("DEBUG: Old webhook removed (if any).\n")
            bot.set_webhook(url=WEBHOOK_URL)
            sys.stderr.write(f"DEBUG: Webhook set to {WEBHOOK_URL}\n")
            sys.stderr.write("DEBUG: Starting Flask app.run on 0.0.0.0:PORT.\n")
            app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
        except Exception as e:
            sys.stderr.write(f"FATAL_ERROR: Failed to set webhook or start Flask app: {e}\n")
            import traceback
            sys.stderr.write(traceback.format_exc())
    else:
        sys.stderr.write("ERROR: API_TOKEN or WEBHOOK_HOST environment variable not set.\n")
        sys.stderr.write("Bot will not run via webhook on Render.com.\n")
        sys.stderr.write("For local testing, consider uncommenting bot.polling(none_stop=True).\n")

