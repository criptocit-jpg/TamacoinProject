import sqlite3
import datetime
import json

DATABASE_NAME = 'tamacoin_game.db'

class DBManager:
    def __init__(self):
        # check_same_thread=False важно для работы с Flask в многопоточной среде вебхуков
        self.conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._initialize_game_stats() # Добавляем инициализацию статистики

    def _create_tables(self):
        # Таблица для пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                balance INTEGER DEFAULT 0,
                pet_id INTEGER,
                last_daily_bonus TEXT, -- ISO format string
                welcome_bonus_actions_count INTEGER DEFAULT 0,
                FOREIGN KEY (pet_id) REFERENCES pets(id)
            )
        ''')

        # Таблица для питомцев (их текущее состояние)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER UNIQUE NOT NULL, -- Ссылка на user_id
                pet_type TEXT NOT NULL, -- 'toothless', 'light_fury', 'stormfly'
                name TEXT NOT NULL,
                hunger REAL DEFAULT 100.0, -- 0-100, 100 is full
                happiness REAL DEFAULT 100.0, -- 0-100, 100 is happy
                health REAL DEFAULT 100.0, -- 0-100, 100 is healthy
                is_alive INTEGER DEFAULT 1, -- 1 for alive, 0 for dead
                last_fed TEXT, -- ISO format string
                last_played TEXT, -- ISO format string
                last_cleaned TEXT, -- ISO format string
                last_state_update TEXT, -- For calculating decay over time
                FOREIGN KEY (owner_id) REFERENCES users(id)
            )
        ''')

        # Новая таблица для общей статистики игры
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_distributed_coins INTEGER DEFAULT 0
            )
        ''')
        self.conn.commit()

    def _initialize_game_stats(self):
        # Убедимся, что в таблице game_stats всегда есть одна строка
        self.cursor.execute('SELECT COUNT(*) FROM game_stats')
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute('INSERT INTO game_stats (total_distributed_coins) VALUES (?)', (0,))
            self.conn.commit()

    def get_user(self, telegram_id):
        self.cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        user_data = self.cursor.fetchone()
        if user_data:
            # Преобразуем tuple в словарь для удобства
            columns = [description[0] for description in self.cursor.description]
            return dict(zip(columns, user_data))
        return None

    def create_user(self, telegram_id, username):
        try:
            self.cursor.execute('INSERT INTO users (telegram_id, username, balance) VALUES (?, ?, ?)',
                                (telegram_id, username, 0))
            self.conn.commit()
            return self.get_user(telegram_id)
        except sqlite3.IntegrityError:
            return self.get_user(telegram_id) # User already exists, return existing

    def update_user_balance(self, telegram_id, amount):
        self.cursor.execute('UPDATE users SET balance = balance + ? WHERE telegram_id = ?', (amount, telegram_id))
        self.conn.commit()
        # Если выдаем монеты (amount > 0), обновляем общую статистику распределения
        if amount > 0:
            self.update_total_distributed_coins(amount)
        return self.get_user(telegram_id)['balance']

    def update_user_pet_id(self, telegram_id, pet_id):
        self.cursor.execute('UPDATE users SET pet_id = ? WHERE telegram_id = ?', (pet_id, telegram_id))
        self.conn.commit()

    def update_last_daily_bonus(self, telegram_id, timestamp):
        self.cursor.execute('UPDATE users SET last_daily_bonus = ? WHERE telegram_id = ?', (timestamp, telegram_id))
        self.conn.commit()

    def increment_welcome_bonus_actions(self, telegram_id):
        self.cursor.execute('UPDATE users SET welcome_bonus_actions_count = welcome_bonus_actions_count + 1 WHERE telegram_id = ?', (telegram_id,))
        self.conn.commit()
        return self.get_user(telegram_id)['welcome_bonus_actions_count']

    def reset_welcome_bonus_actions(self, telegram_id):
        self.cursor.execute('UPDATE users SET welcome_bonus_actions_count = 0 WHERE telegram_id = ?', (telegram_id,))
        self.conn.commit()

    def get_pet(self, owner_id):
        self.cursor.execute('SELECT * FROM pets WHERE owner_id = ?', (owner_id,))
        pet_data = self.cursor.fetchone()
        if pet_data:
            columns = [description[0] for description in self.cursor.description]
            return dict(zip(columns, pet_data))
        return None

    def create_pet(self, owner_id, pet_type, name, is_alive=1):
        # Устанавливаем начальные значения для состояния питомца и времени последнего обновления
        initial_state_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.cursor.execute('''
            INSERT INTO pets (owner_id, pet_type, name, hunger, happiness, health, is_alive, last_state_update)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (owner_id, pet_type, name, 100.0, 100.0, 100.0, is_alive, initial_state_time))
        self.conn.commit()
        pet_data = self.get_pet(owner_id)
        # Получаем telegram_id пользователя из owner_id, чтобы обновить pet_id в таблице users
        owner_user_data = self.get_user_by_db_id(owner_id)
        if owner_user_data:
            self.update_user_pet_id(owner_user_data['telegram_id'], pet_data['id'])
        return pet_data

    def update_pet_state(self, owner_id, hunger, happiness, health, last_state_update):
        self.cursor.execute('''
            UPDATE pets SET hunger = ?, happiness = ?, health = ?, last_state_update = ?
            WHERE owner_id = ?
        ''', (hunger, happiness, health, last_state_update, owner_id))
        self.conn.commit()

    def update_pet_action_time(self, owner_id, action_type, timestamp):
        # action_type может быть 'last_fed', 'last_played', 'last_cleaned'
        set_clause = f"{action_type} = ?"
        self.cursor.execute(f'UPDATE pets SET {set_clause} WHERE owner_id = ?', (timestamp, owner_id))
        self.conn.commit()

    def kill_pet(self, owner_id):
        self.cursor.execute('UPDATE pets SET is_alive = 0 WHERE owner_id = ?', (owner_id,))
        self.conn.commit()

    def get_user_by_db_id(self, db_id):
        self.cursor.execute('SELECT * FROM users WHERE id = ?', (db_id,))
        user_data = self.cursor.fetchone()
        if user_data:
            columns = [description[0] for description in self.cursor.description]
            return dict(zip(columns, user_data))
        return None

    def get_total_users_with_pets(self):
        self.cursor.execute('SELECT COUNT(DISTINCT owner_id) FROM pets WHERE is_alive = 1')
        return self.cursor.fetchone()[0]

    # Функции для отслеживания общей статистики
    def get_game_stats(self):
        self.cursor.execute('SELECT * FROM game_stats LIMIT 1')
        stats_data = self.cursor.fetchone()
        if stats_data:
            columns = [description[0] for description in self.cursor.description]
            return dict(zip(columns, stats_data))
        return {'total_distributed_coins': 0} # Возвращаем дефолт, если нет данных

    def update_total_distributed_coins(self, amount):
        self.cursor.execute('UPDATE game_stats SET total_distributed_coins = total_distributed_coins + ? WHERE id = 1', (amount,))
        self.conn.commit()

    def close(self):
        self.conn.close()

# Инициализация DBManager (для использования в main.py)
db = DBManager()
