"""Strings of the hike-conditions features (recommended start, full-day forecast, ticks by terrain, nearby water).
English and Russian are complete; the other languages fall back to English like the rest of the plan. Merged into
`i18n.STRINGS` at import time (see the end of i18n.py)."""

CONDITION_STRINGS = {
    "en": {
        # recommended start
        "st_limits": {"sunrise": "sunrise", "start_open": "the start point opens",
                      "first_arrival": "the first public transport arrives", "sunset": "sunset",
                      "last_departure": "the last public transport back", "end_close": "the end point closes"},
        "st_no_limit": "no limit",
        "st_recommended": "Recommended start: **{start}** (a start is possible from {early} to {late}{pref}).",
        "st_pref": ", not earlier than 07:00 by preference",
        "st_warn_empty": "No start fits all limits: a start is possible only from {earliest} ({early}) but only until {latest} ({late}); the start used is {start}.",
        "st_transport_missing": "Not recorded: {what} — those transport limits are not applied to the recommended start.",
        "st_missing": {"first_arrival": "the first public transport to the start point",
                       "last_departure": "the last public transport back"},
    },
    "ru": {
        "st_limits": {"sunrise": "рассвет", "start_open": "открытие точки старта",
                      "first_arrival": "прибытие первого рейса", "sunset": "закат",
                      "last_departure": "последний рейс назад", "end_close": "закрытие точки финиша"},
        "st_no_limit": "без ограничения",
        "st_recommended": "Рекомендуемый старт: **{start}** (старт возможен с {early} до {late}{pref}).",
        "st_pref": ", не раньше 07:00 по предпочтению",
        "st_warn_empty": "Нет старта, подходящего под все ограничения: стартовать можно только с {earliest} ({early}), но не позже {latest} ({late}); взят старт {start}.",
        "st_transport_missing": "Не записано: {what} — эти ограничения по транспорту не учтены в рекомендуемом старте.",
        "st_missing": {"first_arrival": "первый рейс до точки старта", "last_departure": "последний рейс назад"},
    },
}

# plugin names for the progress lines: every language (a test requires it for every default plugin)
CONDITION_PLUGIN_NAMES = {lang: {} for lang in ("en", "ru", "es", "fr", "de", "pt", "it")}
