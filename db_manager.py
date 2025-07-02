import os
import sqlite3
import datetime
# import json # Этот импорт не используется, можно удалить. Оставил закомментированным на всякий случай.

DATABASE_NAME = 'tamacoin_game.db'

class DBManager:
    def __init__(self):
        print("DEBUG_DB: DBManager __init__ started.")
        try:
            # check_same_thread=False важно для работы с Flask в многопоточной среде вебхуков
            self.conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
            self.cursor = self.conn.cursor()
            print(f"DEBUG_DB: SQLite connected to {DATABASE_NAME}.")
            self._create_tables()
            self._initialize_game_stats()
            print("DEBUG_DB: DBManager __init__ finished successfully.")
        except Exception as e:
            print(f"ERROR_DB: Failed to initialize DBManager: {e}")
            # Выведем полный стек вызовов для детальной информации об ошибке
            import traceback
            traceback.print_exc()
            raise # Перебросим исключение, чтобы Render показал ошибку запуска сервиса

    def _create_tables(self):
        print("DEBUG_DB: _create_tables started.")
        try:
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
            print("DEBUG_DB: Users table checked/created.")

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
            print("DEBUG_DB: Pets table checked/created.")

            # Новая таблица для общей статистики игры
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS game_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_distributed_coins INTEGER DEFAULT 0
                )
            ''')
            print("DEBUG_DB: Game stats table checked/created.")
            self.conn.commit()
            print("DEBUG_DB: _create_tables finished successfully.")
        except Exception as e:
            print(f"ERROR_DB: Failed to create tables: {e}")
            import traceback
            traceback.print_exc()
            raise # Перебросим исключение

    def _initialize_game_stats(self):
        print("DEBUG_DB: _initialize_game_stats started.")
        try:
            # Убедимся, что в таблице game_stats всегда есть одна строка
            self.cursor.execute('SELECT COUNT(*) FROM game_stats')
            if self.cursor.fetchone()[0] == 0:
                self.cursor.execute('INSERT INTO game_stats (total_distributed_coins) VALUES (?)', (0,))
                self.conn.commit()
                print("DEBUG_DB: Game stats initialized with 0 coins.")
            else:
                print("DEBUG_DB: Game stats already initialized (row exists).")
            print("DEBUG_DB: _initialize_game_stats finished successfully.")
        except Exception as e:
            print(f"ERROR_DB: Failed to initialize game stats: {e}")
            import traceback
            traceback.print_exc()
            raise

    def get_user(self, telegram_id):
        print(f"DEBUG_DB: get_user called for telegram_id: {telegram_id}")
        try:
            self.cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            user_data = self.cursor.fetchone()
            if user_data:
                columns = [description[0] for description in self.cursor.description]
                result = dict(zip(columns, user_data))
                print(f"DEBUG_DB: get_user found: {result}")
                return result
            print(f"DEBUG_DB: get_user not found for telegram_id: {telegram_id}.")
            return None
        except Exception as e:
            print(f"ERROR_DB: Failed in get_user for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def create_user(self, telegram_id, username):
        print(f"DEBUG_DB: create_user called for telegram_id: {telegram_id}, username: {username}")
        try:
            self.cursor.execute('INSERT INTO users (telegram_id, username, balance) VALUES (?, ?, ?)',
                                (telegram_id, username, 0))
            self.conn.commit()
            print(f"DEBUG_DB: User {telegram_id} created, fetching newly created user data.")
            return self.get_user(telegram_id)
        except sqlite3.IntegrityError:
            print(f"DEBUG_DB: User {telegram_id} already exists (IntegrityError), returning existing user.")
            return self.get_user(telegram_id) # User already exists, return existing
        except Exception as e:
            print(f"ERROR_DB: Failed in create_user for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def update_user_balance(self, telegram_id, amount):
        print(f"DEBUG_DB: update_user_balance called for telegram_id: {telegram_id}, amount: {amount}")
        try:
            self.cursor.execute('UPDATE users SET balance = balance + ? WHERE telegram_id = ?', (amount, telegram_id))
            self.conn.commit()
            if amount > 0:
                print(f"DEBUG_DB: Updating total distributed coins by {amount}.")
                self.update_total_distributed_coins(amount)
            updated_balance = self.get_user(telegram_id)['balance']
            print(f"DEBUG_DB: Balance for {telegram_id} updated to {updated_balance}.")
            return updated_balance
        except Exception as e:
            print(f"ERROR_DB: Failed in update_user_balance for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def update_user_pet_id(self, telegram_id, pet_id):
        print(f"DEBUG_DB: update_user_pet_id called for telegram_id: {telegram_id}, pet_id: {pet_id}")
        try:
            self.cursor.execute('UPDATE users SET pet_id = ? WHERE telegram_id = ?', (pet_id, telegram_id))
            self.conn.commit()
            print(f"DEBUG_DB: User {telegram_id} pet_id updated to {pet_id}.")
        except Exception as e:
            print(f"ERROR_DB: Failed in update_user_pet_id for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def update_last_daily_bonus(self, telegram_id, timestamp):
        print(f"DEBUG_DB: update_last_daily_bonus called for telegram_id: {telegram_id}, timestamp: {timestamp}")
        try:
            self.cursor.execute('UPDATE users SET last_daily_bonus = ? WHERE telegram_id = ?', (timestamp, telegram_id))
            self.conn.commit()
            print(f"DEBUG_DB: Last daily bonus timestamp updated for {telegram_id}.")
        except Exception as e:
            print(f"ERROR_DB: Failed in update_last_daily_bonus for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def increment_welcome_bonus_actions(self, telegram_id):
        print(f"DEBUG_DB: increment_welcome_bonus_actions called for telegram_id: {telegram_id}")
        try:
            self.cursor.execute('UPDATE users SET welcome_bonus_actions_count = welcome_bonus_actions_count + 1 WHERE telegram_id = ?', (telegram_id,))
            self.conn.commit()
            count = self.get_user(telegram_id)['welcome_bonus_actions_count']
            print(f"DEBUG_DB: Welcome bonus actions count for {telegram_id} incremented to {count}.")
            return count
        except Exception as e:
            print(f"ERROR_DB: Failed in increment_welcome_bonus_actions for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def reset_welcome_bonus_actions(self, telegram_id):
        print(f"DEBUG_DB: reset_welcome_bonus_actions called for telegram_id: {telegram_id}")
        try:
            self.cursor.execute('UPDATE users SET welcome_bonus_actions_count = 0 WHERE telegram_id = ?', (telegram_id,))
            self.conn.commit()
            print(f"DEBUG_DB: Welcome bonus actions reset for {telegram_id}.")
        except Exception as e:
            print(f"ERROR_DB: Failed in reset_welcome_bonus_actions for telegram_id {telegram_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def get_pet(self, owner_id):
        print(f"DEBUG_DB: get_pet called for owner_id: {owner_id}")
        try:
            self.cursor.execute('SELECT * FROM pets WHERE owner_id = ?', (owner_id,))
            pet_data = self.cursor.fetchone()
            if pet_data:
                columns = [description[0] for description in self.cursor.description]
                result = dict(zip(columns, pet_data))
                print(f"DEBUG_DB: get_pet found: {result}")
                return result
            print(f"DEBUG_DB: get_pet not found for owner_id: {owner_id}.")
            return None
        except Exception as e:
            print(f"ERROR_DB: Failed in get_pet for owner_id {owner_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def create_pet(self, owner_id, pet_type, name, is_alive=1):
        print(f"DEBUG_DB: create_pet called for owner_id: {owner_id}, type: {pet_type}, name: {name}, is_alive: {is_alive}")
        try:
            initial_state_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.cursor.execute('''
                INSERT INTO pets (owner_id, pet_type, name, hunger, happiness, health, is_alive, last_state_update)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (owner_id, pet_type, name, 100.0, 100.0, 100.0, is_alive, initial_state_time))
            self.conn.commit()
            pet_data = self.get_pet(owner_id)
            
            owner_user_data = self.get_user_by_db_id(owner_id)
            if owner_user_data:
                self.update_user_pet_id(owner_user_data['telegram_id'], pet_data['id'])
            print(f"DEBUG_DB: Pet created: {pet_data}")
            return pet_data
        except Exception as e:
            print(f"ERROR_DB: Failed in create_pet for owner_id {owner_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def update_pet_state(self, owner_id, hunger, happiness, health, last_state_update):
        print(f"DEBUG_DB: update_pet_state called for owner_id: {owner_id}, hunger: {hunger}, happiness: {happiness}, health: {health}")
        try:
            self.cursor.execute('''
                UPDATE pets SET hunger = ?, happiness = ?, health = ?, last_state_update = ?
                WHERE owner_id = ?
            ''', (hunger, happiness, health, last_state_update, owner_id))
            self.conn.commit()
            print(f"DEBUG_DB: Pet state updated for owner_id {owner_id}.")
        except Exception as e:
            print(f"ERROR_DB: Failed in update_pet_state for owner_id {owner_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def update_pet_action_time(self, owner_id, action_type, timestamp):
        print(f"DEBUG_DB: update_pet_action_time called for owner_id: {owner_id}, action_type: {action_type}, timestamp: {timestamp}")
        try:
            set_clause = f"{action_type} = ?"
            self.cursor.execute(f'UPDATE pets SET {set_clause} WHERE owner_id = ?', (timestamp, owner_id))
            self.conn.commit()
            print(f"DEBUG_DB: Pet action time for {action_type} updated for owner_id {owner_id}.")
        except Exception as e:
            print(f"ERROR_DB: Failed in update_pet_action_time for owner_id {owner_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def kill_pet(self, owner_id):
        print(f"DEBUG_DB: kill_pet called for owner_id: {owner_id}")
        try:
            self.cursor.execute('UPDATE pets SET is_alive = 0 WHERE owner_id = ?', (owner_id,))
            self.conn.commit()
            print(f"DEBUG_DB: Pet for owner_id {owner_id} killed (is_alive set to 0).")
        except Exception as e:
            print(f"ERROR_DB: Failed in kill_pet for owner_id {owner_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def get_user_by_db_id(self, db_id):
        print(f"DEBUG_DB: get_user_by_db_id called for db_id: {db_id}")
        try:
            self.cursor.execute('SELECT * FROM users WHERE id = ?', (db_id,))
            user_data = self.cursor.fetchone()
            if user_data:
                columns = [description[0] for description in self.cursor.description]
                result = dict(zip(columns, user_data))
                print(f"DEBUG_DB: get_user_by_db_id found: {result}")
                return result
            print(f"DEBUG_DB: get_user_by_db_id not found for db_id: {db_id}.")
            return None
        except Exception as e:
            print(f"ERROR_DB: Failed in get_user_by_db_id for db_id {db_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def get_total_users_with_pets(self):
        print("DEBUG_DB: get_total_users_with_pets called.")
        try:
            self.cursor.execute('SELECT COUNT(DISTINCT owner_id) FROM pets WHERE is_alive = 1')
            count = self.cursor.fetchone()[0]
            print(f"DEBUG_DB: Total users with active pets: {count}.")
            return count
        except Exception as e:
            print(f"ERROR_DB: Failed in get_total_users_with_pets: {e}")
            import traceback
            traceback.print_exc()
            raise

    def get_game_stats(self):
        print("DEBUG_DB: get_game_stats called.")
        try:
            self.cursor.execute('SELECT * FROM game_stats LIMIT 1')
            stats_data = self.cursor.fetchone()
            if stats_data:
                columns = [description[0] for description in self.cursor.description]
                result = dict(zip(columns, stats_data))
                print(f"DEBUG_DB: Game stats found: {result}")
                return result
            print("DEBUG_DB: Game stats not found, returning default dictionary.")
            return {'total_distributed_coins': 0} # Возвращаем дефолт, если нет данных
        except Exception as e:
            print(f"ERROR_DB: Failed in get_game_stats: {e}")
            import traceback
            traceback.print_exc()
            raise

    def update_total_distributed_coins(self, amount):
        print(f"DEBUG_DB: update_total_distributed_coins called with amount: {amount}")
        try:
            # Убеждаемся, что строка с id=1 существует, если нет - создаем, чтобы избежать ошибок.
            # Это на случай, если _initialize_game_stats не сработал корректно.
            self.cursor.execute('INSERT OR IGNORE INTO game_stats (id, total_distributed_coins) VALUES (1, 0)')
            self.cursor.execute('UPDATE game_stats SET total_distributed_coins = total_distributed_coins + ? WHERE id = 1', (amount,))
            self.conn.commit()
            print(f"DEBUG_DB: Total distributed coins updated by {amount}.")
        except Exception as e:
            print(f"ERROR_DB: Failed in update_total_distributed_coins: {e}")
            import traceback
            traceback.print_exc()
            raise

    def close(self):
        print("DEBUG_DB: DBManager close called.")
        try:
            self.conn.close()
            print("DEBUG_DB: DB connection closed.")
        except Exception as e:
            print(f"ERROR_DB: Failed to close DB connection: {e}")
            import traceback
            traceback.print_exc()
            raise

# Инициализация DBManager (для использования в main.py)
print("DEBUG_DB: Attempting global DBManager instance initialization.")
try:
    db = DBManager()
    print("DEBUG_DB: Global DBManager instance initialization completed successfully.")
except Exception as e:
    print(f"FATAL_ERROR: Global DBManager instance initialization failed, application may not function: {e}")
    import traceback
    traceback.print_exc()
    # В этом случае приложение, скорее всего, не сможет работать,
    # и Render должен показать ошибку в логах запуска, что нам и нужно.
