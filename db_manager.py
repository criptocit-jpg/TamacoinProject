import sqlite3
import datetime
import json
import sys # Добавьте этот импорт, если его нет

class DBManager:
    _instance = None
    _is_initialized = False

    def __new__(cls, db_path='tamacoin_game.db'):
        sys.stderr.write("DEBUG_DB: Attempting global DBManager instance initialization.\n")
        if cls._instance is None:
            cls._instance = super(DBManager, cls).__new__(cls)
            cls._instance.db_path = db_path
            if not cls._is_initialized:
                cls._instance._init_db()
                cls._is_initialized = True
        return cls._instance

    def _init_db(self):
        sys.stderr.write("DEBUG_DB: DBManager __init__ started.\n")
        self.conn = None
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            sys.stderr.write(f"DEBUG_DB: SQLite connected to {self.db_path}.\n")
            self._create_tables()
            self._initialize_game_stats()
            sys.stderr.write("DEBUG_DB: DBManager __init__ finished successfully.\n")
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: SQLite connection or initialization error: {e}\n")
            if self.conn:
                self.conn.close()
            self.conn = None
            raise

    def _get_cursor(self):
        try:
            if not self.conn: # sqlite3 не имеет ping(), поэтому просто проверяем, что conn не None
                raise sqlite3.Error("Connection is closed or invalid.")
            self.conn.cursor() # Пробуем получить курсор, чтобы проверить соединение
        except (sqlite3.Error, AttributeError):
            sys.stderr.write("DEBUG_DB: Re-establishing SQLite connection.\n")
            try:
                self.conn = sqlite3.connect(self.db_path)
                self.conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                sys.stderr.write(f"FATAL_ERROR_DB: Could not re-establish SQLite connection: {e}\n")
                raise
        return self.conn.cursor()

    def _create_tables(self):
        sys.stderr.write("DEBUG_DB: _create_tables started.\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    balance REAL DEFAULT 0.0,
                    pet_id INTEGER,
                    daily_bonus_last_claimed TEXT,
                    FOREIGN KEY (pet_id) REFERENCES pets (owner_id) ON DELETE SET NULL
                )
            """)
            sys.stderr.write("DEBUG_DB: Users table checked/created.\n")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER UNIQUE NOT NULL,
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
            sys.stderr.write("DEBUG_DB: Pets table checked/created.\n")
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_tamacoins_circulating REAL DEFAULT 0.0,
                    total_pets_created INTEGER DEFAULT 0,
                    last_update TEXT
                )
            """)
            sys.stderr.write("DEBUG_DB: Game stats table checked/created.\n")

            self.conn.commit()
            sys.stderr.write("DEBUG_DB: _create_tables finished successfully.\n")
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error creating tables: {e}\n")
            raise

    def _initialize_game_stats(self):
        sys.stderr.write("DEBUG_DB: _initialize_game_stats started.\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT COUNT(*) FROM game_stats")
            count = cursor.fetchone()[0]
            if count == 0:
                from pet_config import TOTAL_INITIAL_SUPPLY
                initial_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
                cursor.execute(
                    "INSERT INTO game_stats (total_tamacoins_circulating, total_pets_created, last_update) VALUES (?, ?, ?)",
                    (TOTAL_INITIAL_SUPPLY, 0, initial_time)
                )
                self.conn.commit()
                sys.stderr.write(f"DEBUG_DB: Game stats initialized with TOTAL_INITIAL_SUPPLY: {TOTAL_INITIAL_SUPPLY}.\n")
            else:
                sys.stderr.write("DEBUG_DB: Game stats already initialized (row exists).\n")
            sys.stderr.write("DEBUG_DB: _initialize_game_stats finished successfully.\n")
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error initializing game stats: {e}\n")
            raise

    def create_user(self, telegram_id, username):
        sys.stderr.write(f"DEBUG_DB: create_user called for telegram_id: {telegram_id}, username: {username}\n")
        try:
            cursor = self._get_cursor()
            from pet_config import INITIAL_TAMACIONS_BALANCE
            cursor.execute(
                "INSERT INTO users (telegram_id, username, balance, daily_bonus_last_claimed) VALUES (?, ?, ?, ?)",
                (telegram_id, username, INITIAL_TAMACIONS_BALANCE, datetime.datetime.now(datetime.timezone.utc).isoformat())
            )
            self.conn.commit()
            new_user_id = cursor.lastrowid
            sys.stderr.write(f"DEBUG_DB: User created: id={new_user_id}, telegram_id={telegram_id}, balance={INITIAL_TAMACIONS_BALANCE}.\n")
            return self.get_user(telegram_id)
        except sqlite3.IntegrityError:
            sys.stderr.write(f"WARNING_DB: User with telegram_id {telegram_id} already exists. Returning existing user.\n")
            return self.get_user(telegram_id)
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error creating user {telegram_id}: {e}\n")
            return None

    def get_user(self, telegram_id):
        sys.stderr.write(f"DEBUG_DB: get_user called for telegram_id: {telegram_id}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()
            if user:
                user_dict = dict(user)
                sys.stderr.write(f"DEBUG_DB: User found: {user_dict['username']} (ID: {user_dict['id']}).\n")
                return user_dict
            sys.stderr.write(f"DEBUG_DB: User with telegram_id {telegram_id} not found.\n")
            return None
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error getting user {telegram_id}: {e}\n")
            return None

    def update_user_balance(self, user_id, amount):
        sys.stderr.write(f"DEBUG_DB: update_user_balance called for user_id: {user_id}, amount: {amount}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
            self.conn.commit()
            sys.stderr.write(f"DEBUG_DB: User {user_id} balance updated by {amount}.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error updating user {user_id} balance: {e}\n")
            return False

    def update_user_pet_id(self, user_id, pet_id):
        sys.stderr.write(f"DEBUG_DB: update_user_pet_id called for user_id: {user_id}, pet_id: {pet_id}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE users SET pet_id = ? WHERE id = ?", (pet_id, user_id))
            self.conn.commit()
            sys.stderr.write(f"DEBUG_DB: User {user_id} pet_id updated to {pet_id}.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error updating user {user_id} pet_id: {e}\n")
            return False

    def update_daily_bonus_time(self, user_id, timestamp):
        sys.stderr.write(f"DEBUG_DB: update_daily_bonus_time called for user_id: {user_id}, timestamp: {timestamp}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE users SET daily_bonus_last_claimed = ? WHERE id = ?", (timestamp, user_id))
            self.conn.commit()
            sys.stderr.write(f"DEBUG_DB: User {user_id} daily_bonus_last_claimed updated.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error updating daily bonus time for user {user_id}: {e}\n")
            return False

    def create_pet(self, owner_id, pet_type, name):
        sys.stderr.write(f"DEBUG_DB: create_pet called for owner_id: {owner_id}, pet_type: {pet_type}, name: {name}\n")
        try:
            cursor = self._get_cursor()
            current_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO pets (owner_id, pet_type, name, last_state_update, last_action_time) VALUES (?, ?, ?, ?, ?)",
                (owner_id, pet_type, name, current_time, current_time)
            )
            self.conn.commit()
            new_pet_id = cursor.lastrowid
            self.update_user_pet_id(owner_id, new_pet_id)
            self.increment_total_pets_created()
            sys.stderr.write(f"DEBUG_DB: Pet created: id={new_pet_id}, owner_id={owner_id}, type={pet_type}, name={name}.\n")
            return self.get_pet(owner_id)
        except sqlite3.IntegrityError:
            sys.stderr.write(f"WARNING_DB: Pet for owner_id {owner_id} already exists. Cannot create duplicate.\n")
            return None
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error creating pet for owner_id {owner_id}: {e}\n")
            return None

    def get_pet(self, owner_id):
        sys.stderr.write(f"DEBUG_DB: get_pet called for owner_id: {owner_id}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT * FROM pets WHERE owner_id = ?", (owner_id,))
            pet = cursor.fetchone()
            if pet:
                pet_dict = dict(pet)
                sys.stderr.write(f"DEBUG_DB: Pet found for owner {owner_id}: {pet_dict['name']} (ID: {pet_dict['id']}).\n")
                return pet_dict
            sys.stderr.write(f"DEBUG_DB: Pet not found for owner_id {owner_id}.\n")
            return None
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error getting pet for owner_id {owner_id}: {e}\n")
            return None

    def update_pet_state(self, owner_id, hunger, happiness, health, last_state_update):
        sys.stderr.write(f"DEBUG_DB: update_pet_state called for owner_id: {owner_id}, hunger: {hunger}, happiness: {happiness}, health: {health}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "UPDATE pets SET hunger = ?, happiness = ?, health = ?, last_state_update = ? WHERE owner_id = ?",
                (hunger, happiness, health, last_state_update, owner_id)
            )
            self.conn.commit()
            sys.stderr.write(f"DEBUG_DB: Pet state updated for owner_id {owner_id}.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error updating pet state for owner_id {owner_id}: {e}\n")
            return False

    def update_pet_action_time(self, owner_id, last_action_time):
        sys.stderr.write(f"DEBUG_DB: update_pet_action_time called for owner_id: {owner_id}, time: {last_action_time}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE pets SET last_action_time = ? WHERE owner_id = ?", (last_action_time, owner_id))
            self.conn.commit()
            sys.stderr.write(f"DEBUG_DB: Pet last_action_time updated for owner_id {owner_id}.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error updating pet action time for owner_id {owner_id}: {e}\n")
            return False

    def kill_pet(self, owner_id):
        sys.stderr.write(f"DEBUG_DB: kill_pet called for owner_id: {owner_id}\n")
        try:
            cursor = self._get_cursor()
            cursor.execute(
                "UPDATE pets SET is_alive = 0, hunger = 0.0, happiness = 0.0, health = 0.0 WHERE owner_id = ?",
                (owner_id,)
            )
            self.conn.commit()
            sys.stderr.write(f"DEBUG_DB: Pet for owner_id {owner_id} marked as dead.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error killing pet for owner_id {owner_id}: {e}\n")
            return False

    def increment_total_pets_created(self):
        sys.stderr.write("DEBUG_DB: increment_total_pets_created called.\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("UPDATE game_stats SET total_pets_created = total_pets_created + 1, last_update = ?",
                           (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
            self.conn.commit()
            sys.stderr.write("DEBUG_DB: total_pets_created incremented.\n")
            return True
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error incrementing total_pets_created: {e}\n")
            return False

    def get_game_stats(self):
        sys.stderr.write("DEBUG_DB: get_game_stats called.\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT * FROM game_stats LIMIT 1")
            stats = cursor.fetchone()
            if stats:
                stats_dict = dict(stats)
                sys.stderr.write(f"DEBUG_DB: Game stats retrieved: {stats_dict}.\n")
                return stats_dict
            sys.stderr.write("DEBUG_DB: No game stats found.\n")
            return None
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error getting game stats: {e}\n")
            return None

    def get_total_users_count(self):
        sys.stderr.write("DEBUG_DB: get_total_users_count called.\n")
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            sys.stderr.write(f"DEBUG_DB: Total users count: {count}.\n")
            return count
        except sqlite3.Error as e:
            sys.stderr.write(f"ERROR_DB: Error getting total users count: {e}\n")
            return 0

try:
    db = DBManager()
    sys.stderr.write("DEBUG_DB: Global DBManager instance initialization completed successfully.\n")
except Exception as e:
    sys.stderr.write(f"FATAL_ERROR: Failed to initialize DBManager: {e}\n")
    import traceback
    sys.stderr.write(traceback.format_exc())
    db = None
