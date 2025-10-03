# app.py — супер-минимум: только Flask, только localhost, TCP:8080
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "OK: Flask жив! Откройте http://127.0.0.1:8080/"

if __name__ == "__main__":
    # слушаем ТОЛЬКО localhost, чтобы обойти любые блокировки внешних интерфейсов
    app.run(host="127.0.0.1", port=5000)
