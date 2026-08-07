# -*- coding: utf-8 -*-
"""
project_stat / watcher.py
Наблюдатель за папкой test_reports (эмуляция папки на сервере).

Логика:
  1. polling каждые POLL_INTERVAL_SEC
  2. новый *.csv -> SHA-256 -> если хэш неизвестен, парсим и пишем в БД
  3. файл переносим в archive/
  4. считаем партии, прошедшие все 4 участка
  5. при достижении FULL_CYCLES_TRIGGER -> analytics -> report -> запрос в ИИ

Запуск: python watcher.py --watch
"""
from __future__ import annotations
import argparse
import csv
import io
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from typing import List, Dict, Any, Tuple

import config as C
import db


LOG_PATH = os.path.join(C.LOGS_DIR, "watcher.log")


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────────
# ПАРСЕР CSV
# ──────────────────────────────────────────────────────────────────────────
def clean_cell(s: str) -> str:
    """Снимает один слой обрамляющих кавычек и пробелы.
    Реальные выгрузки часто оборачивают КАЖДОЕ поле в кавычки — без этого
    сравнение direction=='OUT' молча не срабатывает и отчёт остаётся пустым."""
    if s is None:
        return ""
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.strip()


def parse_csv(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Возвращает (movements, moisture_samples)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read()

    rdr = csv.reader(io.StringIO(text), delimiter=C.CSV_SEP)
    rows = [[clean_cell(c) for c in r] for r in rdr]

    header = None
    movements: List[Dict[str, Any]] = []
    moisture: List[Dict[str, Any]] = []

    for r in rows:
        if not r or all(c == "" for c in r):
            continue
        if r[0] == "#MOISTURE":
            if len(r) >= 4 and r[1] != "layer":
                moisture.append({"layer": r[1], "value": float(r[2]),
                                 "in_spec": int(r[3])})
            continue
        if header is None:
            header = r
            missing = [c for c in db.MOVEMENT_COLS if c not in header]
            if missing:
                raise ValueError(f"нет колонок: {missing}")
            continue
        d = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        if not d.get("batch_id"):
            continue
        movements.append(d)

    return movements, moisture


def load_file(con, path: str) -> Dict[str, Any]:
    fn = os.path.basename(path)
    sha = db.file_sha256(path)
    if db.is_loaded(con, sha):
        return {"status": "duplicate", "filename": fn}

    movements, moisture = parse_csv(path)
    if not movements:
        return {"status": "empty", "filename": fn}

    stage = int(movements[0]["stage"])
    batch = movements[0]["batch_id"]
    fid = db.insert_file(con, fn, sha, datetime.now().isoformat(timespec="seconds"),
                         len(movements), stage, batch)
    db.insert_movements(con, fid, movements)
    if moisture:
        db.insert_moisture(con, fid, batch, moisture)
    con.commit()
    return {"status": "loaded", "filename": fn, "stage": stage,
            "batch": batch, "rows": len(movements), "moisture": len(moisture)}


def archive(path: str) -> None:
    if not os.path.exists(path):
        return  # файл уже перенесён/удалён другим процессом — не падаем
    dst = os.path.join(C.ARCHIVE_DIR, os.path.basename(path))
    if os.path.exists(dst):
        base, ext = os.path.splitext(os.path.basename(path))
        dst = os.path.join(C.ARCHIVE_DIR, f"{base}_{int(time.time())}{ext}")
    try:
        shutil.move(path, dst)
    except (FileNotFoundError, OSError):
        # файл исчез между проверкой и move (гонка с параллельным watcher'ом)
        pass


# ──────────────────────────────────────────────────────────────────────────
# ТРИГГЕР АНАЛИТИКИ
# ──────────────────────────────────────────────────────────────────────────
def run_analysis(con, complete: List[str], use_ai: bool = True) -> str:
    """Аналитика + HTML-отчёт + запрос в ИИ. Возвращает путь к отчёту."""
    import analytics
    import report as report_mod

    log(f"ТРИГГЕР: полных циклов {len(complete)} -> запуск аналитики "
        f"({', '.join(complete)})")
    res = analytics.analyze(con, complete)

    ai_text = ""
    ai_model_used = None
    if use_ai:
        try:
            import ai_client
            # fallback (основная модель -> запасная, до N попыток) реализован
            # внутри ai_client.chat_with_fallback — единая логика для всего ПО.
            log(f"Запрос в ИИ (маршрут {C.AI_MODEL_ANALYTICS} -> "
                f"{C.AI_MODEL_ANALYTICS_FALLBACK}, таймаут {C.AI_TIMEOUT} с) ...")
            ai_text, ai_model_used = ai_client.chat_with_fallback(
                [{"role": "system", "content": ai_client.SYSTEM},
                 {"role": "user", "content": ai_client.ANALYSIS_TASK + "\n\n"
                  + ai_client.anonymize(ai_client.build_factsheet(res))}],
                primary=C.AI_MODEL_ANALYTICS,
                fallback=C.AI_MODEL_ANALYTICS_FALLBACK,
                timeout=C.AI_TIMEOUT)
            db.log_ai(con, datetime.now().isoformat(timespec="seconds"),
                      "assistant", ai_model_used, ai_text)
            con.commit()
            log(f"Ответ ИИ получен ({len(ai_text)} симв., модель {ai_model_used})")
        except Exception as e:
            ai_text = f"(ИИ недоступен: {e})"
            log(f"ОШИБКА ИИ: {e}")

    path = report_mod.build(res, ai_text)
    db.log_run(con, datetime.now().isoformat(timespec="seconds"), len(complete),
               ",".join(complete), path, 1 if ai_text and not ai_text.startswith("(ИИ") else 0)
    con.commit()
    log(f"Отчёт сохранён: {path}")
    return path


# ──────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ ЦИКЛ
# ──────────────────────────────────────────────────────────────────────────
def scan_once(con, state: Dict[str, Any], use_ai: bool = True) -> None:
    files = sorted(fn for fn in os.listdir(C.TEST_REPORTS)
                   if fn.lower().endswith(".csv"))
    if not files:
        return

    loaded_any = False
    for fn in files:
        path = os.path.join(C.TEST_REPORTS, fn)
        # файл может ещё дописываться — ждём стабилизации размера
        try:
            s1 = os.path.getsize(path)
            time.sleep(0.15)
            if os.path.getsize(path) != s1:
                continue
        except OSError:
            continue
        try:
            res = load_file(con, path)
        except Exception as e:
            log(f"ОШИБКА разбора {fn}: {e}")
            continue

        if res["status"] == "loaded":
            log(f"+ {fn}: участок {res['stage']}, партия {res['batch']}, "
                f"{res['rows']} строк" +
                (f", влажность {res['moisture']} замеров" if res["moisture"] else ""))
            loaded_any = True
        elif res["status"] == "duplicate":
            log(f"= {fn}: уже загружен (совпадение SHA-256), пропуск")
        else:
            log(f"! {fn}: пустой файл")
        archive(path)

    if not loaded_any:
        return

    complete = db.complete_batches(con)
    n = len(complete)
    if n != state.get("last_complete"):
        log(f"Полных циклов в БД: {n}/{C.FULL_CYCLES_TRIGGER}")
        state["last_complete"] = n

    # БД могла быть очищена извне (demo N) -> счётчик анализа сбрасываем
    if n < state.get("analyzed_at", 0):
        state["analyzed_at"] = 0

    if n >= C.FULL_CYCLES_TRIGGER and n > state.get("analyzed_at", 0):
        # ПОДНИМАЕМ флаг ДО запуска аналитики: иначе при длительном
        # прогоне (ИИ до ~3 мин) повторные тики снова запустят run_analysis
        # и сгенерят дубликаты отчёта (гонка триггера).
        state["analyzed_at"] = n
        try:
            run_analysis(con, complete, use_ai)
        except Exception:
            state["analyzed_at"] = 0   # при ошибке разрешаем повтор на след. цикле
            log("ОШИБКА аналитики:\n" + traceback.format_exc())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="режим наблюдения (по умолчанию)")
    ap.add_argument("--no-ai", action="store_true", help="без запроса в ИИ")
    ap.add_argument("--reset", action="store_true", help="очистить БД перед запуском")
    args = ap.parse_args()

    db.init()
    con = db.connect()

    if args.reset:
        for t in ("movements", "moisture", "files", "analysis_runs", "ai_dialog"):
            con.execute(f"DELETE FROM {t}")
        con.commit()
        log("БД очищена")

    st = db.stats(con)
    state = {"last_complete": len(st["complete"]), "analyzed_at": 0}
    log(f"Старт watcher. Папка: {C.TEST_REPORTS}")
    log(f"В БД: файлов {st['files']}, движений {st['movements']}, "
        f"полных циклов {len(st['complete'])}")
    log(f"Триггер аналитики: {C.FULL_CYCLES_TRIGGER} полных цикла. "
        f"Опрос каждые {C.POLL_INTERVAL_SEC} с. Ctrl+C для остановки.")

    try:
        while True:
            scan_once(con, state, use_ai=not args.no_ai)
            time.sleep(C.POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        log("Остановлен пользователем")
    finally:
        con.close()


if __name__ == "__main__":
    main()
