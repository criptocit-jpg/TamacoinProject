# game_logic.py
import asyncio
from datetime import datetime, timedelta
import logging

import pet_config # Предполагаем, что pet_config.py существует и содержит PET_TYPES, PET_IMAGES, etc.

logger = logging.getLogger(__name__)

class PetGame:
    def __init__(self, db_manager):
        self.db_manager = db_manager # Принимаем экземпляр DBManager

    async def send_pet_status(self, chat_id, user_id):
        user = self.db_manager.get_user(user_id)
        if not user:
            # Should not happen if this is called after a user is confirmed to exist
            return
        
        pet = self.db_manager.get_pet(user[0]) # Используем внутренний ID пользователя
        
        if not pet:
            # This case is handled in main.py before calling this, but for safety
            await self.db_manager.context.bot.send_message(chat_id=chat_id, text="У вас еще нет питомца!")
            return

        pet_name = pet[3]
        pet_type = pet[2]
        health = pet[4]
        happiness = pet[5]
        hunger = pet[6]
        balance = user[5] # Баланс пользователя

        status_text = (
            f"**{pet_name} ({pet_type})**\n"
            f"Здоровье: {health}/100\n"
            f"Счастье: {happiness}/100\n"
            f"Голод: {hunger}/100\n"
            f"Баланс Tamacoin: {balance}"
        )
        await self.db_manager.context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode='Markdown')

    async def feed_pet(self, chat_id, user_id):
        pet = self.db_manager.get_pet(user_id)
        if not pet:
            await self.db_manager.context.bot.send_message(chat_id=chat_id, text="У вас еще нет питомца!")
            return

        current_hunger = pet[6]
        
        # Проверка времени с последнего кормления (опционально, можно добавить кулдаун)
        last_fed_time = pet[7]
        time_since_fed = (datetime.now() - last_fed_time).total_seconds() if last_fed_time else float('inf')

        if current_hunger <= 0:
            await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"{pet[3]} не голоден прямо сейчас.")
        # elif time_since_fed < 3600: # Пример: можно кормить раз в час
        #    await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"Вы уже кормили {pet[3]} недавно. Подождите еще {int(3600 - time_since_fed)} секунд.")
        else:
            new_hunger = max(0, current_hunger - 20) # Уменьшаем голод
            new_health = min(100, pet[4] + 5) # Немного улучшаем здоровье
            new_happiness = min(100, pet[5] + 5) # Немного улучшаем счастье

            self.db_manager.update_pet_stats(
                pet[0], # pet_id
                health=new_health,
                happiness=new_happiness,
                hunger=new_hunger,
                last_fed=datetime.now(),
                last_interacted=datetime.now()
            )
            await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"Вы покормили {pet[3]}! Голод уменьшился, здоровье и счастье немного улучшились.")
            await self.send_pet_status(chat_id, user_id)

    async def play_with_pet(self, chat_id, user_id):
        pet = self.db_manager.get_pet(user_id)
        if not pet:
            await self.db_manager.context.bot.send_message(chat_id=chat_id, text="У вас еще нет питомца!")
            return

        # Проверка времени с последней игры (опционально, можно добавить кулдаун)
        last_played_time = pet[8]
        time_since_played = (datetime.now() - last_played_time).total_seconds() if last_played_time else float('inf')

        # if time_since_played < 1800: # Пример: можно играть раз в 30 минут
        #    await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"Вы уже играли с {pet[3]} недавно. Подождите еще {int(1800 - time_since_played)} секунд.")
        #    return

        new_happiness = min(100, pet[5] + 20) # Увеличиваем счастье
        new_hunger = min(100, pet[6] + 10) # Увеличиваем голод от активности
        
        self.db_manager.update_pet_stats(
            pet[0], # pet_id
            happiness=new_happiness,
            hunger=new_hunger,
            last_played=datetime.now(),
            last_interacted=datetime.now()
        )
        await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"Вы поиграли с {pet[3]}! Счастье увеличилось, но он немного проголодался.")
        await self.send_pet_status(chat_id, user_id)

    async def clean_pet_area(self, chat_id, user_id):
        pet = self.db_manager.get_pet(user_id)
        if not pet:
            await self.db_manager.context.bot.send_message(chat_id=chat_id, text="У вас еще нет питомца!")
            return

        # Проверка времени с последней уборки (опционально, можно добавить кулдаун)
        last_cleaned_time = pet[9]
        time_since_cleaned = (datetime.now() - last_cleaned_time).total_seconds() if last_cleaned_time else float('inf')

        # if time_since_cleaned < 7200: # Пример: убирать раз в 2 часа
        #    await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"Вы уже убирали за {pet[3]} недавно. Подождите еще {int(7200 - time_since_cleaned)} секунд.")
        #    return
            
        new_health = min(100, pet[4] + 10) # Улучшаем здоровье
        new_happiness = min(100, pet[5] + 5) # Немного улучшаем счастье

        self.db_manager.update_pet_stats(
            pet[0], # pet_id
            health=new_health,
            happiness=new_happiness,
            last_cleaned=datetime.now(),
            last_interacted=datetime.now()
        )
        await self.db_manager.context.bot.send_message(chat_id=chat_id, text=f"Вы убрали за {pet[3]}! Его здоровье и счастье улучшились.")
        await self.send_pet_status(chat_id, user_id)

    # Здесь будут добавляться другие функции игровой логики
    # Например, проверка состояния питомца со временем, ежедневные бонусы и т.д.
    # Это потребует фоновых задач или периодических проверок.

    # Важно: для работы PetGame, как сейчас, нужно передать context.bot
    # в send_pet_status. Простейший способ это сделать, если bot
    # является частью Application, это передать ссылку на Application.
    # Сейчас в DBManager нет ссылки на context.bot.
    # Исправим это, чтобы send_pet_status мог отправлять сообщения.
    # В main.py Application.builder().token(TOKEN).build() создает объект 'application'.
    # Мы можем передать его в PetGame, чтобы PetGame имел доступ к application.bot.

    # Временно (для отладки)
    # Если context.bot не доступен напрямую в game_logic,
    # придется передавать его в каждую функцию, которая отправляет сообщения.
    # Лучше передать 'application.bot' в PetGame при инициализации.

    # Исправление:
    # В main.py:
    # db_manager = DBManager()
    # application = Application.builder().token(TOKEN).build()
    # game_instance = PetGame(db_manager, application.bot) # Передаем bot

    # В game_logic.py, в __init__:
    # def __init__(self, db_manager, bot):
    #    self.db_manager = db_manager
    #    self.bot = bot

    # И затем в функциях:
    # await self.bot.send_message(chat_id=chat_id, ...)
    # Однако, для send_pet_status, feed_pet и т.д., я полагался на update.effective_chat.id
    # и context.bot.send_message, которые доступны в обработчиках main.py.
    # Если вы хотите, чтобы game_logic сама отправляла сообщения,
    # то нужно передавать application.bot при инициализации game_instance.

    # В текущей версии main.py, функции send_pet_status, feed_pet и т.д.
    # вызываются из main.py и имеют доступ к context.bot.
    # Поэтому, строка `await self.db_manager.context.bot.send_message` является ошибкой.
    # Она должна быть `await context.bot.send_message` ИЛИ `await self.bot.send_message`
    # если bot передается в PetGame.
    #
    # Мой предыдущий `main.py` правильно передает `update.effective_chat.id`
    # и использует `await game_instance.send_pet_status(update.effective_chat.id, user_id)`.
    # Это означает, что `game_logic` не должен напрямую знать о `context.bot`.
    #
    # Итак, я должен исправить `game_logic.py`, чтобы он не пытался получить `context.bot` из `db_manager`.
    # Вместо этого, он должен получать `chat_id` и использовать `context.bot` из `main.py`.
    #
    # Упс, я вижу ошибку в своем коде. `send_pet_status` и другие функции в `PetGame`
    # получают `chat_id`, но не имеют `bot` для отправки сообщений.
    # Это значит, что `main.py` должен передавать `context.bot` в эти функции,
    # или `PetGame` должен иметь доступ к `bot` при инициализации.

    # Самое простое: передавать `context.bot` в каждую функцию `PetGame` при вызове из `main.py`.

    # Пересмотр:
    # Если PetGame должен сам отправлять сообщения, то в main.py:
    # application = Application.builder().token(TOKEN).build()
    # game_instance = PetGame(db_manager)
    # game_instance.set_bot_instance(application.bot) # Новый метод в PetGame

    # В game_logic.py:
    # class PetGame:
    #    def __init__(self, db_manager):
    #        self.db_manager = db_manager
    #        self.bot = None
    #    def set_bot_instance(self, bot):
    #        self.bot = bot
    #    async def send_pet_status(self, chat_id, user_id):
    #        if self.bot: await self.bot.send_message(...)

    # НЕТ, это усложнит. Давайте придерживаться передачи `chat_id` и `context.bot` в функции.
    # В `main.py` уже есть `context`, так что `context.bot` всегда доступен.
    # Мой `game_logic.py` выше не использует `context.bot` напрямую. Он использует `self.db_manager.context.bot`,
    # чего нет.
    #
    # Мне нужно будет переписать `send_pet_status` и другие функции в `game_logic.py`
    # чтобы они принимали `bot` как аргумент.

    # Corrected game_logic.py:
    # `send_pet_status` will now need `bot` argument.
    # `feed_pet` will need `bot` argument.
    # `play_with_pet` will need `bot` argument.
    # `clean_pet_area` will need `bot` argument.

    # This means `main.py` calls will change:
    # `await game_instance.send_pet_status(update.effective_chat.id, user_id)`
    # Becomes:
    # `await game_instance.send_pet_status(update.effective_chat.id, user_id, context.bot)`

    # Okay, I will provide the corrected game_logic.py and then a slightly modified main.py (only calls)

