# -*- coding: utf-8 -*-
"""Программная проверка GUI: размеры виджетов, градиент, отрисовка графиков.
Работает на временной БД — пользовательские данные не затрагиваются."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fintracker

# временная БД с демо-данными — не трогаем реальную базу пользователя
_tmpdb = os.path.join(tempfile.gettempdir(), "ft_verify_gui.db")
if os.path.exists(_tmpdb):
    os.remove(_tmpdb)
fintracker.DB_PATH = _tmpdb
# default-аргумент path=DB_PATH связывается при импорте — правим и его
fintracker.Database.__init__.__defaults__ = (_tmpdb,)

from fintracker import App, messagebox

messagebox.askyesno = lambda *a, **k: False   # демо загрузим явно
messagebox.showinfo = lambda *a, **k: None
errors = []
checks = []
import time as _time
_T0 = _time.time()


def check(name, cond, extra=""):
    checks.append(bool(cond))
    print(f"[{_time.time() - _T0:7.2f}s] " + ("PASS " if cond else "FAIL ") + name
          + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond:
        errors.append(name)


def run():
    app = App()
    app.geometry("1300x820+50+50")
    # внешние запросы закрытия окна (менеджер сессии и пр.) игнорируем:
    # тест сам завершит приложение в конце
    app.protocol("WM_DELETE_WINDOW", lambda: None)
    if app.db.count_transactions() == 0:
        app.db.load_demo_data()
        app.refresh_all()

    # страховка: тест не может висеть вечно
    def watchdog():
        print("WATCHDOG: принудительное завершение", flush=True)
        app.db.close()
        os._exit(2)
    app.after(150000, watchdog)

    def phase1():
        app.deiconify()
        app.update_idletasks()
        app.update()
        check("окно не скрыто приложением", app.state() != "withdrawn", app.state())
        check("градиентный фон нарисован", app._grad_photo is not None)
        items = app.grad_canvas.find_all()
        check("на canvas градиента есть изображение", len(items) > 0)

        # дашборд: KPI и графики
        d = app.pages["dashboard"]
        check("KPI доходы непустые", "—" not in d.kpi_income["value"].cget("text"),
              d.kpi_income["value"].cget("text"))
        check("график тренда отрисован",
              len(d.trend.fig.axes) > 0 and d.trend._wid.winfo_width() > 100)
        check("круговая диаграмма отрисована", len(d.pie.fig.axes) > 0)

        # каждая страница: размеры корня ненулевые + в раскладке ровно она одна
        for key, page in app.pages.items():
            app.show_page(key)
            # состояние раскладки синхронно: проверяем сразу после переключения
            mapped = [k for k, p in app.pages.items() if bool(p.grid_info())]
            check(f"«{key}»: в раскладке ровно одна страница", mapped == [key], str(mapped))
            app.update_idletasks()
            app.update()
            w, h = page.winfo_width(), page.winfo_height()
            check(f"страница «{key}» имеет размер", w > 100 and h > 100, f"{w}x{h}")

        check("пять разделов в навигации", len(app.pages) == 5, str(len(app.pages)))

        # дашборд: таблица последних операций заполнена
        d_rows = d.table.list_frame.winfo_children()
        check("дашборд: таблица операций заполнена", len(d_rows) >= 5,
              f"{len(d_rows)} строк")

        # бюджеты: карточки существуют
        b = app.pages["budgets"]
        cards = [c for c in b.body.winfo_children()]
        check("бюджеты: карточки построены", len(cards) >= 3, f"{len(cards)} карточек")

        # финансы: карточки счетов и кнопки
        f = app.pages["finance"]
        accs = f.body.winfo_children()
        check("финансы: карточки счетов", len(accs) >= 3, f"{len(accs)}")

        # транзакции: строки в таблице
        t = app.pages["transactions"]
        rows = t.table.list_frame.winfo_children()
        check("транзакции: строки таблицы", len(rows) > 10, f"{len(rows)} строк")

        phase2_small()

    def phase2_small():
        # маленькое окно: всё перестраивается без вылета за границы
        app.geometry("900x620+50+50")
        app.after(1400, phase2_check)

    def phase2_check():
        app.deiconify()
        for key in ("dashboard", "finance", "budgets", "settings", "transactions"):
            app.show_page(key)
            app.update_idletasks()
            app.update()
            page = app.pages[key]
            pw = page.winfo_width()
            # ищем виджеты, вылезающие за правую границу страницы
            overflow = []
            def scan(w):
                try:
                    if w.winfo_x() + w.winfo_width() > pw + 40 and w.winfo_width() > 30:
                        overflow.append((w.winfo_class(), w.winfo_x() + w.winfo_width()))
                    for c in w.winfo_children():
                        scan(c)
                except Exception:
                    pass
            scan(page)
            check(f"«{key}» 900x620: ничего не вылезает", not overflow, str(overflow[:3]))

        phase3_light()

    def phase3_light():
        app.set_theme("light")
        app.show_page("dashboard")
        app.after(800, phase3_check)

    def phase3_check():
        app.deiconify()
        app.update_idletasks()
        check("светлая тема переключилась",
              __import__("customtkinter").get_appearance_mode() == "Light")
        d = app.pages["dashboard"]
        check("графики перерисованы в светлой теме", len(d.trend.fig.axes) > 0)
        app.set_theme("dark")
        check("тёмная тема вернулась",
              __import__("customtkinter").get_appearance_mode() == "Dark")

        # хоткеи — с паузами между событиями, как в реальной жизни
        def hk1():
            app.deiconify()
            app.focus_force()
            app.show_page("dashboard")
            app.update()
            app.event_generate("<Alt-Right>")
            app.after(150, hk2)

        def hk2():
            app.deiconify()
            app.update()
            t = __import__("datetime").date.today()
            check("Alt+Right переключил месяц", (app.year, app.month) != (t.year, t.month))
            app.event_generate("<Control-Key-3>")
            app.after(150, hk3)

        def hk3():
            app.update()
            check("Ctrl+3 открыл раздел Бюджеты", app.current_page == "budgets")
            print(f"\n{sum(checks)}/{len(checks)} checks passed")
            print("SMOKE OK" if not errors else "SMOKE FAILED: " + "; ".join(errors))
            app.db.close()
            os._exit(0 if not errors else 1)   # минуя teardown Tcl

        hk1()

    app.after(1200, phase1)
    try:
        app.mainloop()
    except Exception:
        pass  # гонка при teardown не отменяет результат проверок


if __name__ == "__main__":
    run()
