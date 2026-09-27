from requests_log import append_request, read_requests


def test_read_requests_returns_empty_list_when_no_log(tmp_path):
    assert read_requests(tmp_path) == []


def test_append_request_returns_incrementing_iteration_numbers(tmp_path):
    first = append_request(tmp_path, "Маршрут у Бажуково, 10 км, кольцевой", "первая версия маршрута")
    second = append_request(tmp_path, "Замени точку А на музей", "заменена точка интереса")

    assert first == 1
    assert second == 2


def test_appended_requests_are_stored_verbatim_and_in_order(tmp_path):
    append_request(tmp_path, "Маршрут «у реки», ~5 часов", "построен маршрут")
    append_request(tmp_path, "Сделай его короче", "уменьшен бюджет до 8 км")

    entries = read_requests(tmp_path)

    assert len(entries) == 2
    assert entries[0]["iteration"] == 1
    assert entries[0]["request"] == "Маршрут «у реки», ~5 часов"
    assert entries[1]["iteration"] == 2
    assert entries[1]["request"] == "Сделай его короче"
    assert entries[1]["summary"] == "уменьшен бюджет до 8 км"
