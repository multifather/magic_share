# -*- coding: utf-8 -*-
"""
project_stat / gen_test_data.py
Генератор синтетических отчётов участков.

10 партий (BATCH_VOLUMES, м³) × 4 участка = 40 CSV в test_reports/.
Скрытые факторы состояния партии (см. config.SYNTH), в ПРОЦЕНТНЫХ ПУНКТАХ
от норматива:
  • качество сырья — асимметрично вниз (до -10 п.п.) / вверх (до +2 п.п.);
  • калибровка ±3 п.п.; отбор на слои ±4 п.п. — произвольно по циклам;
  • пиление ламелей ±3 п.п.; склейка ±1 п.п.; профилирование ±2 п.п.
  • влажность — нормальное распределение около уставки 7.0, σ=0.5, в коридоре
    5.5..8.5, с послойными окнами приёмки в склейку.
Асимметрия сырья даёт стабильно ловимое узкое место на Уч.1 (распиловка).

Единая схема CSV (разделитель ';'), long-формат — один парсер на все участки:
report_id;timestamp;batch_id;stage;operation;direction;material;species;layer;
thickness_mm;qty;unit;operator

Опции:
  --drip N   пауза N сек между записью файлов (для демонстрации watcher'а)
  --clean    очистить test_reports (и archive) перед генерацией
"""
from __future__ import annotations
import argparse
import csv
import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta

import config as C
import model as M

OPERATORS = ["Оператор-А", "Оператор-Б", "Оператор-В", "Оператор-Г"]
MOISTURE_SAMPLES_PER_LAYER = 40      # выборка замеров влажности на слой


def _row(rid, ts, batch, stage, op, direction, material,
         species="", layer="", thick="", qty=0.0, unit="m3", operator=""):
    return {
        "report_id": rid,
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "batch_id": batch,
        "stage": stage,
        "operation": op,
        "direction": direction,
        "material": material,
        "species": species,
        "layer": layer,
        "thickness_mm": thick,
        "qty": f"{qty:.4f}",
        "unit": unit,
        "operator": operator,
    }


def build_batch(idx: int, volume: float, rng: random.Random, t0: datetime):
    """Возвращает список (filename, rows, moisture_rows) для одной партии.

    Скрытые факторы состояния партии (в ПРОЦЕНТНЫХ ПУНКТАХ от норматива):
      • качество сырья — асимметрично: до -10 вниз / +2 вверх (систематический
        перекос вниз = ловимое узкое место Уч.1);
      • калибровка ±3; отбор ±4 — произвольно по циклам;
      • пиление ламелей ±3; склейка ±1; профилирование ±2 — произвольно по циклам.
    """
    batch = f"B{idx + 1:03d}"
    S = C.SYNTH
    # фиксируем seed прогона, чтобы отчёт мог его показать (воспроизводимость показа)
    C.CURRENT_SEED = CURRENT_SEED if CURRENT_SEED is not None else "random"

    # ── скрытые факторы состояния партии (в ПРОЦЕНТНЫХ ПУНКТАХ от норматива) ──
    # 1. Качество сырья: асимметрично вниз (до -10) / вверх (до +2)
    d_raw = rng.uniform(-S["raw_quality_pp_down"], S["raw_quality_pp_up"])
    # 2. Калибровка: ±calibration_pp произвольно
    d_cal = rng.uniform(-S["calibration_pp"], S["calibration_pp"])
    # 3. Отбор на слои: ±selection_pp произвольно
    d_sel = rng.uniform(-S["selection_pp"], S["selection_pp"])
    # 4. Пиление бруса на ламели: ±sawing_pp (в обе стороны)
    d_saw = rng.uniform(-S["sawing_pp"], S["sawing_pp"])
    # 5. Склейка ламелей в полуфабрикат: ±gluing_pp
    d_glue = rng.uniform(-S["gluing_pp"], S["gluing_pp"])
    # 6. Профилирование полуфабриката в доску: ±profile_pp
    d_prof = rng.uniform(-S["profile_pp"], S["profile_pp"])

    # построим нормативы с учётом факторов
    y = M.norm_yields()
    y["s1"]["дуб"]    *= (1.0 + d_raw / 100.0)
    y["s1"]["береза"] *= (1.0 + d_raw / 100.0)
    y["s2cal"]["дуб"]    *= (1.0 + d_cal / 100.0)
    y["s2cal"]["береза"] *= (1.0 + d_cal / 100.0)
    y["sel_top"]  *= (1.0 + d_sel / 100.0)
    y["sel_bot"]  *= (1.0 + d_sel / 100.0)
    y["joint_oak"] *= (1.0 + d_sel / 100.0)
    y["joint_bir"] *= (1.0 + d_sel / 100.0)
    for L in C.LAYERS:
        y["s3saw"][L] *= (1.0 + d_saw / 100.0)
    y["glue"] *= (1.0 + d_glue / 100.0)
    y["s4"]   *= (1.0 + d_prof / 100.0)

    r = M.compute(volume, C.OAK_SHARE, y)

    files = []
    # ── УЧАСТОК 1 ─────────────────────────────────────────────────────────
    ts = t0
    rid = f"{batch}-S1"
    rows = [
        _row(rid, ts, batch, 1, "Приемка круглого леса", "IN", "Круглый лес",
             "дуб", qty=r["in_oak"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 1, "Приемка круглого леса", "IN", "Круглый лес",
             "береза", qty=r["in_bir"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 1, "Распиловка", "OUT", "Брус",
             "дуб", qty=r["s1_out_oak"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 1, "Распиловка", "OUT", "Брус",
             "береза", qty=r["s1_out_bir"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 1, "Распиловка", "WASTE", "Щепа/опил",
             "дуб", qty=r["s1_waste_oak"]),
        _row(rid, ts, batch, 1, "Распиловка", "WASTE", "Щепа/опил",
             "береза", qty=r["s1_waste_bir"]),
    ]
    files.append((f"{batch}_stage1_{ts:%Y%m%d_%H%M%S}.csv", rows, []))

    # ── УЧАСТОК 2 ─────────────────────────────────────────────────────────
    ts = t0 + timedelta(hours=3)
    rid = f"{batch}-S2"
    rows = [
        _row(rid, ts, batch, 2, "Приемка бруса", "IN", "Брус", "дуб",
             qty=r["s1_out_oak"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 2, "Приемка бруса", "IN", "Брус", "береза",
             qty=r["s1_out_bir"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 2, "Калибровка", "OUT", "Брус калиброванный", "дуб",
             qty=r["s2_cal_oak"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 2, "Калибровка", "OUT", "Брус калиброванный", "береза",
             qty=r["s2_cal_bir"], operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 2, "Калибровка", "WASTE", "Щепа/опил", "дуб",
             qty=r["s2_calwaste_oak"]),
        _row(rid, ts, batch, 2, "Калибровка", "WASTE", "Щепа/опил", "береза",
             qty=r["s2_calwaste_bir"]),
        # отбор на слои (верхняя — дуб)
        _row(rid, ts, batch, 2, "Отбор на слой", "OUT", "Брус под ламель", "дуб",
             "верхняя", C.THICKNESS_MM["верхняя"], r["s2_top_brus"],
             operator=rng.choice(OPERATORS)),
        # нижняя ламель — гетерогенная: берёза-отбор + дуб-остаток (обе идут в нижнюю)
        _row(rid, ts, batch, 2, "Отбор на слой", "OUT", "Брус под ламель", "береза",
             "нижняя", C.THICKNESS_MM["нижняя"], r["s2_bot_brus"],
             operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 2, "Сращивание остатка", "OUT", "Брус сращенный", "дуб",
             "нижняя", C.THICKNESS_MM["нижняя"], r["s2_oak_to_low"],
             operator=rng.choice(OPERATORS)),
        # средняя ламель — только сращённый берёза-остаток
        _row(rid, ts, batch, 2, "Сращивание остатка", "OUT", "Брус сращенный", "береза",
             "средняя", C.THICKNESS_MM["средняя"], r["s2_joint_bir"],
             operator=rng.choice(OPERATORS)),
        _row(rid, ts, batch, 2, "Отбор на слой", "WASTE", "Щепа/опил", "дуб",
             qty=r["s2_selwaste_oak"]),
        _row(rid, ts, batch, 2, "Отбор на слой", "WASTE", "Щепа/опил", "береза",
             qty=r["s2_selwaste_bir"]),
    ]
    files.append((f"{batch}_stage2_{ts:%Y%m%d_%H%M%S}.csv", rows, []))

    # ── УЧАСТОК 3 ─────────────────────────────────────────────────────────
    ts = t0 + timedelta(hours=7)
    rid = f"{batch}-S3"
    rows = []
    for L in C.LAYERS:
        rows.append(_row(rid, ts, batch, 3, "Приемка бруса", "IN", "Брус под ламель",
                         "", L, C.THICKNESS_MM[L], r["s3_brus_in"][L],
                         operator=rng.choice(OPERATORS)))
    for L in C.LAYERS:
        rows.append(_row(rid, ts, batch, 3, "Пиление ламелей", "OUT", "Ламель",
                         "", L, C.THICKNESS_MM[L], r["s3_lam_m3"][L], "m3",
                         rng.choice(OPERATORS)))
        rows.append(_row(rid, ts, batch, 3, "Пиление ламелей", "WASTE", "Щепа/опил",
                         "", L, C.THICKNESS_MM[L], r["s3_sawwaste_m3"][L]))
    # склейка — учёт в м² по верхней ламели
    rows.append(_row(rid, ts, batch, 3, "Склейка", "IN", "Комплект ламелей",
                     "", "верхняя", C.THICKNESS_MM["верхняя"],
                     r["complect_m2"], "m2", rng.choice(OPERATORS)))
    rows.append(_row(rid, ts, batch, 3, "Склейка", "OUT", "Полуфабрикат",
                     "", "", "", r["s3_semi_m2"], "m2", rng.choice(OPERATORS)))
    rows.append(_row(rid, ts, batch, 3, "Склейка", "WASTE", "Брак склейки",
                     "", "", "", r["s3_gluewaste_m2"], "m2"))
    # излишек слоёв, не вошедший в комплект — замороженный ресурс
    for L in C.LAYERS:
        if r["surplus_m2"][L] > 1e-9:
            rows.append(_row(rid, ts, batch, 3, "Излишек слоя", "WASTE", "Ламель невостребованная",
                             "", L, C.THICKNESS_MM[L], r["surplus_m2"][L], "m2"))

    # замеры влажности: генерируются из общего коридора процесса 5.5..8.5
    # (распределение N(7.0, sigma), усечённое коридором), а годность к склейке
    # (in_spec) считается ПОСТФАКТУМ против послойного окна приёмки
    # (средняя — любая, верхняя 6.1..7.6, нижняя 6.3..8.3).
    moist = []
    GENERAL_RANGE = (5.5, 8.5)
    moist_ranges = {
        "верхняя": (6.1, 7.6),
        "средняя": (5.5, 8.5),   # любая влажность в пределах общего коридора
        "нижняя":  (6.3, 8.3),
    }
    for L in C.LAYERS:
        lo_spec, hi_spec = moist_ranges[L]
        for _ in range(MOISTURE_SAMPLES_PER_LAYER):
            v = M.sample_moisture(rng, lo=GENERAL_RANGE[0], hi=GENERAL_RANGE[1])
            moist.append({"layer": L, "value": v,
                          "in_spec": 1 if lo_spec <= v <= hi_spec else 0})
    files.append((f"{batch}_stage3_{ts:%Y%m%d_%H%M%S}.csv", rows, moist))

    # ── УЧАСТОК 4 ─────────────────────────────────────────────────────────
    ts = t0 + timedelta(hours=11)
    rid = f"{batch}-S4"
    rows = [
        _row(rid, ts, batch, 4, "Приемка полуфабриката", "IN", "Полуфабрикат",
             "", "", "", r["s3_semi_m2"], "m2", rng.choice(OPERATORS)),
        _row(rid, ts, batch, 4, "Профилирование", "OUT", "Паркетная доска",
             "", "", "", r["s4_board_m2"], "m2", rng.choice(OPERATORS)),
        _row(rid, ts, batch, 4, "Профилирование", "WASTE", "Брак профилирования",
             "", "", "", r["s4_waste_m2"], "m2"),
    ]
    files.append((f"{batch}_stage4_{ts:%Y%m%d_%H%M%S}.csv", rows, []))

    meta = {"batch": batch, "volume": volume, "calc": r,
            "factors": {"raw_pp": d_raw, "cal_pp": d_cal, "sel_pp": d_sel,
                        "saw_pp": d_saw, "glue_pp": d_glue, "prof_pp": d_prof}}
    return files, meta


def write_csv(path: str, rows, moisture):
    with open(path, "w", encoding=C.CSV_ENCODING, newline="") as f:
        w = csv.writer(f, delimiter=C.CSV_SEP, lineterminator="\r\n")
        w.writerow(["report_id", "timestamp", "batch_id", "stage", "operation",
                    "direction", "material", "species", "layer", "thickness_mm",
                    "qty", "unit", "operator"])
        for r in rows:
            w.writerow([r["report_id"], r["timestamp"], r["batch_id"], r["stage"],
                        r["operation"], r["direction"], r["material"], r["species"],
                        r["layer"], r["thickness_mm"], r["qty"], r["unit"], r["operator"]])
        if moisture:
            w.writerow([])
            w.writerow(["#MOISTURE", "layer", "value", "in_spec"])
            for m in moisture:
                w.writerow(["#MOISTURE", m["layer"], f"{m['value']:.2f}", m["in_spec"]])


def reset_all() -> None:
    """Полный сброс: БД и все папки с CSV. Для демо-стенда."""
    try:
        db_path = C.DB_PATH
        if os.path.exists(db_path):
            import sqlite3
            con = sqlite3.connect(db_path)
            for t in ("movements", "moisture", "files", "analysis_runs", "ai_dialog"):
                con.execute(f"DELETE FROM {t}")
            con.commit()
            con.close()
            print("[reset] БД очищена")
    except Exception as e:
        print(f"[reset] БД: {e}")
    for d in (C.TEST_REPORTS, C.ARCHIVE_DIR):
        try:
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                if os.path.isfile(p) and fn.lower().endswith(".csv"):
                    os.remove(p)
            print(f"[reset] {d} очищена")
        except Exception as e:
            print(f"[reset] {d}: {e}")


def generate_once(rng: random.Random, t0: datetime, drip: float) -> None:
    total = 0
    print(f"Генерация: партии {C.BATCH_VOLUMES} м³")
    print(f"  SEED={CURRENT_SEED}  BASE_TIME={t0:%Y-%m-%d %H:%M}")
    print(f"  Сырьё: асимметрия вниз до -{C.SYNTH['raw_quality_pp_down']:.0f} п.п. / "
          f"вверх +{C.SYNTH['raw_quality_pp_up']:.0f} п.п.")
    for i, vol in enumerate(C.BATCH_VOLUMES):
        files, meta = build_batch(i, vol, rng, t0 + timedelta(days=i))
        for fn, rows, moist in files:
            write_csv(os.path.join(C.TEST_REPORTS, fn), rows, moist)
            total += 1
            print(f"  {fn}  ({len(rows)} строк)")
            if drip > 0:
                time.sleep(drip)
        c = meta["calc"]; f = meta["factors"]
        print(f"  == {meta['batch']}: {vol} м³ -> доска {c['s4_board_m2']:.1f} м² "
              f"({c['overall_volume_yield']:.1%}), лимитер={c['limiting_layer']} "
              f"| сырьё {f['raw_pp']:+.1f}п.п.")
    print(f"Готово: {total} файлов в {C.TEST_REPORTS}")


CURRENT_SEED = None  # заполняется в main для печати в generate_once


def main():
    global CURRENT_SEED
    ap = argparse.ArgumentParser()
    ap.add_argument("--drip", type=float, default=4.0,
                    help="пауза в секундах между файлами (для демонстрации watcher)")
    ap.add_argument("--clean", action="store_true", help="очистить test_reports перед генерацией")
    ap.add_argument("--seed", type=int, default=None,
                    help="фиксированный seed (для воспроизводимости); без флага — случайный")
    ap.add_argument("--interactive", action="store_true",
                    help="демо-стенд: полный сброс и цикл N=новая генерация / E=выход")
    args = ap.parse_args()

    if args.clean:
        for d in (C.TEST_REPORTS, C.ARCHIVE_DIR):
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                if os.path.isfile(p) and fn.lower().endswith(".csv"):
                    os.remove(p)
        print("[clean] test_reports очищена")

    if not args.interactive:
        # одноразовый режим (для тестов / ручного прогона)
        seed = args.seed if args.seed is not None else int(time.time() * 1000) & 0x7fffffff
        CURRENT_SEED = seed
        rng = random.Random(seed)
        t0 = datetime(2026, 7, 27, 7, 0, 0) if args.seed is not None else \
             datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(days=random.Random(seed).randint(0, 30))
        generate_once(rng, t0, args.drip)
        return

    # ── интерактивный демо-стенд ──
    print("=" * 60)
    print(" DEMO STAND — генератор синтетических отчётов")
    print("=" * 60)
    # пауза, чтобы окна успели встать на места до старта генерации
    for i in range(10, 0, -1):
        print(f"  Старт генерации через {i} с... (окна уже на местах)", end="\r", flush=True)
        time.sleep(1)
    print("")
    while True:
        reset_all()
        seed = int(time.time() * 1000) & 0x7fffffff
        CURRENT_SEED = seed
        rng = random.Random(seed)
        # случайное базовое время: случайный день в прошлом + 07:00
        base_day = datetime.now().date() - timedelta(days=random.Random(seed).randint(0, 30))
        t0 = datetime(base_day.year, base_day.month, base_day.day, 7, 0, 0)
        generate_once(rng, t0, args.drip)
        print("")
        print("  Нажмите [N] — новая генерация (полный сброс БД и папок)")
        print("  Нажмите [E] — выход")
        print("  > ", end="", flush=True)
        try:
            key = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            key = "e"
        if key == "e":
            print("Выход.")
            break
        # любой ключ кроме 'e' — новая генерация (в т.ч. 'n')
        if key != "n":
            print("(повторите: N — новая генерация, E — выход)")
            continue
        print("")


if __name__ == "__main__":
    main()
