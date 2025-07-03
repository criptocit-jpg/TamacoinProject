import os
import psycopg2
from psycopg2 import sql
import logging

# Настройка логирования для отладки
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DBManager:
    _instance = None
    _connection = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DBManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if DBManager._connection is None:
            self._connect()

    def _connect(self):
        try:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                logger.error("DATABASE_URL environment variable not set.")
                raise ValueError("DATABASE_URL environment variable not set.")
            
            DBManager._connection = psycopg2.connect(database_url)
            DBManager._connection.autocommit = True # Автоматическая фиксация изменений
            logger.info("Successfully connected to PostgreSQL database.")
            self._create_tables()
        except Exception as e:
            logger.exception(f"Error connecting to PostgreSQL database: {e}")
            DBManager._connection = None # Сбросить соединение, чтобы при следующей попытке оно было None
            raise # Повторно выбросить исключение, чтобы остановить инициализацию, если БД недоступна

    def _get_cursor(self):
        if DBManager._connection is None or DBManager._connection.closed:
            logger.debug("Re-establishing PostgreSQL connection.")
            self._connect() # Попытка переподключения
        return DBManager._connection.cursor()

    def _create_tables(self):
        try:
            with self._get_cursor() as cur:
                # Создаем таблицу users
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        telegram_id BIGINT UNIQUE NOT NULL,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        last_name VARCHAR(255),
                        balance INTEGER DEFAULT 0,
                        last_daily_bonus TIMESTAMP
                    );
                """)
                logger.debug("Table 'users' ensured to exist.")

                # Создаем таблицу pets
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pets (
                        id SERIAL PRIMARY KEY,
                        owner_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                        pet_type VARCHAR(50) NOT NULL,
                        name VARCHAR(255),
                        health INTEGER DEFAULT 100,
                        happiness INTEGER DEFAULT 100,
                        hunger INTEGER DEFAULT 0,
                        last_fed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_cleaned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_interacted TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                logger.debug("Table 'pets' ensured to exist.")

                # Создаем таблицу game_stats (для статистики)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS game_stats (
                        id SERIAL PRIMARY KEY,
                        total_emitted_tamacoin BIGINT DEFAULT 0,
                        total_users BIGINT DEFAULT 0
                    );
                """)
                logger.debug("Table 'game_stats' ensured to exist.")
                
                # Инициализация game_stats, если она пуста
                cur.execute("SELECT COUNT(*) FROM game_stats;")
                if cur.fetchone()[0] == 0:
                    cur.execute("INSERT INTO game_stats (total_emitted_tamacoin, total_users) VALUES (0, 0);")
                    logger.debug("game_stats initialized.")

        except Exception as e:
            logger.exception(f"Error creating tables: {e}")
            raise # Перевыбросить исключение

    def close(self):
        if DBManager._connection:
            DBManager._connection.close()
            DBManager._connection = None
            logger.info("Database connection closed.")

    def get_user(self, telegram_id):
        logger.debug(f"get_user called for telegram_id: {telegram_id}")
        try:
            with self._get_cursor() as cur:
                cur.execute("SELECT id, telegram_id, username, first_name, last_name, balance, last_daily_bonus FROM users WHERE telegram_id = %s;", (telegram_id,))
                user_data = cur.fetchone()
                if user_data:
                    logger.debug(f"User found: {user_data}")
                    # Преобразуем timestamp в datetime объект, если он есть
                    user_data_list = list(user_data)
                    if user_data_list[6]: # last_daily_bonus
                        user_data_list[6] = user_data_list[6].replace(tzinfo=None) # Удаляем информацию о таймзоне
                    return tuple(user_data_list)
                logger.debug(f"User not found for telegram_id: {telegram_id}")
                return None
        except Exception as e:
            logger.exception(f"Error getting user {telegram_id}: {e}")
            return None

    def add_user(self, telegram_id, username, first_name, last_name):
        logger.debug(f"add_user called for telegram_id: {telegram_id}")
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "INSERT INTO users (telegram_id, username, first_name, last_name) VALUES (%s, %s, %s, %s) RETURNING id;",
                    (telegram_id, username, first_name, last_name)
                )
                user_id = cur.fetchone()[0]
                logger.info(f"User {telegram_id} added with internal ID: {user_id}")
                # Обновляем game_stats
                cur.execute("UPDATE game_stats SET total_users = total_users + 1;")
                return user_id
        except psycopg2.errors.UniqueViolation:
            logger.warning(f"User {telegram_id} already exists (add_user called but user exists).")
            return self.get_user(telegram_id)[0] # Возвращаем ID существующего пользователя
        except Exception as e:
            logger.exception(f"Error adding user {telegram_id}: {e}")
            return None

    def update_user_balance(self, user_id, amount):
        logger.debug(f"update_user_balance called for user_id: {user_id}, amount: {amount}")
        try:
            with self._get_cursor() as cur:
                cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s RETURNING balance;", (amount, user_id))
                new_balance = cur.fetchone()[0]
                logger.info(f"User {user_id} balance updated to {new_balance}. Amount: {amount}")
                # Обновляем game_stats, если добавляем монеты
                if amount > 0:
                    cur.execute("UPDATE game_stats SET total_emitted_tamacoin = total_emitted_tamacoin + %s;", (amount,))
                return new_balance
        except Exception as e:
            logger.exception(f"Error updating user {user_id} balance: {e}")
            return None

    def update_user_daily_bonus_time(self, user_id):
        logger.debug(f"update_user_daily_bonus_time called for user_id: {user_id}")
        try:
            from datetime import datetime
            with self._get_cursor() as cur:
                cur.execute("UPDATE users SET last_daily_bonus = %s WHERE id = %s;", (datetime.now(), user_id))
                logger.info(f"User {user_id} last_daily_bonus updated.")
            return True
        except Exception as e:
            logger.exception(f"Error updating last_daily_bonus for user {user_id}: {e}")
            return False

    def create_pet(self, owner_id, pet_type, name):
        logger.debug(f"create_pet called for owner_id: {owner_id}, pet_type: {pet_type}, name: {name}")
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "INSERT INTO pets (owner_id, pet_type, name) VALUES (%s, %s, %s);",
                    (owner_id, pet_type, name)
                )
                logger.info(f"Pet '{name}' of type '{pet_type}' created for user {owner_id}.")
            return True
        except psycopg2.errors.UniqueViolation:
            logger.warning(f"Pet already exists for owner_id {owner_id}. Skipping creation.")
            return False # Или True, если вы считаете, что это не ошибка
        except Exception as e:
            logger.exception(f"Error creating pet for owner_id {owner_id}: {e}")
            return False

    def get_pet(self, owner_id):
        logger.debug(f"get_pet called for owner_id: {owner_id}")
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "SELECT id, owner_id, pet_type, name, health, happiness, hunger, last_fed, last_played, last_cleaned, last_interacted FROM pets WHERE owner_id = %s;",
                    (owner_id,)
                )
                pet_data = cur.fetchone()
                if pet_data:
                    logger.debug(f"Pet found for owner_id: {owner_id}")
                    # Преобразовать timestamp в datetime объекты, если они есть
                    pet_data_list = list(pet_data)
                    for i in [7, 8, 9, 10]: # Индексы для last_fed, last_played, last_cleaned, last_interacted
                        if pet_data_list[i]:
                            pet_data_list[i] = pet_data_list[i].replace(tzinfo=None) # Удаляем информацию о таймзоне
                    return tuple(pet_data_list)
                logger.debug(f"Pet not found for owner_id {owner_id}.")
                return None
        except Exception as e:
            logger.exception(f"Error getting pet for owner_id {owner_id}: {e}")
            return None

    def update_pet_stats(self, pet_id, health=None, happiness=None, hunger=None, last_fed=None, last_played=None, last_cleaned=None, last_interacted=None):
        logger.debug(f"update_pet_stats called for pet_id: {pet_id}")
        try:
            updates = []
            params = []
            from datetime import datetime

            if health is not None:
                updates.append("health = %s")
                params.append(health)
            if happiness is not None:
                updates.append("happiness = %s")
                params.append(happiness)
            if hunger is not None:
                updates.append("hunger = %s")
                params.append(hunger)
            if last_fed is not None:
                updates.append("last_fed = %s")
                params.append(last_fed if isinstance(last_fed, datetime) else datetime.now())
            if last_played is not None:
                updates.append("last_played = %s")
                params.append(last_played if isinstance(last_played, datetime) else datetime.now())
            if last_cleaned is not None:
                updates.append("last_cleaned = %s")
                params.append(last_cleaned if isinstance(last_cleaned, datetime) else datetime.now())
            if last_interacted is not None:
                updates.append("last_interacted = %s")
                params.append(last_interacted if isinstance(last_interacted, datetime) else datetime.now())
            
            if not updates:
                logger.warning(f"No stats to update for pet_id {pet_id}.")
                return False

            query = sql.SQL("UPDATE pets SET {} WHERE id = %s;").format(
                sql.SQL(", ").join(map(sql.SQL, updates))
            )
            params.append(pet_id)

            with self._get_cursor() as cur:
                cur.execute(query, tuple(params))
                logger.info(f"Pet {pet_id} stats updated.")
            return True
        except Exception as e:
            logger.exception(f"Error updating pet {pet_id} stats: {e}")
            return False

    def get_game_stats(self):
        logger.debug("get_game_stats called.")
        try:
            with self._get_cursor() as cur:
                cur.execute("SELECT total_emitted_tamacoin, total_users FROM game_stats LIMIT 1;")
                stats = cur.fetchone()
                if stats:
                    logger.debug(f"Game stats found: {stats}")
                    return {"total_emitted_tamacoin": stats[0], "total_users": stats[1]}
                logger.warning("Game stats not found or table empty.")
                return {"total_emitted_tamacoin": 0, "total_users": 0}
        except Exception as e:
            logger.exception(f"Error getting game stats: {e}")
            return {"total_emitted_tamacoin": 0, "total_users": 0}

    def get_total_users_count(self):
        logger.debug("get_total_users_count called.")
        try:
            with self._get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users;")
                count = cur.fetchone()[0]
                logger.debug(f"Total users count: {count}")
                return count
        except Exception as e:
            logger.exception(f"Error getting total users count: {e}")
            return 0
