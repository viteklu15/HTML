# app.py — Flask + index.html + API
from flask import Flask, render_template, request, Response, jsonify

state = {
    "power": True,  # Питание модема (вкл/выкл)
    "wifi_on": True,  # Состояние Wi-Fi (вкл/выкл)
    "mac": "12.34.56.78",  # MAC-адрес / идентификатор устройства
    "temp_c": 45,  # Температура устройства (°C)
    "coords": {"lat": 55.73, "lng": 37.61},  # Геокоординаты: широта/долгота
    # верхняя линейка статусов
    "coords_status": "pending",  # Статус координат (pending|ok|err)
    "gps_status": "pending",  # Статус GPS связи (pending|ok|err)
    "inet_status": "pending",  # Статус интернета (pending|ok|err)
    "rx": {"progress": 0},  # Прогресс приёма данных (0–100%)
    "tx": {"progress": 0},  # Прогресс передачи данных (0–100%)
    # экран «Идёт подключение…»
    "attempt": 1,  # Номер попытки подключения
    # общая индикация
    "system": "pending",  # Состояние системы (pending|ok|warn|err|off)
    "modem_off_temp": False,  # Автовыключение модема при перегреве (True/False)
    # углы антенного поста
    "angles": {
        "tilt_current": 123,  # Угол наклона текущий
        "tilt_required": 456,  # Угол наклона требуемый
        "rotate_current": 1860,  # Угол поворота текущий
        "rotate_required": 1860,  # Угол поворота требуемый
    },
    # новые поля под скрин
    "beam_number": 34,  # Номер луча в РЧ кластере
    "rf_cluster_polarization": "31/A",  # РЧ кластер / поляризация
    # пароль Wi-Fi храним открыто
    "wifi_password": "12345678",
    # логи (максимум 10 последних строк)
    "logs": ["log1", "log2"],
}

app = Flask(__name__)


@app.route("/")  #главная траница 
def index():
    return render_template("index.html")


@app.route("/api/state")  # запрос данных с сервера 
def api_state():
    return jsonify(state)


@app.route("/api/modem/power") #  для ON/OFF модема 
def modem_power():
    value = request.args.get("state")
    print(f"[API] /api/modem/power?state={value}")
    return Response(status=200)  # пустой ответ "OK"


@app.route("/api/modem/off-temp") #  для ON/OFF процедуры выключения при перегреве 
def modem_off_temp():
    value = request.args.get("state")
    print(f"[API] /api/modem/off-temp?state={value}")
    return Response(status=200)  # тоже пустой ответ


@app.route("/api/wifi") #  для ON/OFF WIFI
def wifi_state():
    value = request.args.get("state")
    print(f"[API] /api/wifi?state={value}")
    return Response(status=200)  # и здесь


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
