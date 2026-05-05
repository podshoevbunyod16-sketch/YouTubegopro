import requests

def run(args):
    if not args:
        return "Использование: /services [weather <город>|currency USD RUB|wiki запрос]"

    service = args[0]
    params = args[1:]

    if service == "weather":
        if not params:
            return "Укажите город: /services weather Moscow"
        city = " ".join(params)
        try:
            r = requests.get(f"https://wttr.in/{city}?format=3&lang=ru")
            return r.text
        except Exception as e:
            return f"Ошибка погоды: {e}"

    elif service == "currency":
        if len(params) < 2:
            return "Укажите две валюты: /services currency USD RUB"
        base = params[0].upper()
        target = params[1].upper()
        try:
            r = requests.get(f"https://api.exchangerate-api.com/v4/latest/{base}")
            data = r.json()
            rate = data["rates"].get(target, "не найдена")
            return f"1 {base} = {rate} {target}"
        except Exception as e:
            return f"Ошибка валют: {e}"

    elif service == "wiki":
        if not params:
            return "Укажите запрос: /services wiki Python"
        query = " ".join(params)
        try:
            r = requests.get(f"https://ru.wikipedia.org/api/rest_v1/page/summary/{query}")
            data = r.json()
            return data.get("extract", "Не найдено")
        except:
            return "Ошибка Википедии"

    else:
        return "Неизвестный сервис. Используйте weather/currency/wiki"