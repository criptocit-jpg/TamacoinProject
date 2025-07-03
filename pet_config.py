# pet_config.py

# Соответствие ID питомца и его отображаемого имени на русском
PET_TYPES_DISPLAY = {
    "toothless": "Зубастик (Ночная Фурия)",
    "light_fury": "Белая Фурия (Дневная)",
    "stormfly": "Громгильда",
}

# Список ID питомцев, которые можно выбрать. Это ключи из PET_TYPES_DISPLAY
PET_IDS = list(PET_TYPES_DISPLAY.keys())

# Пути к изображениям. Используем ID питомцев
PET_IMAGES = {
    "toothless_normal": "toothless_normal.png",
    "light_fury_normal": "light_fury_normal.png",
    "stormfly_normal": "stormfly_normal.png",
    "toothless_hungry_sad": "toothless_hungry_sad.png",
    "light_fury_hungry_sad": "light_fury_hungry_sad.png",
    "stormfly_hungry_sad": "stormfly_hungry_sad.png",
    "toothless_sick": "toothless_sick.png",
    "light_fury_sick": "light_fury_sick.png",
    "stormfly_sick": "stormfly_sick.png",
    "grave": "grave.png", # Если используете
}

# Начальные параметры для всех питомцев
INITIAL_HEALTH = 100
INITIAL_HAPPINESS = 100
INITIAL_HUNGER = 0 # 0 - не голоден, 100 - очень голоден
INITIAL_TA_COIN = 100 # Начальный баланс Tamacoin

# Значения, на которые изменяются параметры при действиях
FEED_HUNGER_DECREASE = 20
FEED_HEALTH_INCREASE = 5
FEED_HAPPINESS_INCREASE = 5

PLAY_HAPPINESS_INCREASE = 20
PLAY_HUNGER_INCREASE = 10

CLEAN_HEALTH_INCREASE = 10
CLEAN_HAPPINESS_INCREASE = 5

# Настройки ухудшения состояния (если планируется фоновая деградация)
DEGRADATION_INTERVAL_SECONDS = 3600 # Раз в час
HUNGER_DEGRADATION_PER_INTERVAL = 5
HEALTH_DEGRADATION_PER_INTERVAL = 2
HAPPINESS_DEGRADATION_PER_INTERVAL = 3
