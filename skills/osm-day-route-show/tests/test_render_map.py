from render_map import lang_priority, t


def test_lang_priority_orders_user_local_english_deduplicated():
    assert lang_priority("ru", "ru") == ["ru", "en"]
    assert lang_priority("ru", "es") == ["ru", "es", "en"]


def test_t_falls_back_to_english_for_unknown_language():
    assert t("wikipedia", "xx") == t("wikipedia", "en")
