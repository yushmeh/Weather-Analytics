import sqlite3
import sys
import json

import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ─────────────────────────────────────────────
# Константы
# ─────────────────────────────────────────────

API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=55.75&longitude=37.62"
    "&daily=temperature_2m_max,temperature_2m_min"
    "&timezone=Europe/Moscow"
    "&past_days=7"
)

DB_PATH = "weather.db"
TABLE_NAME = "weather_log"


# ─────────────────────────────────────────────
# 1. Получение данных из API
# ─────────────────────────────────────────────

def fetch_weather_data(url: str) -> dict:
    """
    Делает GET-запрос к API Open-Meteo и возвращает JSON как словарь.
    Прерывает программу при ошибке сети или неверном статусе.
    """
    print("🌐 Отправляем запрос к API Open-Meteo...")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        sys.exit("❌ Ошибка: нет подключения к интернету.")
    except requests.exceptions.Timeout:
        sys.exit("❌ Ошибка: сервер не ответил вовремя (таймаут 10 с).")
    except requests.exceptions.HTTPError as e:
        sys.exit(f"❌ HTTP-ошибка: {e}")

    print("✅ Данные успешно получены.\n")
    return response.json()


# ─────────────────────────────────────────────
# 2. Парсинг JSON
# ─────────────────────────────────────────────

def parse_weather_records(data: dict) -> list[tuple[str, float, float]]:
    """
    Извлекает из JSON списки дат, максимальных и минимальных температур.
    Возвращает список кортежей (date, temp_max, temp_min).
    Берёт только первые 7 записей (прошедшие дни).
    """
    try:
        daily = data["daily"]
        dates    = daily["time"]
        temp_max = daily["temperature_2m_max"]
        temp_min = daily["temperature_2m_min"]
    except KeyError as e:
        sys.exit(f"❌ Неожиданная структура JSON: отсутствует ключ {e}")

    # API может вернуть 8 дней (7 прошлых + сегодня), берём первые 7
    records = list(zip(dates, temp_max, temp_min))[:7]

    if not records:
        sys.exit("❌ API вернул пустой список дней.")

    return records


# ─────────────────────────────────────────────
# 3. Работа с SQLite
# ─────────────────────────────────────────────

def get_connection(db_path: str) -> sqlite3.Connection:
    """Открывает соединение с базой данных SQLite."""
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        sys.exit(f"❌ Не удалось подключиться к базе данных: {e}")


def create_table(conn: sqlite3.Connection) -> None:
    """
    Создаёт таблицу weather_log, если она ещё не существует.
    Структура: date TEXT, temp_max REAL, temp_min REAL.
    """
    sql = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            date     TEXT PRIMARY KEY,
            temp_max REAL NOT NULL,
            temp_min REAL NOT NULL
        )
    """
    try:
        conn.execute(sql)
        conn.commit()
        print(f"📋 Таблица «{TABLE_NAME}» готова.")
    except sqlite3.Error as e:
        sys.exit(f"❌ Ошибка создания таблицы: {e}")


def save_records(conn: sqlite3.Connection,
                 records: list[tuple[str, float, float]]) -> None:
    """
    Вставляет записи в таблицу.
    При повторном запуске перезаписывает существующие строки (UPSERT).
    """
    sql = f"""
        INSERT OR REPLACE INTO {TABLE_NAME} (date, temp_max, temp_min)
        VALUES (?, ?, ?)
    """
    try:
        conn.executemany(sql, records)
        conn.commit()
        print(f"💾 Сохранено {len(records)} записей в базу данных.\n")
    except sqlite3.Error as e:
        sys.exit(f"❌ Ошибка записи в базу данных: {e}")


def load_records(conn: sqlite3.Connection) -> list[tuple]:
    """Загружает все записи из таблицы, отсортированные по дате."""
    sql = f"SELECT date, temp_max, temp_min FROM {TABLE_NAME} ORDER BY date"
    try:
        cursor = conn.execute(sql)
        return cursor.fetchall()
    except sqlite3.Error as e:
        sys.exit(f"❌ Ошибка чтения из базы данных: {e}")


# ─────────────────────────────────────────────
# 4. Аналитика
# ─────────────────────────────────────────────

def calculate_analytics(records: list[tuple]) -> dict:
    """
    Принимает список кортежей (date, temp_max, temp_min).
    Возвращает словарь с аналитическими метриками.
    """
    dates    = [r[0] for r in records]
    max_vals = [r[1] for r in records]
    min_vals = [r[2] for r in records]

    avg_max = sum(max_vals) / len(max_vals)
    avg_min = sum(min_vals) / len(min_vals)

    warmest_idx = max_vals.index(max(max_vals))
    coldest_idx = min_vals.index(min(min_vals))

    temp_range = max(max_vals) - min(min_vals)

    return {
        "avg_max":      avg_max,
        "avg_min":      avg_min,
        "warmest_date": dates[warmest_idx],
        "warmest_temp": max_vals[warmest_idx],
        "coldest_date": dates[coldest_idx],
        "coldest_temp": min_vals[coldest_idx],
        "temp_range":   temp_range,
        "dates":        dates,
        "max_vals":     max_vals,
        "min_vals":     min_vals,
    }


def print_analytics(a: dict) -> None:
    """Красиво выводит аналитические метрики в консоль."""
    sep = "─" * 45

    print(sep)
    print("  📊  АНАЛИТИКА ПОГОДЫ ЗА 7 ДНЕЙ (Москва)")
    print(sep)
    print(f"  Средняя максимальная температура : {a['avg_max']:+.1f} °C")
    print(f"  Средняя минимальная температура  : {a['avg_min']:+.1f} °C")
    print(sep)
    print(f"  🌡️  Самый тёплый день  : {a['warmest_date']}  ({a['warmest_temp']:+.1f} °C)")
    print(f"  🥶  Самый холодный день: {a['coldest_date']}  ({a['coldest_temp']:+.1f} °C)")
    print(sep)
    print(f"  📐  Температурный размах за период: {a['temp_range']:.1f} °C")
    print(sep)
    print()

    # ASCII-таблица по дням
    print("  Дата          Макс.    Мин.")
    print("  " + "─" * 28)
    for date, tmax, tmin in zip(a["dates"], a["max_vals"], a["min_vals"]):
        print(f"  {date}   {tmax:+5.1f}   {tmin:+5.1f}")
    print()


# ─────────────────────────────────────────────
# 5. Визуализация (Plotly, offline)
# ─────────────────────────────────────────────

def build_chart(a: dict, output_file: str = "weather_dashboard.html") -> None:
    """
    Строит интерактивный график Plotly с двумя дорожками:
    — линейный график температур (макс. / мин.)
    — столбчатый график температурного диапазона дня
    Сохраняет HTML-файл для просмотра без интернета.
    """
    dates    = a["dates"]
    max_vals = a["max_vals"]
    min_vals = a["min_vals"]
    ranges   = [mx - mn for mx, mn in zip(max_vals, min_vals)]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        subplot_titles=(
            "Максимальная и минимальная температура (°C)",
            "Дневной температурный диапазон (°C)",
        ),
    )

    # ── Дорожка 1: линии макс / мин ──────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=dates, y=max_vals,
            name="Макс. температура",
            mode="lines+markers",
            line=dict(color="#E84545", width=2.5),
            marker=dict(size=7),
            hovertemplate="%{x}<br>Макс: %{y:.1f} °C<extra></extra>",
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=dates, y=min_vals,
            name="Мин. температура",
            mode="lines+markers",
            line=dict(color="#2B7BFF", width=2.5),
            marker=dict(size=7),
            fill="tonexty",
            fillcolor="rgba(100,160,255,0.15)",
            hovertemplate="%{x}<br>Мин: %{y:.1f} °C<extra></extra>",
        ),
        row=1, col=1,
    )

    # Горизонтальная линия 0 °C
    fig.add_hline(
        y=0, line_dash="dot", line_color="grey",
        annotation_text="0 °C", annotation_position="right",
        row=1, col=1,
    )

    # ── Дорожка 2: столбцы диапазона ─────────────────────────────────────
    fig.add_trace(
        go.Bar(
            x=dates, y=ranges,
            name="Диапазон дня",
            marker_color="#FFA500",
            hovertemplate="%{x}<br>Диапазон: %{y:.1f} °C<extra></extra>",
        ),
        row=2, col=1,
    )

    # ── Оформление ────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text="Погода в Москве — последние 7 дней",
            font=dict(size=20),
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=600,
        plot_bgcolor="#F9F9F9",
        paper_bgcolor="#FFFFFF",
    )
    fig.update_yaxes(title_text="Температура, °C", row=1, col=1, gridcolor="#E0E0E0")
    fig.update_yaxes(title_text="Диапазон, °C",    row=2, col=1, gridcolor="#E0E0E0")
    fig.update_xaxes(title_text="Дата", row=2, col=1)

    records_json = json.dumps([
        {"date": r[0], "temp_max": r[1], "temp_min": r[2]}
        for r in zip(a["dates"], a["max_vals"], a["min_vals"])
    ])

# ─────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────

def main() -> None:
    # 1. Получаем данные из API
    raw_data = fetch_weather_data(API_URL)

    # 2. Парсим JSON → список кортежей
    records = parse_weather_records(raw_data)

    # 3. Сохраняем в SQLite
    conn = get_connection(DB_PATH)
    create_table(conn)
    save_records(conn, records)

    # 4. Загружаем из БД (чтобы убедиться, что данные корректно сохранены)
    db_records = load_records(conn)
    conn.close()

    # 5. Рассчитываем аналитику и выводим её
    analytics = calculate_analytics(db_records)
    print_analytics(analytics)

    # 6. Строим интерактивный график
    build_chart(analytics)


if __name__ == "__main__":
    main()