# -*- coding: utf-8 -*-
"""
Finance Tracker v1.0 by Арсений Гусев — локальный трекер личных финансов.

Разделы:
  • Дашборд       — карточки месяца, график за 6 месяцев, структура расходов
  • Транзакции    — все операции: поиск, фильтры, удаление в один клик
  • Бюджеты       — месячные лимиты с прогрессом и прогнозом
  • Финансы       — счета: пополнение/снятие (связываются с доходами и
                    расходами), переводы между счетами
  • Настройки     — тема, масштаб, градиент, валюта, категории, данные, хоткеи

Данные: SQLite в %APPDATA%/FinanceTracker/fintracker.db
Самопроверка слоя данных: python fintracker.py --selftest
"""
import calendar
import csv
import datetime as dt
import os
import random
import sqlite3
import sys
import tkinter as tk
from tkinter import messagebox, filedialog

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.ticker as mticker

# ---------------------------------------------------------------------------
# Пути, версия, константы
# ---------------------------------------------------------------------------

def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "FinanceTracker")
    os.makedirs(path, exist_ok=True)
    return path


DB_PATH = os.path.join(app_dir(), "fintracker.db")
APP_VERSION = "1.0"
AUTHOR = "Арсений Гусев"
WINDOW_TITLE = "Finance Tracker"
MIN_W, MIN_H = 880, 600

# ---------------------------------------------------------------------------
# Строгая монохромная палитра (кортежи CTk: (light, dark))
# ---------------------------------------------------------------------------

CARD = ("#ffffff", "#161a20")
CARD_INNER = ("#f4f6f8", "#1b2027")
BORDER = ("#e2e6eb", "#242a33")
MUTED = ("#6b7480", "#98a1ac")
GREEN = ("#15803d", "#34d399")
RED = ("#dc2626", "#f87171")
AMBER = ("#b45309", "#fbbf24")
PRIMARY = ("#15181d", "#eef1f4")          # строгие кнопки: чёрное на светлом, белое на тёмном
PRIMARY_HOVER = ("#2c323a", "#cfd5db")
PRIMARY_TEXT = ("#f7f8fa", "#101317")
SIDEBAR = ("#f4f6f8", "#0e1116")
SIDEBAR_HOVER = ("#e2e6ec", "#1c2129")
ROOT_BG = ("#e9ecef", "#0a0d11")
ENTRY_BG = ("#f0f2f5", "#10141a")

CORNER = 10          # слегка закруглённые кнопки
CARD_CORNER = 14

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MONTHS_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]

EXPENSE_CATEGORIES = [
    "Продукты", "Кафе и рестораны", "Транспорт", "Жильё и ЖКХ", "Здоровье",
    "Развлечения", "Одежда", "Образование", "Подписки", "Связь и интернет",
    "Подарки", "Путешествия", "Прочее",
]
INCOME_CATEGORIES = [
    "Зарплата", "Фриланс", "Премия", "Подарок", "Инвестиции", "Возврат средств", "Прочее",
]
DEFAULT_ACCOUNTS = ["Наличные", "Основная карта", "Сбережения"]
DEFAULT_CURRENCY = "₽"
CURRENCY_PRESETS = ["₽", "$", "€", "₸", "Br", "¥", "£", "₴", "zł"]
# строгая серо-синеграфитовая палитра для диаграмм
CHART_PALETTE = ["#8b98a8", "#5b6675", "#b7c0cc", "#3d4653", "#6e8fa3",
                 "#9fb3bf", "#46536b", "#c5ccd6", "#77889a", "#2f3947"]

HOTKEYS_HELP = [
    ("Ctrl + N", "Новая транзакция"),
    ("Ctrl + T", "Перевод между счетами"),
    ("Ctrl + 1 … 5", "Переход к разделу по номеру"),
    ("Alt + ← / →", "Предыдущий / следующий месяц"),
    ("Esc", "Закрыть диалог"),
]


# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()
        self._migrate()

    def _create_tables(self):
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK (kind IN ('expense','income')))""")
        c.execute("""CREATE TABLE IF NOT EXISTS accounts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        balance REAL NOT NULL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind TEXT NOT NULL CHECK (kind IN ('expense','income')),
                        amount REAL NOT NULL CHECK (amount > 0),
                        date TEXT NOT NULL,
                        category_id INTEGER,
                        account_id INTEGER,
                        note TEXT,
                        FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
                        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS budgets (
                        category_id INTEGER PRIMARY KEY,
                        monthly_limit REAL NOT NULL,
                        FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(category_id)")
        c.commit()

    def _migrate(self):
        cur = self.conn.cursor()
        if cur.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            for name in EXPENSE_CATEGORIES:
                cur.execute("INSERT INTO categories(name,kind) VALUES(?, 'expense')", (name,))
            for name in INCOME_CATEGORIES:
                cur.execute("INSERT INTO categories(name,kind) VALUES(?, 'income')", (name,))
        if cur.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
            for name in DEFAULT_ACCOUNTS:
                cur.execute("INSERT INTO accounts(name,balance) VALUES(?, 0)", (name,))
        self.conn.commit()

    # -- настройки ----------------------------------------------------------
    def get_setting(self, key, default=""):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    # -- категории ----------------------------------------------------------
    def categories(self, kind):
        return self.conn.execute(
            "SELECT id,name FROM categories WHERE kind=? ORDER BY name", (kind,)).fetchall()

    def add_category(self, name, kind):
        exists = self.conn.execute(
            "SELECT 1 FROM categories WHERE name=? AND kind=?", (name, kind)).fetchone()
        if exists:
            raise ValueError("Такая категория уже есть")
        self.conn.execute("INSERT INTO categories(name,kind) VALUES(?,?)", (name, kind))
        self.conn.commit()

    def delete_category(self, cat_id):
        """Транзакции категории сохраняются (метка «—»), бюджет удаляется."""
        self.conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        self.conn.commit()

    # -- счета ----------------------------------------------------------------
    def accounts(self):
        return self.conn.execute(
            "SELECT id,name,balance FROM accounts ORDER BY id").fetchall()

    def add_account(self, name, balance=0.0):
        self.conn.execute("INSERT INTO accounts(name,balance) VALUES(?,?)", (name, balance))
        self.conn.commit()

    def rename_account(self, acc_id, name):
        self.conn.execute("UPDATE accounts SET name=? WHERE id=?", (name, acc_id))
        self.conn.commit()

    def delete_account(self, acc_id):
        self.conn.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
        self.conn.commit()

    def account_tx_count(self, acc_id):
        return self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id=?", (acc_id,)).fetchone()[0]

    def recalc_balance(self, acc_id):
        row = self.conn.execute(
            """SELECT COALESCE(SUM(CASE kind WHEN 'income' THEN amount ELSE -amount END), 0)
               FROM transactions WHERE account_id=?""", (acc_id,)).fetchone()
        self.conn.execute("UPDATE accounts SET balance=? WHERE id=?", (row[0], acc_id))
        self.conn.commit()

    def recalc_all_balances(self):
        for (aid,) in self.conn.execute("SELECT id FROM accounts").fetchall():
            self.recalc_balance(aid)

    def net_worth(self):
        return self.conn.execute(
            "SELECT COALESCE(SUM(balance),0) FROM accounts").fetchone()[0] or 0.0

    # -- транзакции ------------------------------------------------------------
    def add_transaction(self, kind, amount, date, category_id, account_id, note,
                        skip_balance=False):
        cur = self.conn.execute(
            "INSERT INTO transactions(kind,amount,date,category_id,account_id,note) "
            "VALUES(?,?,?,?,?,?)",
            (kind, float(amount), date, category_id, account_id, note or ""))
        tx_id = cur.lastrowid
        self.conn.commit()
        if not skip_balance and account_id is not None:
            self.recalc_balance(account_id)
        return tx_id

    def delete_transaction(self, tx_id):
        row = self.conn.execute(
            "SELECT account_id FROM transactions WHERE id=?", (tx_id,)).fetchone()
        self.conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        self.conn.commit()
        if row and row[0] is not None:
            self.recalc_balance(row[0])

    def transfer(self, from_id, to_id, amount, date, note=""):
        """Перевод: расход на исходном счёте и доход на целевом."""
        cat = self.conn.execute(
            "SELECT id FROM categories WHERE kind='expense' AND name='Прочее' LIMIT 1").fetchone()
        cat_id = cat[0] if cat else None
        label = f"Перевод: {note}" if note else "Перевод"
        t1 = self.add_transaction("expense", amount, date, cat_id, from_id, label)
        t2 = self.add_transaction("income", amount, date, cat_id, to_id, label)
        return t1, t2

    def fetch_transactions(self, year=None, month=None, kind=None, search="",
                           limit=None, desc=True, account_id=None):
        q = """SELECT t.id, t.kind, t.amount, t.date,
                      COALESCE(c.name,'—'), COALESCE(a.name,'—'), COALESCE(t.note,'')
               FROM transactions t
               LEFT JOIN categories c ON c.id = t.category_id
               LEFT JOIN accounts a ON a.id = t.account_id
               WHERE 1=1"""
        p = []
        if year:
            q += " AND CAST(substr(t.date,1,4) AS INTEGER)=?"
            p.append(year)
        if month:
            q += " AND CAST(substr(t.date,6,2) AS INTEGER)=?"
            p.append(month)
        if kind:
            q += " AND t.kind=?"
            p.append(kind)
        if account_id is not None:
            q += " AND t.account_id=?"
            p.append(account_id)
        if search:
            q += " AND (COALESCE(t.note,'') LIKE ? OR COALESCE(c.name,'') LIKE ?)"
            p += [f"%{search}%", f"%{search}%"]
        q += " ORDER BY t.date DESC, t.id DESC" if desc else " ORDER BY t.date ASC, t.id ASC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return self.conn.execute(q, p).fetchall()

    def count_transactions(self):
        return self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

    def month_totals(self, year, month):
        row = self.conn.execute(
            """SELECT
                COALESCE(SUM(CASE kind WHEN 'income' THEN amount ELSE 0 END),0),
                COALESCE(SUM(CASE kind WHEN 'expense' THEN amount ELSE 0 END),0)
               FROM transactions
               WHERE CAST(substr(date,1,4) AS INTEGER)=?
                 AND CAST(substr(date,6,2) AS INTEGER)=?""",
            (year, month)).fetchone()
        return {"income": row[0] or 0.0, "expense": row[1] or 0.0}

    def expenses_by_category(self, year, month):
        return self.conn.execute(
            """SELECT COALESCE(c.name,'—') AS cat, SUM(t.amount) AS total
               FROM transactions t
               LEFT JOIN categories c ON c.id=t.category_id
               WHERE t.kind='expense'
                 AND CAST(substr(t.date,1,4) AS INTEGER)=?
                 AND CAST(substr(t.date,6,2) AS INTEGER)=?
               GROUP BY cat ORDER BY total DESC""", (year, month)).fetchall()

    def last_months_totals(self, n):
        today = dt.date.today()
        out = []
        y, m = today.year, today.month
        for _ in range(n):
            t = self.month_totals(y, m)
            out.append((y, m, t["income"], t["expense"]))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        out.reverse()
        return out

    # -- бюджеты ---------------------------------------------------------------
    def budgets(self):
        return self.conn.execute(
            """SELECT b.category_id, c.name, b.monthly_limit
               FROM budgets b JOIN categories c ON c.id=b.category_id
               ORDER BY c.name""").fetchall()

    def set_budget(self, category_id, limit):
        if limit <= 0:
            self.conn.execute("DELETE FROM budgets WHERE category_id=?", (category_id,))
        else:
            self.conn.execute(
                "INSERT INTO budgets(category_id,monthly_limit) VALUES(?,?) "
                "ON CONFLICT(category_id) DO UPDATE SET monthly_limit=excluded.monthly_limit",
                (category_id, float(limit)))
        self.conn.commit()

    def budget_progress(self, category_id, year, month):
        row = self.conn.execute(
            """SELECT COALESCE(SUM(amount),0) FROM transactions
               WHERE kind='expense' AND category_id=?
                 AND CAST(substr(date,1,4) AS INTEGER)=?
                 AND CAST(substr(date,6,2) AS INTEGER)=?""",
            (category_id, year, month)).fetchone()
        return row[0] or 0.0

    # -- экспорт / демо ---------------------------------------------------------
    def export_csv(self, filepath):
        rows = self.fetch_transactions(desc=False)
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Дата", "Тип", "Категория", "Счёт", "Сумма", "Заметка"])
            for _, kind, amount, date, cat, acc, note in rows:
                w.writerow([date, "Доход" if kind == "income" else "Расход",
                            cat, acc, f"{amount:.2f}", note])
        return len(rows)

    def load_demo_data(self):
        today = dt.date.today()
        cats = dict((name, cid) for cid, name in self.categories("expense"))
        incats = dict((name, cid) for cid, name in self.categories("income"))
        accs = [a[0] for a in self.accounts()]
        if not accs:
            self.add_account("Наличные")
            accs = [a[0] for a in self.accounts()]
        rng = random.Random(42)
        n = 0
        amounts = {
            "Продукты": (300, 5500), "Кафе и рестораны": (250, 2600),
            "Транспорт": (60, 900), "Жильё и ЖКХ": (4500, 9000),
            "Здоровье": (400, 4500), "Развлечения": (300, 3800),
            "Одежда": (800, 7500), "Образование": (500, 4000),
            "Подписки": (169, 799), "Связь и интернет": (350, 900),
            "Подарки": (500, 5000), "Путешествия": (3000, 25000),
            "Прочее": (150, 2200),
        }
        notes = {
            "Продукты": ["Пятёрочка", "Магнит", "ВкусВилл", "Лента", "Ашан"],
            "Кафе и рестораны": ["Кофейня", "Обед", "Пиццерия", "Суши"],
            "Транспорт": ["Метро", "Такси", "Каршеринг", "Автобус"],
            "Развлечения": ["Кино", "Концерт", "Игры", "Музей"],
            "Подписки": ["Плюс", "Кинопоиск", "Музыка", "Облако"],
        }
        weights = [22, 12, 10, 8, 6, 8, 5, 3, 4, 3, 2, 3, 4]
        for back in range(5, -1, -1):
            y, m = shift_month(today.year, today.month, -back)
            last_day = calendar.monthrange(y, m)[1]
            if "Зарплата" in incats:
                self.add_transaction(
                    "income", round(rng.uniform(115000, 135000), 2),
                    f"{y:04d}-{m:02d}-05", incats["Зарплата"], rng.choice(accs),
                    "Зарплата", skip_balance=True)
                n += 1
            if rng.random() < 0.6 and "Фриланс" in incats:
                self.add_transaction(
                    "income", round(rng.uniform(8000, 35000), 2),
                    f"{y:04d}-{m:02d}-{rng.randint(10, 25):02d}",
                    incats["Фриланс"], rng.choice(accs), "Проект на заказ",
                    skip_balance=True)
                n += 1
            cat_names = [c for c in amounts if c in cats]
            cat_weights = [weights[list(amounts).index(c)] for c in cat_names]
            for _ in range(rng.randint(28, 45)):
                day = rng.randint(1, last_day)
                if (y, m) == (today.year, today.month) and day > today.day:
                    day = today.day
                cat = rng.choices(cat_names, weights=cat_weights)[0]
                note = rng.choice(notes.get(cat, ["", "", "Покупка"]))
                self.add_transaction(
                    "expense", round(rng.uniform(*amounts[cat]), 2),
                    f"{y:04d}-{m:02d}-{day:02d}", cats[cat], rng.choice(accs),
                    note, skip_balance=True)
                n += 1
        for cname, lim in [("Продукты", 25000), ("Кафе и рестораны", 8000),
                           ("Транспорт", 5000), ("Развлечения", 6000),
                           ("Подписки", 1500)]:
            if cname in cats:
                self.set_budget(cats[cname], lim)
        self.recalc_all_balances()
        return n

    def wipe_data(self):
        for t in ("transactions", "budgets", "accounts", "categories"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
        self._migrate()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def shift_month(y, m, delta):
    m += delta
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return y, m


def fmt_money(v, cur):
    v = float(v)
    if abs(v) >= 1_000_000:
        s = f"{v/1_000_000:,.2f} млн"
    else:
        s = f"{v:,.0f}" if abs(v - round(v)) < 0.005 else f"{v:,.2f}"
    return f"{s} {cur}".replace(",", " ")


def month_label(y, m):
    return f"{MONTHS_RU[m-1]} {y}"


def parse_date(s):
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def today_str():
    return dt.date.today().isoformat()


def greeting():
    h = dt.datetime.now().hour
    if 5 <= h < 12:
        return "Доброе утро"
    if 12 <= h < 18:
        return "Добрый день"
    if 18 <= h < 23:
        return "Добрый вечер"
    return "Доброй ночи"


class Theme:
    """Цвета matplotlib-графиков под текущий режим CTk."""

    @staticmethod
    def is_dark():
        return ctk.get_appearance_mode() == "Dark"

    @staticmethod
    def colors():
        dark = Theme.is_dark()
        if dark:
            return {"card": "#161a20", "fg": "#e8eaed", "grid": "#262c34",
                    "muted": "#98a1ac", "income": "#34d399", "expense": "#f87171",
                    "accent": "#c7ced8", "neutral": "#8b98a8"}
        return {"card": "#ffffff", "fg": "#1f242b", "grid": "#e2e6ea",
                "muted": "#6b7480", "income": "#15803d", "expense": "#dc2626",
                "accent": "#374151", "neutral": "#6b7280"}


def style_ax(ax, tc):
    """Строгий стиль осей matplotlib."""
    ax.set_facecolor(tc["card"])
    ax.tick_params(colors=tc["muted"], labelsize=8, length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.grid(axis="y", color=tc["grid"], linewidth=0.7, zorder=0)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v/1000:,.0f}k" if abs(v) >= 10000 else
        (f"{v/1000:,.1f}k" if abs(v) >= 1000 else f"{v:,.0f}")))


def style_legend(leg, tc):
    leg.set_frame_on(False)
    for t in leg.get_texts():
        t.set_color(tc["muted"])
        t.set_fontsize(8)


# ---------------------------------------------------------------------------
# Градиентный фон (статичный кадр)
# ---------------------------------------------------------------------------

GRAD_DARK = [(10, 13, 17), (18, 27, 36), (12, 33, 29), (24, 24, 32)]
GRAD_LIGHT = [(238, 241, 245), (224, 233, 244), (230, 240, 233), (236, 234, 244)]


def _lerp3(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def gradient_image(w, h, phase, dark):
    """Кадр диагонального градиента: низкое разрешение + мягкий апскейл."""
    lw, lh = 128, 72
    xs = np.linspace(0.0, 1.0, lw)
    ys = np.linspace(0.0, 1.0, lh)
    X, Y = np.meshgrid(xs, ys)
    ang = 0.6 + phase * 0.18
    coord = X * np.cos(ang) + Y * np.sin(ang)
    coord -= coord.min()
    coord /= (coord.max() + 1e-9)
    pal = GRAD_DARK if dark else GRAD_LIGHT
    t1 = (np.sin(phase) + 1) / 2
    t2 = (np.sin(phase * 0.73 + 2.1) + 1) / 2
    c1 = _lerp3(pal[0], pal[1], t1)
    c2 = _lerp3(pal[2], pal[3], t2)
    img = np.empty((lh, lw, 3), dtype=np.uint8)
    for ch in range(3):
        img[..., ch] = (c1[ch] + (c2[ch] - c1[ch]) * coord).astype(np.uint8)
    im = Image.fromarray(img).resize((max(w, 2), max(h, 2)), Image.BILINEAR)
    return ImageTk.PhotoImage(im)


# ---------------------------------------------------------------------------
# Виджеты
# ---------------------------------------------------------------------------

class GhostButton(ctk.CTkButton):
    """Кнопка с обводкой — вторичное действие."""
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", "transparent")
        kw.setdefault("hover_color", CARD_INNER)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDER)
        kw.setdefault("corner_radius", CORNER)
        kw.setdefault("text_color", ("#20242b", "#e6e9ee"))
        super().__init__(master, **kw)


class PrimaryButton(ctk.CTkButton):
    """Строгая контрастная кнопка — главное действие."""
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", PRIMARY)
        kw.setdefault("hover_color", PRIMARY_HOVER)
        kw.setdefault("text_color", PRIMARY_TEXT)
        kw.setdefault("corner_radius", CORNER)
        kw.setdefault("font", ctk.CTkFont(size=13, weight="bold"))
        super().__init__(master, **kw)


class IconButton(ctk.CTkButton):
    """Маленькая квадратная кнопка-символ (✕, ✎)."""
    def __init__(self, master, text, hover=RED, **kw):
        kw.setdefault("width", 28)
        kw.setdefault("height", 26)
        kw.setdefault("corner_radius", 8)
        kw.setdefault("fg_color", "transparent")
        kw.setdefault("hover_color", hover)
        kw.setdefault("text_color", MUTED)
        kw.setdefault("font", ctk.CTkFont(size=12))
        super().__init__(master, text=text, **kw)


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


class AnimatedLabel:
    """Плавный счётчик для KPI-значений: число набирается за ~0.4 с."""

    def __init__(self, label, fmt):
        self.label = label
        self.fmt = fmt              # (value) -> str
        self._target = 0.0
        self._current = 0.0
        self._job = None

    def set_value(self, target: float):
        self._target = float(target)
        start = self._current
        delta = self._target - start
        steps = 12
        if abs(delta) < 0.01 or not self.label.winfo_exists():
            self._current = self._target
            self.label.configure(text=self.fmt(self._target))
            return
        if self._job:
            self.label.after_cancel(self._job)

        def step(i=1):
            t = ease_out_cubic(min(i / steps, 1.0))
            self._current = start + delta * t
            self.label.configure(text=self.fmt(self._current))
            if i < steps and self.label.winfo_exists():
                self._job = self.label.after(33, lambda: step(i + 1))
            else:
                self._current = self._target
                self.label.configure(text=self.fmt(self._target))

        step()


class AnimatedBar(ctk.CTkProgressBar):
    """Прогресс-бар с плавным заполнением и цветом по порогу."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._job = None

    def animate_to(self, spent, limit):
        pct = min(spent / limit, 1.0) if limit > 0 else 0.0
        color = GREEN if pct < 0.75 else (AMBER if pct < 1.0 else RED)
        self.configure(progress_color=color)
        start = self.get()
        steps = 14
        if self._job:
            self.after_cancel(self._job)

        def step(i=1):
            t = ease_out_cubic(min(i / steps, 1.0))
            self.set(start + (pct - start) * t)
            if i < steps and self.winfo_exists():
                self._job = self.after(28, lambda: step(i + 1))
            else:
                self.set(pct)

        step()
        return pct


def make_kpi(parent, title, color, title_size=12, value_size=22):
    frame = ctk.CTkFrame(parent, corner_radius=CARD_CORNER, fg_color=CARD,
                         border_width=1, border_color=BORDER)
    ctk.CTkLabel(frame, text=title, text_color=color,
                 font=ctk.CTkFont(size=title_size, weight="bold")).pack(
        anchor="w", padx=16, pady=(12, 0))
    val = ctk.CTkLabel(frame, text="—", font=ctk.CTkFont(size=value_size, weight="bold"))
    val.pack(anchor="w", padx=16, pady=(2, 0))
    sub = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=11), text_color=MUTED)
    sub.pack(anchor="w", padx=16, pady=(0, 12))
    return {"frame": frame, "value": val, "sub": sub}


class ChartCard(ctk.CTkFrame):
    """Карточка с matplotlib-графиком: canvas создаётся один раз,
    при перерисовке меняется только содержимое фигуры (без мерцания)."""

    def __init__(self, master, title, draw_fn, height=250):
        super().__init__(master, corner_radius=CARD_CORNER, fg_color=CARD,
                         border_width=1, border_color=BORDER, height=height)
        self.pack_propagate(False)
        self.draw_fn = draw_fn          # (fig, w_px, h_px, tc) -> None
        self._last = (0, 0)
        self._job = None
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 0))
        self.title_lbl = ctk.CTkLabel(head, text=title,
                                      font=ctk.CTkFont(size=13, weight="bold"))
        self.title_lbl.pack(side="left")
        self.head_extra = head
        self.holder = ctk.CTkFrame(self, fg_color="transparent")
        self.holder.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.fig = Figure(figsize=(4, 2.4), dpi=100)
        self.fc = FigureCanvasTkAgg(self.fig, master=self.holder)
        self._wid = self.fc.get_tk_widget()
        self._wid.configure(highlightthickness=0)
        self._wid.pack(fill="both", expand=True)
        self.holder.bind("<Configure>", self._on_conf)

    def set_title(self, text):
        self.title_lbl.configure(text=text)

    def _on_conf(self, e):
        # дебаунс длиннее времени перерисовки (~150 мс): иначе цепочка
        # «перерисовка → resize → перерисовка» не даёт очереди событий опустеть
        if (e.width, e.height) == self._last:
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(250, self.redraw)

    def redraw(self):
        self._job = None
        if not self._wid.winfo_exists():
            return
        w, h = self.holder.winfo_width(), self.holder.winfo_height()
        if w < 30 or h < 30:
            return
        self._last = (w, h)
        tc = Theme.colors()
        self.fig.set_size_inches(w / 100, h / 100)
        self.fig.set_facecolor(tc["card"])
        self.fig.clear()
        self.draw_fn(self.fig, w, h, tc)
        self._wid.configure(bg=tc["card"])
        self.fc.draw()

    def refresh(self):
        self._last = (0, 0)
        self.redraw()



class TxTable(ctk.CTkFrame):
    """Единая таблица операций: заголовок, полосатые строки, итоговая строка.
    В узком окне переходит в компактный режим (категория и заметка в одну колонку)."""

    COLS_WIDE = [("Дата", 88, "w"), ("", 30, "w"), ("Категория", 160, "w"),
                 ("Счёт", 130, "w"), ("Заметка", 0, "flex"),
                 ("Сумма", 128, "e"), ("", 34, "e")]
    COLS_NARROW = [("Дата", 84, "w"), ("", 30, "w"), ("Категория / заметка", 0, "flex"),
                   ("Сумма", 120, "e"), ("", 30, "e")]

    def __init__(self, master, app, title=None, on_delete=None, height=None):
        super().__init__(master, corner_radius=CARD_CORNER, fg_color=CARD,
                         border_width=1, border_color=BORDER)
        if height:
            self.configure(height=height)
            self.pack_propagate(False)
        self.app = app
        self.on_delete = on_delete
        self.narrow = False
        if title:
            ctk.CTkLabel(self, text=title,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(
                anchor="w", padx=16, pady=(12, 0))
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill="x", padx=14, pady=(8 if title else 12, 2))
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                   text_color=MUTED)
        self.status.pack(anchor="w", padx=16, pady=(0, 10))
        self._draw_header()

    def set_narrow(self, narrow):
        """True, если режим действительно переключился."""
        if narrow != self.narrow:
            self.narrow = narrow
            self._draw_header()
            return True
        return False

    def _draw_header(self):
        for w in self.header.winfo_children():
            w.destroy()
        cols = self.COLS_NARROW if self.narrow else self.COLS_WIDE
        for i, (txt, width, anchor) in enumerate(cols):
            if anchor == "flex":
                self.header.grid_columnconfigure(i, weight=1)
            lbl = ctk.CTkLabel(self.header, text=txt,
                               anchor="w" if anchor != "e" else "e",
                               font=ctk.CTkFont(size=11, weight="bold"),
                               text_color=MUTED)
            if width:
                lbl.configure(width=width)
            lbl.grid(row=0, column=i, sticky="w" if anchor != "e" else "e", padx=3)

    def load(self, rows, scope_text=""):
        for w in self.list_frame.winfo_children():
            w.destroy()
        cur = self.app.currency
        total_inc = total_exp = 0.0
        zebra = ("gray92", "gray16")       # постоянный фон чётных строк
        hover = ("gray86", "gray22")       # подсветка при наведении
        for i, (tid, k, amount, date, cat, acc, note) in enumerate(rows):
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)
            base = zebra if i % 2 == 0 else "transparent"
            row.configure(fg_color=base)
            # плавная подсветка строки при наведении
            row.bind("<Enter>", lambda e, r=row, b=base: r.configure(fg_color=hover))
            row.bind("<Leave>", lambda e, r=row, b=base: r.configure(fg_color=b))
            d = parse_date(date)
            color = GREEN if k == "income" else RED
            ctk.CTkLabel(row, text=f"{d.day:02d}.{d.month:02d}",
                         width=84 if self.narrow else 88, anchor="w",
                         font=ctk.CTkFont(size=12), text_color=MUTED).grid(
                row=0, column=0, padx=4, pady=5, sticky="w")
            ctk.CTkLabel(row, text="▲" if k == "income" else "▼", width=30,
                         text_color=color, font=ctk.CTkFont(size=10)).grid(
                row=0, column=1, padx=2)
            if self.narrow:
                label = cat if not note else f"{cat} · {note}"
                ctk.CTkLabel(row, text=label[:46], anchor="w",
                             font=ctk.CTkFont(size=12)).grid(
                    row=0, column=2, padx=4, sticky="w")
                row.grid_columnconfigure(2, weight=1)
                amount_col = 3
            else:
                ctk.CTkLabel(row, text=cat, width=160, anchor="w",
                             font=ctk.CTkFont(size=12)).grid(
                    row=0, column=2, padx=4, sticky="w")
                ctk.CTkLabel(row, text=acc, width=130, anchor="w", text_color=MUTED,
                             font=ctk.CTkFont(size=12)).grid(
                    row=0, column=3, padx=4, sticky="w")
                ctk.CTkLabel(row, text=note, anchor="w", text_color=MUTED,
                             font=ctk.CTkFont(size=12)).grid(
                    row=0, column=4, padx=4, sticky="w")
                row.grid_columnconfigure(4, weight=1)
                amount_col = 5
            sign = "+" if k == "income" else "−"
            ctk.CTkLabel(row, text=f"{sign}{amount:,.2f} {cur}".replace(",", " "),
                         width=120 if self.narrow else 128, anchor="e",
                         text_color=color,
                         font=ctk.CTkFont(size=12, weight="bold")).grid(
                row=0, column=amount_col, padx=4, sticky="e")
            if self.on_delete:
                IconButton(row, "✕", width=26 if self.narrow else 30,
                           command=lambda t=tid: self.on_delete(t)).grid(
                    row=0, column=amount_col + 1, padx=4)
            if k == "income":
                total_inc += amount
            else:
                total_exp += amount
        if not rows:
            ctk.CTkLabel(self.list_frame, text="Пусто.",
                         font=ctk.CTkFont(size=13), text_color=MUTED).pack(pady=40)
        self.status.configure(
            text=(f"{len(rows)} записей · {scope_text} · доходы +{total_inc:,.2f} {cur} · "
                  f"расходы −{total_exp:,.2f} {cur}").replace(",", " "))
        return total_inc, total_exp


# ---------------------------------------------------------------------------
# Диалоги (все: Esc — закрыть, Enter — подтвердить)
# ---------------------------------------------------------------------------

class BaseDialog(ctk.CTkToplevel):
    def __init__(self, master, title, geometry):
        super().__init__(master)
        self.title(title)
        self.geometry(geometry)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.result = None
        self.after(60, self.grab_set)
        self.bind("<Escape>", lambda e: self.destroy())
        self._pad = {"padx": 20, "pady": (4, 2)}

    def _label(self, text):
        ctk.CTkLabel(self, text=text, anchor="w",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            fill="x", padx=20, pady=(10, 0))

    def _entry(self, placeholder="", big=False):
        e = ctk.CTkEntry(self, placeholder_text=placeholder, corner_radius=CORNER,
                         fg_color=ENTRY_BG, border_color=BORDER,
                         font=ctk.CTkFont(size=17 if big else 13,
                                          weight="bold" if big else "normal"))
        e.pack(fill="x", padx=20, pady=(2, 0))
        return e

    def _buttons(self, ok_text, ok_cmd, ok_color=PRIMARY, ok_text_color=PRIMARY_TEXT):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=18)
        ctk.CTkButton(row, text=ok_text, fg_color=ok_color, hover_color=PRIMARY_HOVER,
                      text_color=ok_text_color, corner_radius=CORNER,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=ok_cmd).pack(side="right", padx=(8, 0))
        GhostButton(row, text="Отмена", command=self.destroy).pack(side="right")
        return row


class TransactionDialog(BaseDialog):
    """Новая транзакция; lock_account — для пополнения/снятия со счёта."""

    def __init__(self, master, db, cur, kind="expense", lock_account=None):
        super().__init__(master, "Новая транзакция", "430x600")
        self.db = db
        self._kind = kind
        self._lock_account = lock_account

        self.seg = ctk.CTkSegmentedButton(self, values=["Расход", "Доход"],
                                          command=self._on_kind, corner_radius=CORNER)
        self.seg.set("Расход" if kind == "expense" else "Доход")
        if lock_account is not None:
            self.seg.configure(state="disabled")
        self.seg.pack(fill="x", padx=20, pady=(18, 4))

        self._label(f"Сумма, {cur}")
        self.amount = self._entry("0.00", big=True)

        self._label("Дата (ГГГГ-ММ-ДД)")
        self.date = self._entry(today_str())
        self.date.delete(0, "end")
        self.date.insert(0, today_str())

        self._label("Категория")
        self.cat = ctk.CTkOptionMenu(self, values=[], corner_radius=CORNER,
                                     fg_color=ENTRY_BG, button_color=PRIMARY,
                                     button_hover_color=PRIMARY_HOVER,
                                     dropdown_fg_color=CARD)
        self.cat.pack(fill="x", padx=20, pady=(2, 0))

        self._label("Счёт")
        accs = db.accounts()
        if not accs:
            ctk.CTkLabel(self, text="Сначала создайте счёт в разделе «Финансы»",
                         text_color=RED).pack(padx=20, anchor="w")
            self._acc_ids = {}
        else:
            self._acc_ids = {a[1]: a[0] for a in accs}
            self.acc = ctk.CTkOptionMenu(self, values=list(self._acc_ids),
                                         corner_radius=CORNER, fg_color=ENTRY_BG,
                                         button_color=PRIMARY,
                                         button_hover_color=PRIMARY_HOVER,
                                         dropdown_fg_color=CARD)
            self.acc.pack(fill="x", padx=20, pady=(2, 0))
            if lock_account is not None:
                name = next((n for n, i in self._acc_ids.items() if i == lock_account), None)
                if name:
                    self.acc.set(name)
                self.acc.configure(state="disabled")

        self._label("Заметка")
        self.note = self._entry("Необязательно")

        self._buttons("Сохранить", self._save)
        self._refresh_cats()
        self.amount.focus_set()
        self.bind("<Return>", lambda e: self._save())

    def _on_kind(self, val):
        self._kind = "expense" if val == "Расход" else "income"
        self._refresh_cats()

    def _refresh_cats(self):
        cats = [c[1] for c in self.db.categories(self._kind)]
        if not cats:
            cats = ["—"]
        self.cat.configure(values=cats)
        self.cat.set(cats[0])

    def _save(self):
        if not self._acc_ids:
            messagebox.showerror("Ошибка", "Нет ни одного счёта", parent=self)
            return
        try:
            amount = float(self.amount.get().replace(",", ".").replace(" ", ""))
            if amount <= 0:
                raise ValueError
            date = parse_date(self.date.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка", "Проверьте сумму и дату (ГГГГ-ММ-ДД)", parent=self)
            return
        cat_names = {n: i for i, n in self.db.categories(self._kind)}
        cat_id = cat_names.get(self.cat.get())
        acc_id = self._acc_ids.get(self.acc.get() if self._acc_ids else "")
        self.result = dict(kind=self._kind, amount=amount, date=date.isoformat(),
                           category_id=cat_id, account_id=acc_id,
                           note=self.note.get().strip())
        self.destroy()


class TransferDialog(BaseDialog):
    def __init__(self, master, db, cur):
        super().__init__(master, "Перевод между счетами", "420x440")
        self.db = db
        accs = db.accounts()
        if len(accs) < 2:
            ctk.CTkLabel(self, text="Нужно минимум два счёта.\nСоздайте их в разделе «Финансы».",
                         justify="center", font=ctk.CTkFont(size=13)).pack(
                expand=True, fill="both", padx=20, pady=(30, 0))
            GhostButton(self, text="Закрыть", command=self.destroy).pack(pady=(0, 20))
            return
        self._ids = {a[1]: a[0] for a in accs}
        names = list(self._ids)

        self._label("Откуда")
        self.src = ctk.CTkOptionMenu(self, values=names, corner_radius=CORNER,
                                     fg_color=ENTRY_BG, button_color=PRIMARY,
                                     button_hover_color=PRIMARY_HOVER,
                                     dropdown_fg_color=CARD)
        self.src.set(names[0])
        self.src.pack(fill="x", padx=20, pady=(2, 0))

        self._label("Куда")
        self.dst = ctk.CTkOptionMenu(self, values=names, corner_radius=CORNER,
                                     fg_color=ENTRY_BG, button_color=PRIMARY,
                                     button_hover_color=PRIMARY_HOVER,
                                     dropdown_fg_color=CARD)
        self.dst.set(names[1])
        self.dst.pack(fill="x", padx=20, pady=(2, 0))

        self._label(f"Сумма, {cur}")
        self.amount = self._entry("0.00", big=True)

        self._label("Дата (ГГГГ-ММ-ДД)")
        self.date = self._entry("")
        self.date.insert(0, today_str())

        self._buttons("Перевести", self._save)
        self.bind("<Return>", lambda e: self._save())

    def _save(self):
        if not hasattr(self, "src"):
            return
        if self.src.get() == self.dst.get():
            messagebox.showerror("Ошибка", "Выберите разные счета", parent=self)
            return
        try:
            amount = float(self.amount.get().replace(",", ".").replace(" ", ""))
            if amount <= 0:
                raise ValueError
            date = parse_date(self.date.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка", "Проверьте сумму и дату", parent=self)
            return
        self.result = dict(from_id=self._ids[self.src.get()], to_id=self._ids[self.dst.get()],
                           amount=amount, date=date.isoformat())
        self.destroy()


class BudgetDialog(BaseDialog):
    def __init__(self, master, db, cur, focus_cat_id=None):
        super().__init__(master, "Бюджет категории", "400x330")
        self.db = db
        cats = db.categories("expense")
        if not cats:
            ctk.CTkLabel(self, text="Нет категорий расходов",
                         font=ctk.CTkFont(size=13)).pack(expand=True, fill="both")
            return
        self._ids = {n: i for i, n in cats}
        existing = {b[0]: b[2] for b in db.budgets()}

        self._label("Категория")
        self.cat = ctk.CTkOptionMenu(self, values=list(self._ids), corner_radius=CORNER,
                                     fg_color=ENTRY_BG, button_color=PRIMARY,
                                     button_hover_color=PRIMARY_HOVER,
                                     dropdown_fg_color=CARD, command=self._prefill)
        self.cat.pack(fill="x", padx=20, pady=(2, 0))

        self._label(f"Лимит в месяц, {cur} (0 — удалить бюджет)")
        self.limit = self._entry("0", big=True)

        if focus_cat_id is not None:
            name = next((n for n, i in self._ids.items() if i == focus_cat_id), None)
            if name:
                self.cat.set(name)
        self._prefill(self.cat.get())

        self._buttons("Сохранить", self._save)
        self.bind("<Return>", lambda e: self._save())

    def _prefill(self, name):
        ids = getattr(self, "_ids", {})
        lim = {b[0]: b[2] for b in self.db.budgets()}.get(ids.get(name), 0)
        self.limit.delete(0, "end")
        self.limit.insert(0, f"{lim:.0f}" if lim else "")

    def _save(self):
        try:
            limit = float(self.limit.get().replace(",", ".").replace(" ", "") or "0")
            if limit < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Введите корректную сумму", parent=self)
            return
        self.result = dict(category_id=self._ids[self.cat.get()], limit=limit)
        self.destroy()


class AccountDialog(BaseDialog):
    def __init__(self, master, cur, name="", balance=""):
        super().__init__(master, "Новый счёт", "400x300")
        self._label("Название")
        self.name = self._entry("Например: Карта банка")
        if name:
            self.name.insert(0, name)

        self._label(f"Начальный баланс, {cur} (необязательно)")
        self.balance = self._entry("0")
        if balance:
            self.balance.insert(0, balance)

        self._buttons("Создать", self._save)
        self.name.focus_set()
        self.bind("<Return>", lambda e: self._save())

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showerror("Ошибка", "Введите название счёта", parent=self)
            return
        try:
            bal = float(self.balance.get().replace(",", ".").replace(" ", "") or "0")
        except ValueError:
            bal = 0.0
        self.result = dict(name=name, balance=bal)
        self.destroy()


class CategoryDialog(BaseDialog):
    def __init__(self, master):
        super().__init__(master, "Новая категория", "400x320")
        self._label("Название")
        self.name = self._entry("Например: Спорт")

        self._label("Тип")
        self.kind = ctk.CTkSegmentedButton(self, values=["Расход", "Доход"],
                                           corner_radius=CORNER)
        self.kind.set("Расход")
        self.kind.pack(fill="x", padx=20, pady=(2, 0))

        self._buttons("Создать", self._save)
        self.name.focus_set()
        self.bind("<Return>", lambda e: self._save())

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showerror("Ошибка", "Введите название", parent=self)
            return
        self.result = dict(name=name,
                           kind="expense" if self.kind.get() == "Расход" else "income")
        self.destroy()


# ---------------------------------------------------------------------------
# Базовые страницы
# ---------------------------------------------------------------------------

class ScrollPage(ctk.CTkScrollableFrame):
    """Страница с вертикальной прокруткой — ничего не съезжает на малых окнах."""
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.app = app
        self._last_cols_width = 0
        self._cols_job = None
        self.bind("<Configure>", self._on_page_conf)

    def _on_page_conf(self, e):
        # перестроение колонок при заметной смене ширины; небольшая задержка
        # защищает от спама событий при перетаскивании границы окна
        if abs(e.width - self._last_cols_width) < 40:
            return
        self._last_cols_width = e.width
        if self._cols_job:
            self.after_cancel(self._cols_job)
        self._cols_job = self.after(200, lambda: self._relayout(e.width))

    def _relayout(self, width):
        pass

    def inner_width(self):
        return max(self.winfo_width() - 32, 200)

    def refresh(self):
        pass


class PlainPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

    def refresh(self):
        pass


# ---------------------------------------------------------------------------
# Дашборд
# ---------------------------------------------------------------------------

class DashboardPage(ScrollPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._build()

    def _build(self):
        self.greet = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=22, weight="bold"))
        self.greet.pack(anchor="w", padx=4, pady=(6, 2))
        self.greet_sub = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12),
                                      text_color=MUTED)
        self.greet_sub.pack(anchor="w", padx=4, pady=(0, 10))

        self.kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_row.pack(fill="x")
        self.kpi_income = make_kpi(self.kpi_row, "ДОХОДЫ ЗА МЕСЯЦ", GREEN)
        self.kpi_expense = make_kpi(self.kpi_row, "РАСХОДЫ ЗА МЕСЯЦ", RED)
        self.kpi_balance = make_kpi(self.kpi_row, "ОБЩИЙ БАЛАНС", ("#20242b", "#e6e9ee"))
        cur_sym = self.app.currency
        self.anim_income = AnimatedLabel(self.kpi_income["value"],
                                         lambda v: fmt_money(v, cur_sym))
        self.anim_expense = AnimatedLabel(self.kpi_expense["value"],
                                          lambda v: fmt_money(v, cur_sym))
        self.anim_balance = AnimatedLabel(self.kpi_balance["value"],
                                          lambda v: fmt_money(v, cur_sym))

        self.trend = ChartCard(self, "Доходы и расходы за 6 месяцев",
                               self._draw_trend, height=290)
        self.trend.pack(fill="x", pady=(12, 0))

        self.bottom = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom.pack(fill="x", pady=(12, 6))
        self.pie = ChartCard(self.bottom, "Структура расходов месяца",
                             self._draw_pie, height=300)
        self.summary = ctk.CTkFrame(self.bottom, corner_radius=CARD_CORNER,
                                    fg_color=CARD, border_width=1, border_color=BORDER)
        ctk.CTkLabel(self.summary, text="Сводка месяца",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 4))
        self.summary_body = ctk.CTkFrame(self.summary, fg_color="transparent")
        self.summary_body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.table = TxTable(self, self.app, title="Последние операции месяца", height=330)
        self.table.pack(fill="x", pady=(12, 6))

        self._layout(self.inner_width())

    def _relayout(self, width):
        self._layout(width)

    def _layout(self, width):
        wide = width >= 620
        for w in (self.kpi_income["frame"], self.kpi_expense["frame"],
                  self.kpi_balance["frame"]):
            w.grid_forget()
        cols = 3 if width >= 620 else 1
        for i, card in enumerate((self.kpi_income, self.kpi_expense, self.kpi_balance)):
            f = card["frame"]
            f.grid(row=0 if wide else i, column=i if wide else 0,
                   sticky="nsew", padx=(0, 10) if (wide and i < 2) else 0,
                   pady=0 if wide else (0, 10))
        self.kpi_row.grid_columnconfigure(tuple(range(cols)), weight=1, uniform="k")

        for w in (self.pie, self.summary):
            w.pack_forget()
            w.grid_forget()
        if wide:
            self.bottom.grid_columnconfigure(0, weight=3)
            self.bottom.grid_columnconfigure(1, weight=2)
            self.pie.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            self.summary.grid(row=0, column=1, sticky="nsew")
        else:
            self.bottom.grid_columnconfigure(0, weight=1)
            self.pie.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            self.summary.grid(row=1, column=0, sticky="ew")
        table = getattr(self, "table", None)
        if table is not None:
            table.set_narrow(width < 620)

    def refresh(self):
        db, cur = self.app.db, self.app.currency
        y, m = self.app.year, self.app.month
        today = dt.date.today()
        self.greet.configure(text=f"{greeting()}!")
        self.greet_sub.configure(
            text=f"{today.day} {MONTHS_RU[today.month-1].lower()} {today.year} · "
                 f"просматривается {month_label(y, m).lower()}")

        tot = db.month_totals(y, m)
        net = tot["income"] - tot["expense"]
        self.anim_income.set_value(tot["income"])
        self.anim_expense.set_value(tot["expense"])
        self.anim_balance.set_value(db.net_worth())
        self.kpi_balance["sub"].configure(
            text=f"За месяц: {'+' if net >= 0 else '−'}{fmt_money(abs(net), cur)}")

        py, pm = shift_month(y, m, -1)
        prev = db.month_totals(py, pm)
        if prev["expense"] > 0:
            delta = (tot["expense"] - prev["expense"]) / prev["expense"] * 100
            self.kpi_expense["sub"].configure(
                text=f"{'▲' if delta > 0 else '▼'} {abs(delta):.0f}% к прошлому месяцу")
            inc_delta = ((tot["income"] - prev["income"]) / prev["income"] * 100
                         if prev["income"] > 0 else 0)
            self.kpi_income["sub"].configure(
                text=f"{'▲' if inc_delta > 0 else '▼'} {abs(inc_delta):.0f}% к прошлому месяцу"
                if prev["income"] > 0 else "")
        else:
            self.kpi_expense["sub"].configure(text="")
            self.kpi_income["sub"].configure(text="")

        self._fill_summary(y, m, tot, cur, today)
        rows = db.fetch_transactions(year=y, month=m, limit=8)
        self.table.load(rows, month_label(y, m).lower())
        self.pie.refresh()
        self.trend.refresh()

    def _fill_summary(self, y, m, tot, cur, today):
        for w in self.summary_body.winfo_children():
            w.destroy()
        db = self.app.db
        days_passed = today.day if (y, m) == (today.year, today.month) \
            else calendar.monthrange(y, m)[1]
        n_tx = len(db.fetch_transactions(year=y, month=m))
        rows = db.expenses_by_category(y, m)

        def line(label, value, color=None):
            r = ctk.CTkFrame(self.summary_body, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=label, anchor="w", font=ctk.CTkFont(size=12),
                         text_color=MUTED).pack(side="left")
            ctk.CTkLabel(r, text=value, anchor="e", text_color=color or ("#20242b", "#e6e9ee"),
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="right")

        line("Операций за месяц", str(n_tx))
        if days_passed:
            line("Средний расход в день", fmt_money(tot["expense"] / days_passed, cur))
        if tot["income"] > 0:
            rate = (tot["income"] - tot["expense"]) / tot["income"] * 100
            line("Норма сбережений", f"{rate:.0f}%",
                 GREEN if rate >= 20 else (AMBER if rate >= 0 else RED))
        if rows:
            share = rows[0][1] / tot["expense"] * 100 if tot["expense"] else 0
            line("Главная статья расходов", f"{rows[0][0]} · {share:.0f}%")
        biggest = sorted(db.fetch_transactions(year=y, month=m, kind="expense", limit=1),
                         key=lambda r: -r[2])
        if biggest:
            b = biggest[0]
            label = (b[6] or b[4])[:22]
            line("Крупнейший расход", f"{label} · {fmt_money(b[2], cur)}", RED)

    # -- графики ------------------------------------------------------------
    def _draw_trend(self, fig, w, h, tc):
        data = self.app.db.last_months_totals(6)
        labels = [MONTHS_SHORT[m - 1] for _, m, _, _ in data]
        incomes = [i for _, _, i, _ in data]
        expenses = [e for _, _, _, e in data]
        ax = fig.add_subplot(111)
        x = np.arange(len(labels))
        bw = 0.38
        ax.bar(x - bw / 2, incomes, width=bw, color=tc["income"], label="Доходы", zorder=3)
        ax.bar(x + bw / 2, expenses, width=bw, color=tc["expense"], label="Расходы", zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, color=tc["muted"])
        style_ax(ax, tc)
        # легенда под диаграммой, по центру — не перекрывается столбцами
        style_legend(ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12),
                               ncol=2), tc)
        fig.tight_layout(pad=0.8)
        return

    def _draw_pie(self, fig, w, h, tc):
        y, m = self.app.year, self.app.month
        rows = self.app.db.expenses_by_category(y, m)
        ax = fig.add_subplot(111)
        if not rows:
            ax.text(0.5, 0.5, "Нет расходов за месяц", ha="center", va="center",
                    color=tc["muted"], fontsize=11)
            ax.axis("off")
            fig.tight_layout(pad=0.5)
            return
        top = rows[:6]
        rest = sum(r[1] for r in rows[6:])
        names = [r[0] for r in top] + (["Остальное"] if rest > 0 else [])
        vals = [r[1] for r in top] + ([rest] if rest > 0 else [])
        total = sum(vals)
        colors = [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(vals))]
        wedges, _, autotexts = ax.pie(
            vals, colors=colors, startangle=90, counterclock=False,
            autopct=lambda p: f"{p:.0f}%" if p >= 6 else "",
            pctdistance=0.78, wedgeprops=dict(width=0.40, edgecolor=tc["card"], linewidth=1.5))
        for at in autotexts:
            at.set_color("#ffffff" if Theme.is_dark() else "#1f242b")
            at.set_fontsize(8)
            at.set_fontweight("bold")
        ax.text(0, 0, f"{fmt_money(total, self.app.currency)}", ha="center", va="center",
                color=tc["fg"], fontsize=11, fontweight="bold")
        # легенда категорий под диаграммой, в несколько колонок
        ncol = 3 if len(names) > 4 else len(names)
        ax.legend(wedges, [f"{n}" for n in names], loc="upper center",
                  bbox_to_anchor=(0.5, -0.02), ncol=ncol, fontsize=8,
                  columnspacing=1.0, handlelength=1.1)
        style_legend(ax.get_legend(), tc)
        ax.set_aspect("equal")
        fig.tight_layout(pad=0.5)
        return


# ---------------------------------------------------------------------------
# Транзакции
# ---------------------------------------------------------------------------

class TransactionsPage(PlainPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.filter_kind = "all"
        self._build()

    def _build(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=4, pady=(6, 10))
        bar.grid_columnconfigure(0, weight=1)

        self.search = ctk.CTkEntry(bar, placeholder_text="Поиск по заметке или категории…",
                                   corner_radius=CORNER, fg_color=ENTRY_BG,
                                   border_color=BORDER)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.search.bind("<KeyRelease>", lambda e: self._reload())

        self.seg = ctk.CTkSegmentedButton(bar, values=["Все", "Расходы", "Доходы"],
                                          command=self._on_seg, corner_radius=CORNER,
                                          width=220)
        self.seg.set("Все")
        self.seg.grid(row=0, column=1, padx=(0, 10))

        PrimaryButton(bar, text="＋ Добавить", width=120,
                      command=self.app.open_transaction_dialog).grid(row=0, column=2)

        self.table = TxTable(self, self.app, on_delete=self._delete)
        self.table.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        self.bind("<Configure>", self._on_width)

    def _on_width(self, e):
        if self.table.set_narrow(e.width < 780):
            self._reload()

    def _on_seg(self, val):
        self.filter_kind = {"Все": "all", "Расходы": "expense", "Доходы": "income"}[val]
        self._reload()

    def refresh(self):
        self._reload()

    def _reload(self):
        app = self.app
        y, m = app.year, app.month
        kind = None if self.filter_kind == "all" else self.filter_kind
        search = self.search.get().strip()
        if search:
            rows = app.db.fetch_transactions(kind=kind, search=search, limit=300)
            scope = f"поиск «{search}»"
        else:
            rows = app.db.fetch_transactions(year=y, month=m, kind=kind, limit=300)
            scope = month_label(y, m).lower()
        self.table.load(rows, scope)

    def _delete(self, tx_id):
        # без предупреждения
        self.app.db.delete_transaction(tx_id)
        self.app.refresh_all()


# ---------------------------------------------------------------------------
# Бюджеты
# ---------------------------------------------------------------------------

class BudgetsPage(ScrollPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=4, pady=(6, 4))
        self.head = ctk.CTkLabel(bar, text="Бюджеты", font=ctk.CTkFont(size=18, weight="bold"))
        self.head.pack(side="left")
        PrimaryButton(bar, text="＋ Бюджет", width=110,
                      command=lambda: self._edit(None)).pack(side="right")
        GhostButton(bar, text="Перевод", width=96,
                    command=self.app.open_transfer_dialog).pack(side="right", padx=(0, 8))

        self.hint = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color=MUTED)
        self.hint.pack(anchor="w", padx=4, pady=(0, 8))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="x")

    def _relayout(self, width):
        self.refresh()

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        app = self.app
        db, cur = app.db, app.currency
        y, m = app.year, app.month
        self.hint.configure(text=f"Лимиты и факт за {month_label(y, m).lower()}")

        budgets = db.budgets()
        if not budgets:
            ctk.CTkLabel(self.body, justify="center",
                         text="Бюджетов пока нет.\nНажмите «＋ Бюджет», чтобы задать "
                              "месячный лимит для категории расходов.",
                         font=ctk.CTkFont(size=13), text_color=MUTED).grid(
                row=0, column=0, pady=60)
            return
        cols = max(1, min(3, self.inner_width() // 290))
        today = dt.date.today()
        for idx, (cat_id, name, limit) in enumerate(budgets):
            spent = db.budget_progress(cat_id, y, m)
            card = ctk.CTkFrame(self.body, corner_radius=CARD_CORNER, fg_color=CARD,
                                border_width=1, border_color=BORDER)
            card.grid(row=idx // cols, column=idx % cols, sticky="nsew",
                      padx=(0, 10) if idx % cols != cols - 1 else 0, pady=(0, 10))
            self.body.grid_columnconfigure(tuple(range(cols)), weight=1, uniform="b")

            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=16, pady=(14, 0))
            ctk.CTkLabel(head, text=name,
                         font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
            # удаление бюджета — без предупреждения
            IconButton(head, "✕", command=lambda c=cat_id: self._delete(c)).pack(side="right")
            IconButton(head, "✎", hover=SIDEBAR_HOVER,
                       command=lambda c=cat_id: self._edit(c)).pack(side="right", padx=(0, 4))

            bar = AnimatedBar(card, height=8, corner_radius=4, fg_color=CARD_INNER,
                              progress_color=GREEN)
            bar.pack(fill="x", padx=16, pady=(12, 0))
            pct = bar.animate_to(spent, limit)

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=(6, 0))
            ctk.CTkLabel(r, text=f"{spent:,.0f} / {limit:,.0f} {cur}".replace(",", " "),
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            ctk.CTkLabel(r, text=f"{pct * 100:.0f}%", font=ctk.CTkFont(size=12),
                         text_color=MUTED).pack(side="right")

            left = limit - spent
            if left >= 0:
                msg, color = f"Осталось {fmt_money(left, cur)}", MUTED
            else:
                msg, color = f"Превышение на {fmt_money(-left, cur)}", RED
            ctk.CTkLabel(card, text=msg, font=ctk.CTkFont(size=12),
                         text_color=color).pack(anchor="w", padx=16, pady=(6, 0))

            if (y, m) == (today.year, today.month) and today.day > 2:
                days_in_month = calendar.monthrange(y, m)[1]
                projected = spent / today.day * days_in_month
                fc = RED if projected > limit else MUTED
                ctk.CTkLabel(card, text=f"Прогноз на конец месяца: {fmt_money(projected, cur)}",
                             font=ctk.CTkFont(size=11), text_color=fc).pack(
                    anchor="w", padx=16, pady=(2, 14))
            else:
                ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11)).pack(pady=(0, 8))

    def _edit(self, cat_id):
        dlg = BudgetDialog(self, self.app.db, self.app.currency, focus_cat_id=cat_id)
        self.wait_window(dlg)
        if dlg.result:
            self.app.db.set_budget(dlg.result["category_id"], dlg.result["limit"])
            self.app.refresh_all()

    def _delete(self, cat_id):
        self.app.db.set_budget(cat_id, 0)
        self.app.refresh_all()


# ---------------------------------------------------------------------------
# Финансы (счета)
# ---------------------------------------------------------------------------

class FinancePage(ScrollPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=4, pady=(6, 4))
        ctk.CTkLabel(bar, text="Финансы", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        PrimaryButton(bar, text="＋ Счёт", width=96, command=self._add).pack(side="right")
        GhostButton(bar, text="⇄ Перевод", width=110,
                    command=self.app.open_transfer_dialog).pack(side="right", padx=(0, 8))

        self.total = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=13), text_color=MUTED)
        self.total.pack(anchor="w", padx=4, pady=(0, 8))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="x")

        self.recent = ctk.CTkFrame(self, corner_radius=CARD_CORNER, fg_color=CARD,
                                   border_width=1, border_color=BORDER)
        self.recent.pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(self.recent, text="Последние операции",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 4))
        self.recent_body = ctk.CTkFrame(self.recent, fg_color="transparent")
        self.recent_body.pack(fill="x", padx=16, pady=(0, 12))

    def _relayout(self, width):
        self.refresh()

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        app = self.app
        db, cur = app.db, app.currency
        accounts = db.accounts()
        total = sum(a[2] for a in accounts)
        self.total.configure(
            text=f"{len(accounts)} счетов · суммарно {fmt_money(total, cur)}")

        cols = max(1, min(3, self.inner_width() // 300))
        for i, (aid, name, balance) in enumerate(accounts):
            card = ctk.CTkFrame(self.body, corner_radius=CARD_CORNER, fg_color=CARD,
                                border_width=1, border_color=BORDER)
            card.grid(row=i // cols, column=i % cols, sticky="nsew",
                      padx=(0, 10) if i % cols != cols - 1 else 0, pady=(0, 10))
            self.body.grid_columnconfigure(tuple(range(cols)), weight=1, uniform="fa")

            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=16, pady=(14, 0))
            ctk.CTkLabel(head, text=name,
                         font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
            IconButton(head, "✕", command=lambda a=aid: self._delete(a)).pack(side="right")
            IconButton(head, "✎", hover=SIDEBAR_HOVER,
                       command=lambda a=aid, n=name: self._rename(a, n)).pack(
                side="right", padx=(0, 4))

            color = GREEN if balance >= 0 else RED
            ctk.CTkLabel(card, text=fmt_money(balance, cur), text_color=color,
                         font=ctk.CTkFont(size=21, weight="bold")).pack(
                anchor="w", padx=16, pady=(4, 0))
            n_tx = db.account_tx_count(aid)
            ctk.CTkLabel(card, text=f"{n_tx} операций", font=ctk.CTkFont(size=11),
                         text_color=MUTED).pack(anchor="w", padx=16)

            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(fill="x", padx=16, pady=(10, 14))
            ctk.CTkButton(btns, text="Пополнить", height=30, corner_radius=CORNER,
                          fg_color="transparent", border_width=1, border_color=GREEN,
                          text_color=GREEN, font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda a=aid: self._cash(a, "income")).pack(
                side="left", expand=True, fill="x", padx=(0, 4))
            ctk.CTkButton(btns, text="Снять", height=30, corner_radius=CORNER,
                          fg_color="transparent", border_width=1, border_color=RED,
                          text_color=RED, font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda a=aid: self._cash(a, "expense")).pack(
                side="left", expand=True, fill="x", padx=(4, 0))

        # последние операции
        for w in self.recent_body.winfo_children():
            w.destroy()
        recent = db.fetch_transactions(limit=8)
        if not recent:
            ctk.CTkLabel(self.recent_body, text="Операций пока нет",
                         text_color=MUTED).pack(anchor="w")
        for tid, k, amount, date, cat, acc, note in recent:
            r = ctk.CTkFrame(self.recent_body, fg_color="transparent")
            r.pack(fill="x", pady=1)
            d = parse_date(date)
            color = GREEN if k == "income" else RED
            sign = "+" if k == "income" else "−"
            ctk.CTkLabel(r, text=f"{d.day:02d}.{d.month:02d}", width=48, anchor="w",
                         font=ctk.CTkFont(size=12), text_color=MUTED).pack(side="left")
            ctk.CTkLabel(r, text=(note or cat)[:44], anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=8)
            ctk.CTkLabel(r, text=acc, anchor="w", font=ctk.CTkFont(size=11),
                         text_color=MUTED).pack(side="left")
            ctk.CTkLabel(r, text=f"{sign}{amount:,.2f} {cur}".replace(",", " "),
                         anchor="e", text_color=color,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="right", padx=(8, 0))
            # удаление без предупреждения
            IconButton(r, "✕", width=24, height=22,
                       command=lambda t=tid: self._delete_tx(t)).pack(side="right")

    def _add(self):
        dlg = AccountDialog(self, self.app.currency)
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            self.app.db.add_account(r["name"])
            acc_id = self.app.db.accounts()[-1][0]
            if r["balance"] != 0:
                # стартовый баланс проводим как доход/расход, чтобы история сходилась
                kind = "income" if r["balance"] > 0 else "expense"
                cats = self.app.db.categories(kind)
                cat_id = None
                for cid, cname in cats:
                    if cname == "Прочее":
                        cat_id = cid
                if cat_id is None and cats:
                    cat_id = cats[0][0]
                self.app.db.add_transaction(kind, abs(r["balance"]), today_str(),
                                            cat_id, acc_id, "Начальный баланс")
            self.app.refresh_all()

    def _rename(self, acc_id, old):
        dlg = BaseDialog(self, "Переименовать счёт", "380x220")
        dlg._label("Новое название")
        entry = dlg._entry("")
        entry.insert(0, old)

        def save():
            name = entry.get().strip()
            if name:
                self.app.db.rename_account(acc_id, name)
                self.app.refresh_all()
            dlg.destroy()
        dlg._buttons("Сохранить", save)
        self.wait_window(dlg)

    def _cash(self, acc_id, kind):
        """Пополнение/снятие: обычная транзакция, привязанная к счёту."""
        dlg = TransactionDialog(self, self.app.db, self.app.currency,
                                kind=kind, lock_account=acc_id)
        dlg.title("Пополнение счёта" if kind == "income" else "Снятие со счёта")
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            self.app.db.add_transaction(r["kind"], r["amount"], r["date"],
                                        r["category_id"], r["account_id"], r["note"])
            self.app.refresh_all()

    def _delete(self, acc_id):
        # без предупреждения; транзакции сохраняются, теряя привязку к счёту
        self.app.db.delete_account(acc_id)
        self.app.refresh_all()

    def _delete_tx(self, tx_id):
        self.app.db.delete_transaction(tx_id)
        self.app.refresh_all()


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

class SettingsPage(ScrollPage):
    def __init__(self, master, app):
        super().__init__(master, app)
        ctk.CTkLabel(self, text="Настройки", font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=4, pady=(6, 10))

        # --- внешний вид
        look = self._card("Внешний вид")
        r = self._row(look, "Тема оформления")
        self.theme_menu = ctk.CTkOptionMenu(r, values=["Тёмная", "Светлая", "Системная"],
                                            width=140, corner_radius=CORNER,
                                            fg_color=ENTRY_BG, button_color=PRIMARY,
                                            button_hover_color=PRIMARY_HOVER,
                                            dropdown_fg_color=CARD,
                                            command=self._set_theme)
        self.theme_menu.pack(side="left")

        r = self._row(look, "Масштаб интерфейса")
        self.scale_menu = ctk.CTkOptionMenu(r, values=["90%", "100%", "110%", "125%"],
                                            width=140, corner_radius=CORNER,
                                            fg_color=ENTRY_BG, button_color=PRIMARY,
                                            button_hover_color=PRIMARY_HOVER,
                                            dropdown_fg_color=CARD,
                                            command=self._set_scale)
        self.scale_menu.pack(side="left")

        # --- валюта
        money = self._card("Валюта")
        r = self._row(money, "Символ")
        self.currency_menu = ctk.CTkOptionMenu(r, values=CURRENCY_PRESETS, width=90,
                                               corner_radius=CORNER, fg_color=ENTRY_BG,
                                               button_color=PRIMARY,
                                               button_hover_color=PRIMARY_HOVER,
                                               dropdown_fg_color=CARD,
                                               command=self.app.set_currency)
        self.currency_menu.pack(side="left")
        ctk.CTkLabel(r, text="или свой:", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(14, 6))
        self.currency_entry = ctk.CTkEntry(r, width=90, corner_radius=CORNER,
                                           fg_color=ENTRY_BG, border_color=BORDER,
                                           placeholder_text="₿")
        self.currency_entry.pack(side="left")
        self.currency_entry.bind("<Return>", self._set_custom_currency)
        self.currency_entry.bind("<FocusOut>", self._set_custom_currency)

        # --- горячие клавиши
        keys = self._card("Горячие клавиши")
        for combo, desc in HOTKEYS_HELP:
            r = ctk.CTkFrame(keys, fg_color="transparent")
            r.pack(fill="x", padx=18, pady=2)
            ctk.CTkLabel(r, text=combo, width=140, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            ctk.CTkLabel(r, text=desc, anchor="w", text_color=MUTED,
                         font=ctk.CTkFont(size=12)).pack(side="left")

        # --- категории
        cats = self._card("Категории")
        r = ctk.CTkFrame(cats, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(4, 6))
        ctk.CTkLabel(r, text="Удаление категории сохраняет её прошлые операции "
                             "(они получат метку «—»).", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left")
        PrimaryButton(r, text="＋ Категория", width=130,
                      command=self._add_category).pack(side="right")
        self.cats_body = ctk.CTkFrame(cats, fg_color="transparent")
        self.cats_body.pack(fill="x", padx=18, pady=(0, 14))

        # --- данные
        data = self._card("Данные")
        r = ctk.CTkFrame(data, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(6, 4))
        ctk.CTkLabel(r, text="База данных:", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).pack(side="left")
        ctk.CTkLabel(r, text=DB_PATH, font=ctk.CTkFont(size=11),
                     text_color=MUTED).pack(side="left", padx=6)
        r = ctk.CTkFrame(data, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(4, 14))
        GhostButton(r, text="Экспорт в CSV", width=150,
                    command=self._export).pack(side="left")
        GhostButton(r, text="Загрузить демо-данные", width=200,
                    command=self._demo).pack(side="left", padx=8)
        ctk.CTkButton(r, text="Очистить все данные", width=180, fg_color=RED,
                      hover_color=("#b91c1c", "#991b1b"), text_color="#ffffff",
                      corner_radius=CORNER, font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._wipe).pack(side="left")

        # --- о программе
        about = self._card("О программе")
        ctk.CTkLabel(about, text=f"Finance Tracker v{APP_VERSION} by {AUTHOR}",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=18, pady=(12, 2))
        ctk.CTkLabel(about, justify="left", text_color=MUTED,
                     font=ctk.CTkFont(size=12),
                     text="Локальный трекер личных финансов. Все данные хранятся только\n"
                          "на вашем компьютере и никуда не отправляются.").pack(
            anchor="w", padx=18, pady=(0, 14))

        self._sync_controls()

    # -- helpers
    def _card(self, title):
        card = ctk.CTkFrame(self, corner_radius=CARD_CORNER, fg_color=CARD,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=18, pady=(12, 4))
        return card

    def _row(self, parent, label):
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=4)
        ctk.CTkLabel(r, text=label, width=300, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        return r

    def _sync_controls(self):
        app = self.app
        self.theme_menu.set({"dark": "Тёмная", "light": "Светлая",
                             "system": "Системная"}.get(app.theme, "Тёмная"))
        self.scale_menu.set(f"{int(app.ui_scale * 100)}%")
        if app.currency in CURRENCY_PRESETS:
            self.currency_menu.set(app.currency)

    def refresh(self):
        self._sync_controls()
        self._render_categories()

    def _render_categories(self):
        for w in self.cats_body.winfo_children():
            w.destroy()
        db = self.app.db
        # равные ячейки: чипы одной ширины, колонки строго друг под другом
        per_row = {"expense": 3, "income": 3}
        for kind, title in (("expense", "Расходы"), ("income", "Доходы")):
            ctk.CTkLabel(self.cats_body, text=title, text_color=MUTED,
                         font=ctk.CTkFont(size=11, weight="bold")).pack(
                anchor="w", pady=(6, 3))
            grid = ctk.CTkFrame(self.cats_body, fg_color="transparent")
            grid.pack(fill="x")
            cols = per_row[kind]
            for i in range(cols):
                grid.grid_columnconfigure(i, weight=1, uniform=f"cat_{kind}")
            cats = db.categories(kind)
            for i, (cid, name) in enumerate(cats):
                chip = ctk.CTkFrame(grid, fg_color=CARD_INNER, corner_radius=9,
                                    border_width=1, border_color=BORDER)
                chip.grid(row=i // cols, column=i % cols, sticky="ew",
                          padx=4, pady=3)
                ctk.CTkLabel(chip, text=name, anchor="w",
                             font=ctk.CTkFont(size=12)).pack(
                    side="left", fill="x", expand=True, padx=(10, 2), pady=5)
                # удаление категории — без предупреждения
                IconButton(chip, "✕", width=20, height=20,
                           font=ctk.CTkFont(size=10),
                           command=lambda c=cid: self._delete_category(c)).pack(
                    side="right", padx=(0, 6))
            if not cats:
                ctk.CTkLabel(grid, text="—", text_color=MUTED,
                             font=ctk.CTkFont(size=12)).grid(row=0, column=0,
                                                             sticky="w", padx=4)

    def _delete_category(self, cat_id):
        self.app.db.delete_category(cat_id)
        self.app.refresh_all()

    def _add_category(self):
        dlg = CategoryDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            try:
                self.app.db.add_category(dlg.result["name"], dlg.result["kind"])
            except ValueError as e:
                messagebox.showerror("Ошибка", str(e), parent=self)
                return
            self.app.refresh_all()

    def _set_theme(self, val):
        self.app.set_theme({"Тёмная": "dark", "Светлая": "light",
                            "Системная": "system"}[val])

    def _set_scale(self, val):
        self.app.set_scale(int(val.rstrip("%")) / 100)

    def _set_custom_currency(self, _=None):
        val = self.currency_entry.get().strip()
        if val and val != self.app.currency:
            self.app.set_currency(val[:6])
            self.currency_entry.delete(0, "end")

    def _export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"finance_{dt.date.today().isoformat()}.csv")
        if not path:
            return
        n = self.app.db.export_csv(path)
        messagebox.showinfo("Экспорт", f"Готово: {n} операций выгружено в\n{path}")

    def _demo(self):
        n = self.app.db.load_demo_data()
        self.app.refresh_all()
        messagebox.showinfo("Демо-данные",
                            f"Добавлено записей: {n}. Графики и бюджеты наполнены.")

    def _wipe(self):
        if not messagebox.askyesno(
                "Очистка",
                "Удалить ВСЕ транзакции, бюджеты и счета?\n"
                "Действие необратимо — при желании сначала сделайте CSV-экспорт."):
            return
        self.app.db.wipe_data()
        self.app.refresh_all()


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    PAGES = [("dashboard", "Дашборд"), ("transactions", "Транзакции"),
             ("budgets", "Бюджеты"), ("finance", "Финансы"),
             ("settings", "Настройки")]

    def __init__(self):
        super().__init__()
        self.db = Database()

        # -- сохранённые настройки
        self.currency = self.db.get_setting("currency", DEFAULT_CURRENCY)
        self.theme = self.db.get_setting("theme", "dark")
        try:
            self.ui_scale = float(self.db.get_setting("ui_scale", "1.0"))
        except ValueError:
            self.ui_scale = 1.0
        ctk.set_appearance_mode(self.theme)
        ctk.set_default_color_theme("dark-blue")
        ctk.set_widget_scaling(self.ui_scale)

        today = dt.date.today()
        self.year, self.month = today.year, today.month
        self.current_page = "dashboard"

        self.title(WINDOW_TITLE)
        self.geometry(f"{max(MIN_W, 1280)}x{max(MIN_H, 800)}")
        self.minsize(MIN_W, MIN_H)
        self.configure(fg_color=ROOT_BG)

        # -- статичный градиентный фон
        self.grad_canvas = tk.Canvas(self, bd=0, highlightthickness=0)
        self.grad_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._grad_photo = None
        self.grad_canvas.bind("<Configure>", lambda e: self._draw_gradient())

        # -- каркас поверх градиента
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_sidebar()
        self._build_topbar()

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=1, column=1, sticky="nsew", padx=(0, 0))
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.pages = {
            "dashboard": DashboardPage(self.container, self),
            "transactions": TransactionsPage(self.container, self),
            "budgets": BudgetsPage(self.container, self),
            "finance": FinancePage(self.container, self),
            "settings": SettingsPage(self.container, self),
        }
        # страницы не размещаются заранее: show_page() держит в раскладке
        # ровно одну — иначе они перекрывают друг друга

        self._bind_hotkeys()
        self.show_page("dashboard")
        self._start_gradient()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.db.count_transactions() == 0:
            self.after(700, self._offer_demo)

    # -- каркас -----------------------------------------------------------------
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=196, corner_radius=0, fg_color=SIDEBAR,
                          border_width=0)
        sb.grid(row=0, column=0, rowspan=2, sticky="nsw")
        sb.grid_propagate(False)
        self.sidebar = sb

        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=18, pady=(20, 14))
        ctk.CTkLabel(logo, text="FINANCE", font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=("#101317", "#f2f4f7")).pack(anchor="w")
        ctk.CTkLabel(logo, text="TRACKER", font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=MUTED).pack(anchor="w")

        self.nav_buttons = {}
        for i, (key, label) in enumerate(self.PAGES):
            b = ctk.CTkButton(sb, text=f"  {i + 1}   {label}", anchor="w", height=38,
                              corner_radius=CORNER, fg_color="transparent",
                              hover_color=SIDEBAR_HOVER, text_color=("#20242b", "#c9ced6"),
                              font=ctk.CTkFont(size=13),
                              command=lambda k=key: self.show_page(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = b

        PrimaryButton(sb, text="＋ Транзакция  (Ctrl+N)", height=38,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self.open_transaction_dialog).pack(fill="x", padx=12, pady=(12, 4))
        GhostButton(sb, text="⇄ Перевод  (Ctrl+T)", height=34,
                    font=ctk.CTkFont(size=12),
                    command=self.open_transfer_dialog).pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(sb, text=f"v{APP_VERSION} by {AUTHOR}", font=ctk.CTkFont(size=10),
                     text_color=MUTED).pack(side="bottom", pady=10)

    def _build_topbar(self):
        tb = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color="transparent")
        tb.grid(row=0, column=1, sticky="ew")
        tb.grid_columnconfigure(1, weight=1)

        self.page_title = ctk.CTkLabel(tb, text="", font=ctk.CTkFont(size=17, weight="bold"))
        self.page_title.grid(row=0, column=0, sticky="w", padx=20)

        self.month_lbl = ctk.CTkLabel(tb, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.month_lbl.grid(row=0, column=2, padx=8)
        GhostButton(tb, text="‹", width=34, height=30,
                    command=lambda: self.change_month(-1)).grid(row=0, column=1, sticky="e")
        GhostButton(tb, text="›", width=34, height=30,
                    command=lambda: self.change_month(+1)).grid(row=0, column=3, padx=(0, 8))
        GhostButton(tb, text="Сегодня", width=84, height=30,
                    command=self.go_today).grid(row=0, column=4, padx=(0, 20))

    # -- градиент ----------------------------------------------------------------
    def _draw_gradient(self):
        """Статичный градиент: рисуется один раз и только при смене
        размера окна или темы — без фоновых перерисовок и мерцания."""
        try:
            w = self.grad_canvas.winfo_width()
            h = self.grad_canvas.winfo_height()
            if w < 20 or h < 20:
                return
            self.grad_canvas.delete("all")
            self._grad_photo = gradient_image(w, h, 0.8, Theme.is_dark())
            self.grad_canvas.create_image(0, 0, image=self._grad_photo, anchor="nw")
        except tk.TclError:
            pass

    def _start_gradient(self):
        self._draw_gradient()

    # -- горячие клавиши ------------------------------------------------------------
    def _bind_hotkeys(self):
        def guard(fn):
            def handler(event):
                w = self.grab_current()
                if w is not None:
                    try:
                        if w.winfo_toplevel() is not self:
                            return
                    except tk.TclError:
                        return
                fn()
                return "break"
            return handler

        self.bind_all("<Control-n>", guard(self.open_transaction_dialog))
        self.bind_all("<Control-t>", guard(self.open_transfer_dialog))
        self.bind_all("<Alt-Left>", guard(lambda: self.change_month(-1)))
        self.bind_all("<Alt-Right>", guard(lambda: self.change_month(+1)))
        for i, (key, _) in enumerate(self.PAGES, start=1):
            self.bind_all(f"<Control-Key-{i}>", guard(lambda k=key: self.show_page(k)))

    # -- навигация ------------------------------------------------------------------
    def show_page(self, key):
        self.current_page = key
        for k, b in self.nav_buttons.items():
            if k == key:
                b.configure(fg_color=PRIMARY, text_color=PRIMARY_TEXT,
                            font=ctk.CTkFont(size=13, weight="bold"))
            else:
                b.configure(fg_color="transparent", text_color=("#20242b", "#c9ced6"),
                            font=ctk.CTkFont(size=13))
        self.page_title.configure(text=dict(self.PAGES)[key])
        # однозначное переключение: активная страница в раскладке,
        # остальные полностью убраны (tkraise на CTk-виджетах ненадёжен)
        for k, page in self.pages.items():
            if k == key:
                page.grid(row=0, column=0, sticky="nsew", padx=16, pady=(0, 10))
            else:
                page.grid_forget()
        page = self.pages[key]
        page.refresh()
        self._update_month_lbl()

    def _update_month_lbl(self):
        self.month_lbl.configure(text=month_label(self.year, self.month))

    def change_month(self, delta):
        self.year, self.month = shift_month(self.year, self.month, delta)
        self._update_month_lbl()
        self.pages[self.current_page].refresh()

    def go_today(self):
        today = dt.date.today()
        self.year, self.month = today.year, today.month
        self._update_month_lbl()
        self.pages[self.current_page].refresh()

    # -- диалоги ---------------------------------------------------------------------
    def open_transaction_dialog(self):
        if not self.db.accounts():
            messagebox.showinfo("Сначала счёт",
                                "Создайте хотя бы один счёт в разделе «Финансы».")
            self.show_page("finance")
            return
        dlg = TransactionDialog(self, self.db, self.currency)
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            self.db.add_transaction(r["kind"], r["amount"], r["date"],
                                    r["category_id"], r["account_id"], r["note"])
            self.refresh_all()

    def open_transfer_dialog(self):
        dlg = TransferDialog(self, self.db, self.currency)
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            self.db.transfer(r["from_id"], r["to_id"], r["amount"], r["date"])
            self.refresh_all()

    def refresh_all(self):
        self._update_month_lbl()
        for p in self.pages.values():
            p.refresh()

    # -- настройки --------------------------------------------------------------------
    def set_currency(self, cur: str):
        cur = (cur or "").strip()
        if not cur:
            return
        self.currency = cur
        self.db.set_setting("currency", cur)
        self.refresh_all()

    def set_theme(self, theme: str):
        self.theme = theme
        ctk.set_appearance_mode(theme)
        self.db.set_setting("theme", theme)
        self._draw_gradient()
        self.refresh_all()

    def set_scale(self, scale: float):
        self.ui_scale = scale
        ctk.set_widget_scaling(scale)
        self.db.set_setting("ui_scale", str(scale))
        self.refresh_all()

    def _offer_demo(self):
        if messagebox.askyesno(
                "Добро пожаловать!",
                "В базе пока нет данных.\n\nЗагрузить демо-данные за 6 месяцев, чтобы "
                "посмотреть графики и бюджеты в деле?\n(Удаляются в Настройках)"):
            self.db.load_demo_data()
            self.refresh_all()

    def _on_close(self):
        self.db.close()
        try:
            for after_id in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(after_id)
        except Exception:
            pass
        # отложенное «будящее» событие: если окно свёрнуто, цикл событий после
        # quit() может уснуть в ожидании и не заметить флаг выхода
        try:
            self.after(1, lambda: None)
        except Exception:
            pass
        self.quit()
        try:
            self.destroy()
        except Exception:
            # при разборе дерева виджетов Tk может споткнуться о уже удалённые
            # команды (matplotlib-canvas и пр.) — mainloop уже остановлен,
            # процесс в любом случае завершается корректно
            pass


# ---------------------------------------------------------------------------
# Самопроверка (без GUI): python fintracker.py --selftest
# ---------------------------------------------------------------------------

def selftest():
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "fintracker_selftest.db")
    if os.path.exists(tmp):
        os.remove(tmp)
    db = Database(tmp)
    ok = []

    def check(name, cond):
        ok.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name)

    check("категории созданы", len(db.categories("expense")) >= 10)
    check("счета созданы", len(db.accounts()) == len(DEFAULT_ACCOUNTS))

    exp_cat = db.categories("expense")[0]
    inc_cat = db.categories("income")[0]
    acc, acc2 = db.accounts()[0], db.accounts()[1]
    today = dt.date.today()

    db.add_transaction("income", 100000, today.isoformat(), inc_cat[0], acc[0], "Зарплата")
    db.add_transaction("expense", 2500, today.isoformat(), exp_cat[0], acc[0], "Магазин")
    check("баланс счёта", abs(db.accounts()[0][2] - 97500) < 1e-6)

    tot = db.month_totals(today.year, today.month)
    check("итоги месяца", tot["income"] == 100000 and tot["expense"] == 2500)

    rows = db.fetch_transactions(year=today.year, month=today.month)
    check("выборка за месяц", len(rows) == 2)
    rows = db.fetch_transactions(kind="expense", search="Магазин")
    check("поиск", len(rows) == 1)

    db.set_budget(exp_cat[0], 5000)
    check("бюджет", db.budget_progress(exp_cat[0], today.year, today.month) == 2500)
    db.set_budget(exp_cat[0], 0)
    check("удаление бюджета нулём", len(db.budgets()) == 0)

    db.transfer(acc[0], acc2[0], 10000, today.isoformat())
    accs = {a[0]: a[2] for a in db.accounts()}
    check("перевод", abs(accs[acc[0]] - 87500) < 1e-6 and abs(accs[acc2[0]] - 10000) < 1e-6)

    db.delete_transaction(rows[0][0])
    check("удаление транзакции", db.count_transactions() == 3)

    # пополнение/снятие = транзакции, привязанные к счёту
    before = db.accounts()[0][2]
    db.add_transaction("income", 5000, today.isoformat(), inc_cat[0], acc[0], "Пополнение")
    check("пополнение счёта", abs(db.accounts()[0][2] - (before + 5000)) < 1e-6)

    db.set_budget(exp_cat[0], 3000)
    linked_tx = db.add_transaction("expense", 700, today.isoformat(),
                                   exp_cat[0], acc[0], "Тест категории")
    db.delete_category(exp_cat[0])
    check("удаление категории каскадом убирает бюджет", len(db.budgets()) == 0)
    orphan = db.fetch_transactions(kind="expense", search="Тест категории")
    check("транзакции удалённой категории сохранены",
          any(r[0] == linked_tx and r[4] == "—" for r in orphan))

    db.add_category("Спорт", "expense")
    try:
        db.add_category("Спорт", "expense")
        dup = False
    except ValueError:
        dup = True
    check("дубликат категории отклоняется", dup)

    db.rename_account(acc[0], "Карта Мир")
    check("переименование счёта",
          any(a[1] == "Карта Мир" for a in db.accounts()))
    db.delete_account(acc2[0])
    check("удаление счёта", all(a[0] != acc2[0] for a in db.accounts()))

    n_demo = db.load_demo_data()
    check("демо-данные", n_demo > 100 and db.count_transactions() > 100)
    check("чистая стоимость", isinstance(db.net_worth(), float))
    check("6 месяцев истории", len(db.last_months_totals(6)) == 6)

    csv_path = os.path.join(tempfile.gettempdir(), "fintracker_selftest.csv")
    n = db.export_csv(csv_path)
    check("экспорт CSV", n > 100 and os.path.exists(csv_path))
    os.remove(csv_path)

    db.set_setting("ui_scale", "1.1")
    check("настройки сохраняются", db.get_setting("ui_scale") == "1.1")

    db.wipe_data()
    check("очистка", db.count_transactions() == 0 and len(db.accounts()) == 3)
    db.close()
    os.remove(tmp)

    print(f"\n{sum(ok)}/{len(ok)} checks passed")
    return 0 if all(ok) else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
