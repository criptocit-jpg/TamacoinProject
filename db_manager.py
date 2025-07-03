import sqlite3
import datetime
import json # Импортируем json для сериализации/десериализации сложных данных, если они появятся

class DBManager:
    _instance = None
    _is_initialized = False

    def __new__(cls, db_path='tamacoin_game.db'):
        print("DEBUG_DB: Attempting global DBManager instance initialization.")
        if cls._instance is None:
            cls._instance = super(DBManager, cls).__new__(cls)
            cls._instance.db_path = db_path
            # Инициализируем соединение и таблицы только один раз
            if not cls._is_initialized:
                cls._instance._init_db()
                cls._is_initialized = True
        return cls._instance

    def _init_db(self):
        print("DEBUG_DB: DBManager __init__ started.")
        self.conn = None # Инициализируем conn как None
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row # Позволяет получать строки как объекты-словари
            print(f"DEBUG_DB: SQLite connected to {self.db_path}.")
            self._create_tables()
            self._initialize_game_stats() # Инициализация общих игровых статистик
            print("DEBUG_DB: DBManager __init__ finished successfully.")
        except sqlite3.Error as e:
            print(f"ERROR_DB: SQLite connection or initialization error: {e}")
            if self.conn:
                self.conn.close()
            self.conn = None # Убедимся, что соединение закрыто и обнулено
            raise # Перевыбрасываем исключение, так как это критическая ошибка

    def _get_cursor(self):
        """Получает курсор, переподключаясь, если соединение закрыто."""
        try:
            if not self.conn or not self.conn.ping(): # ping() не существует в sqlite3, поэтому просто try/except
                raise sqlite3.Error("Connection is closed or invalid.")
        except (sqlite3.Error, AttributeError):
            print("DEBUG_DB: Re-establishing SQLite connection.")
            try:
                self.conn = sqlite3.connect(self.db_path)
                self.conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                print(f"FATAL_ERROR_DB: Could not re-establish SQLite connection: {e}")
                raise # Критическая ошибка, не можем работать без базы
        return self.conn.cursor()

    def _create_tables(self):
        print("DEBUG_DB: _create_tables started.")
        try:
            cursor = self._get_cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    balance REAL DEFAULT 0.0,
                    pet_id INTEGER, -- Ссылка на ID питомца
                    daily_bonus_last_claimed TEXT,
                    FOREIGN KEY (pet_id) REFERENCES pets (owner_id) ON DELETE SET NULL
                )
            """)
            print("DEBUG_DB: Users table checked/created.")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER UNIQUE NOT NULL, -- Ссылка на id пользователя
                    pet_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    hunger REAL DEFAULT 100.0,
                    happiness REAL DEFAULT 100.0,
                    health REAL DEFAULT 100.0,
                    is_alive INTEGER DEFAULT 1,
                    last_state_update TEXT,
                    last_action_time TEXT,
                    FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            print("DEBUG_DB: Pets table checked/created.")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_tamacoins_circulating REAL DEFAULT 0.0,
                    total_pets_created INTEGER DEFAULT 0,
                    last_update TEXT
                )
            """)
            print("DEBUG_DB: Game stats table checked/created.")

            self.conn.commit()
            print("DEBUG_DB: _create_tables finished successfully.")
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error creating tables: {e}")
            raise # Перевыбрасываем, так как без таблиц работать нельзя

    def _initialize_game_stats(self):
        print("DEBUG_DB: _initialize_game_stats started.")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT COUNT(*) FROM game_stats")
            count = cursor.fetchone()[0]
            if count == 0:
                # Вставляем начальные данные, если таблица пуста
                # total_tamacoins_circulating должен быть равен общему INITIAL_SUPPLY
                from pet_config import TOTAL_INITIAL_SUPPLY # Импортируем здесь, чтобы избежать циклической зависимости
                initial_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
                cursor.execute(
                    "INSERT INTO game_stats (total_tamacoins_circulating, total_pets_created, last_update) VALUES (?, ?, ?)",
                    (TOTAL_INITIAL_SUPPLY, 0, initial_time)
                )
                self.conn.commit()
                print(f"DEBUG_DB: Game stats initialized with TOTAL_INITIAL_SUPPLY: {TOTAL_INITIAL_SUPPLY}.")
            else:
                print("DEBUG_DB: Game stats already initialized (row exists).")
            print("DEBUG_DB: _initialize_game_stats finished successfully.")
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error initializing game stats: {e}")
            raise

    # --- Методы для работы с пользователями ---
    def create_user(self, telegram_id, username):
        print(f"DEBUG_DB: create_user called for telegram_id: {telegram_id}, username: {username}")
        try:
            cursor = self._get_cursor()
            # Установим initial_tamacions_balance как начальный баланс
            from pet_config import INITIAL_TAMACIONS_BALANCE # Импортируем здесь
            cursor.execute(
                "INSERT INTO users (telegram_id, username, balance, daily_bonus_last_claimed) VALUES (?, ?, ?, ?)",
                (telegram_id, username, INITIAL_TAMACIONS_BALANCE, datetime.datetime.now(datetime.timezone.utc).isoformat())
            )
            self.conn.commit()
            new_user_id = cursor.lastrowid
            print(f"DEBUG_DB: User created: id={new_user_id}, telegram_id={telegram_id}, balance={INITIAL_TAMACIONS_BALANCE}.")
            return self.get_user(telegram_id) # Возвращаем полный объект пользователя
        except sqlite3.IntegrityError:
            print(f"WARNING_DB: User with telegram_id {telegram_id} already exists. Returning existing user.")
            return self.get_user(telegram_id)
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error creating user {telegram_id}: {e}")
            return None

    def get_user(self, telegram_id):
        print(f"DEBUG_DB: get_user called for telegram_id: {telegram_id}")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()
            if user:
                user_dict = dict(user)
                print(f"DEBUG_DB: User found: {user_dict['username']} (ID: {user_dict['id']}).")
                return user_dict
            print(f"DEBUG_DB: User with telegram_id {telegram_id} not found.")
            return None
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error getting user {telegram_id}: {e}")
            return None

    def update_user_balance(self, user_id, amount):
        print(f"DEBUG_DB: update_user_balance called for user_id: {user_id}, amount: {amount}")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
            self.conn.commit()
            print(f"DEBUG_DB: User {user_id} balance updated by {amount}.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error updating user {user_id} balance: {e}")
            return False

    def update_user_pet_id(self, user_id, pet_id):
        print(f"DEBUG_DB: update_user_pet_id called for user_id: {user_id}, pet_id: {pet_id}")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE users SET pet_id = ? WHERE id = ?", (pet_id, user_id))
            self.conn.commit()
            print(f"DEBUG_DB: User {user_id} pet_id updated to {pet_id}.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error updating user {user_id} pet_id: {e}")
            return False

    def update_daily_bonus_time(self, user_id, timestamp):
        print(f"DEBUG_DB: update_daily_bonus_time called for user_id: {user_id}, timestamp: {timestamp}")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE users SET daily_bonus_last_claimed = ? WHERE id = ?", (timestamp, user_id))
            self.conn.commit()
            print(f"DEBUG_DB: User {user_id} daily_bonus_last_claimed updated.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error updating daily bonus time for user {user_id}: {e}")
            return False

    # --- Методы для работы с питомцами ---
    def create_pet(self, owner_id, pet_type, name):
        print(f"DEBUG_DB: create_pet called for owner_id: {owner_id}, pet_type: {pet_type}, name: {name}")
        try:
            cursor = self._get_cursor()
            current_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO pets (owner_id, pet_type, name, last_state_update, last_action_time) VALUES (?, ?, ?, ?, ?)",
                (owner_id, pet_type, name, current_time, current_time)
            )
            self.conn.commit()
            new_pet_id = cursor.lastrowid
            self.update_user_pet_id(owner_id, new_pet_id) # Связываем питомца с пользователем
            self.increment_total_pets_created() # Увеличиваем счетчик созданных питомцев
            print(f"DEBUG_DB: Pet created: id={new_pet_id}, owner_id={owner_id}, type={pet_type}, name={name}.")
            return self.get_pet(owner_id) # Возвращаем полный объект питомца
        except sqlite3.IntegrityError:
            print(f"WARNING_DB: Pet for owner_id {owner_id} already exists. Cannot create duplicate.")
            return None # Или можно вернуть существующего питомца, если это ожидаемое поведение
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error creating pet for owner_id {owner_id}: {e}")
            return None

    def get_pet(self, owner_id):
        print(f"DEBUG_DB: get_pet called for owner_id: {owner_id}")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT * FROM pets WHERE owner_id = ?", (owner_id,))
            pet = cursor.fetchone()
            if pet:
                pet_dict = dict(pet)
                print(f"DEBUG_DB: Pet found for owner {owner_id}: {pet_dict['name']} (ID: {pet_dict['id']}).")
                return pet_dict
            print(f"DEBUG_DB: Pet not found for owner_id {owner_id}.")
            return None
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error getting pet for owner_id {owner_id}: {e}")
            return None

    def update_pet_state(self, owner_id, hunger, happiness, health, last_state_update):
        print(f"DEBUG_DB: update_pet_state called for owner_id: {owner_id}, hunger: {hunger}, happiness: {happiness}, health: {health}")
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "UPDATE pets SET hunger = ?, happiness = ?, health = ?, last_state_update = ? WHERE owner_id = ?",
                (hunger, happiness, health, last_state_update, owner_id)
            )
            self.conn.commit()
            print(f"DEBUG_DB: Pet state updated for owner_id {owner_id}.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error updating pet state for owner_id {owner_id}: {e}")
            return False

    def update_pet_action_time(self, owner_id, last_action_time):
        print(f"DEBUG_DB: update_pet_action_time called for owner_id: {owner_id}, time: {last_action_time}")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE pets SET last_action_time = ? WHERE owner_id = ?", (last_action_time, owner_id))
            self.conn.commit()
            print(f"DEBUG_DB: Pet last_action_time updated for owner_id {owner_id}.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error updating pet action time for owner_id {owner_id}: {e}")
            return False

    def kill_pet(self, owner_id):
        print(f"DEBUG_DB: kill_pet called for owner_id: {owner_id}")
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "UPDATE pets SET is_alive = 0, hunger = 0.0, happiness = 0.0, health = 0.0 WHERE owner_id = ?",
                (owner_id,)
            )
            self.conn.commit()
            print(f"DEBUG_DB: Pet for owner_id {owner_id} marked as dead.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error killing pet for owner_id {owner_id}: {e}")
            return False

    # --- Методы для работы с общей статистикой игры ---
    def increment_total_pets_created(self):
        print("DEBUG_DB: increment_total_pets_created called.")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE game_stats SET total_pets_created = total_pets_created + 1, last_update = ?",
                           (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
            self.conn.commit()
            print("DEBUG_DB: total_pets_created incremented.")
            return True
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error incrementing total_pets_created: {e}")
            return False

    def get_game_stats(self):
        print("DEBUG_DB: get_game_stats called.")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT * FROM game_stats LIMIT 1")
            stats = cursor.fetchone()
            if stats:
                stats_dict = dict(stats)
                print(f"DEBUG_DB: Game stats retrieved: {stats_dict}.")
                return stats_dict
            print("DEBUG_DB: No game stats found.")
            return None
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error getting game stats: {e}")
            return None

    def get_total_users_count(self):
        print("DEBUG_DB: get_total_users_count called.")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            print(f"DEBUG_DB: Total users count: {count}.")
            return count
        except sqlite3.Error as e:
            print(f"ERROR_DB: Error getting total users count: {e}")
            return 0

# Создаем единственный экземпляр DBManager для всего приложения
try:
    db = DBManager()
    print("DEBUG_DB: Global DBManager instance initialization completed successfully.")
except Exception as e:
    print(f"FATAL_ERROR: Failed to initialize DBManager: {e}")
    # В этом случае приложение, возможно, не сможет продолжить работу
    db = None # Установим db в None, чтобы избежать использования неинициализированного объекта
