# -*- coding: utf-8 -*-
"""
project_stat / analytics.py
Расчётное ядро. ВСЕ числа считаются здесь детерминированно.
ИИ получает уже посчитанные агрегаты и только интерпретирует их.

Считает:
  1. Материальный баланс факт vs норматив по каждому участку
  2. Потери по этапам (м³/м², % и ₽)
  3. Три РАЗНЫХ узких места:
       (a) участок с максимальным отклонением от норматива
       (b) слой-лимитер комплекта (структурное ограничение)
       (c) отбраковка по влажности -> досушка
  4. Обратный прогноз: сколько леса на целевой объём доски
  5. Что-если: оптимальная доля дуба, оптимальная уставка сушилки
"""
from __future__ import annotations
import json
import math
from datetime import datetime
from typing import Dict, Any, List

import config as C
import db
import model as M


# ──────────────────────────────────────────────────────────────────────────
def _fact_batch(con, b: str) -> Dict[str, Any]:
    """Достаёт фактические величины партии из БД."""
    q = lambda **kw: db.qty(con, b, **kw)
    f: Dict[str, Any] = {"batch_id": b}

    f["in_oak"] = q(stage=1, direction="IN", species="дуб")
    f["in_bir"] = q(stage=1, direction="IN", species="береза")
    f["volume"] = f["in_oak"] + f["in_bir"]
    f["oak_share"] = f["in_oak"] / f["volume"] if f["volume"] else 0.0

    f["s1_out_oak"] = q(stage=1, direction="OUT", species="дуб")
    f["s1_out_bir"] = q(stage=1, direction="OUT", species="береза")
    f["s1_waste"] = q(stage=1, direction="WASTE")

    f["s2_cal_oak"] = q(stage=2, direction="OUT", material="Брус калиброванный", species="дуб")
    f["s2_cal_bir"] = q(stage=2, direction="OUT", material="Брус калиброванный", species="береза")
    f["s2_top_brus"] = q(stage=2, direction="OUT", material="Брус под ламель", layer="верхняя")
    f["s2_mid_brus"] = q(stage=2, direction="OUT", material="Брус сращенный", layer="средняя")
    # нижняя ламель — гетерогенная (берёза-отбор + дуб-остаток): сумма всех OUT-строк Уч.2
    # со слоем «нижняя» независимо от материала/породы
    f["s2_low_brus"] = q(stage=2, direction="OUT", layer="нижняя")
    f["s2_bot_brus"] = q(stage=2, direction="OUT", material="Брус под ламель", layer="нижняя")
    f["s2_waste"] = q(stage=2, direction="WASTE")

    f["s3_lam_m3"] = {L: q(stage=3, direction="OUT", material="Ламель", layer=L)
                      for L in C.LAYERS}
    f["s3_lam_m2"] = {L: M.m3_to_m2(f["s3_lam_m3"][L], L) for L in C.LAYERS}
    f["s3_saw_waste"] = q(stage=3, direction="WASTE", material="Щепа/опил")
    f["complect_m2"] = q(stage=3, direction="IN", material="Комплект ламелей")
    f["s3_semi_m2"] = q(stage=3, direction="OUT", material="Полуфабрикат")
    f["s3_glue_waste_m2"] = q(stage=3, direction="WASTE", material="Брак склейки")
    f["surplus_m2"] = {L: q(stage=3, direction="WASTE",
                            material="Ламель невостребованная", layer=L)
                       for L in C.LAYERS}
    f["s4_board_m2"] = q(stage=4, direction="OUT", material="Паркетная доска")
    f["s4_waste_m2"] = q(stage=4, direction="WASTE")

    # фактические коэффициенты выхода
    y: Dict[str, Any] = {}
    y["s1_дуб"] = f["s1_out_oak"] / f["in_oak"] if f["in_oak"] else 0
    y["s1_береза"] = f["s1_out_bir"] / f["in_bir"] if f["in_bir"] else 0
    y["s2cal_дуб"] = f["s2_cal_oak"] / f["s1_out_oak"] if f["s1_out_oak"] else 0
    y["s2cal_береза"] = f["s2_cal_bir"] / f["s1_out_bir"] if f["s1_out_bir"] else 0
    y["sel_top"] = f["s2_top_brus"] / f["s2_cal_oak"] if f["s2_cal_oak"] else 0
    y["sel_bot"] = f["s2_bot_brus"] / f["s2_cal_bir"] if f["s2_cal_bir"] else 0
    for L in C.LAYERS:
        brus = {"верхняя": f["s2_top_brus"], "средняя": f["s2_mid_brus"],
                "нижняя": f["s2_low_brus"]}[L]
        y[f"s3saw_{L}"] = f["s3_lam_m3"][L] / brus if brus else 0
    y["glue"] = f["s3_semi_m2"] / f["complect_m2"] if f["complect_m2"] else 0
    y["s4"] = f["s4_board_m2"] / f["s3_semi_m2"] if f["s3_semi_m2"] else 0
    f["yields"] = y

    f["limiting_layer"] = min(f["s3_lam_m2"], key=lambda L: f["s3_lam_m2"][L])
    f["overall_m2_per_m3"] = f["s4_board_m2"] / f["volume"] if f["volume"] else 0
    return f


NORM_KEYS = [
    ("s1_дуб",        lambda: C.YIELD_S1["дуб"],            1, "Уч.1 распиловка, дуб"),
    ("s1_береза",     lambda: C.YIELD_S1["береза"],         1, "Уч.1 распиловка, берёза"),
    ("s2cal_дуб",     lambda: C.YIELD_S2_CALIBRATION["дуб"], 2, "Уч.2 калибровка, дуб"),
    ("s2cal_береза",  lambda: C.YIELD_S2_CALIBRATION["береза"], 2, "Уч.2 калибровка, берёза"),
    ("sel_top",       lambda: C.SELECT_TOP_FROM_OAK,        2, "Уч.2 отбор на верхнюю"),
    ("sel_bot",       lambda: C.SELECT_BOTTOM_FROM_BIR,     2, "Уч.2 отбор на нижнюю"),
    ("s3saw_верхняя", lambda: C.YIELD_S3_SAWING["верхняя"], 3, "Уч.3 пиление, верхняя"),
    ("s3saw_средняя", lambda: C.YIELD_S3_SAWING["средняя"], 3, "Уч.3 пиление, средняя"),
    ("s3saw_нижняя",  lambda: C.YIELD_S3_SAWING["нижняя"],  3, "Уч.3 пиление, нижняя"),
    ("glue",          lambda: C.YIELD_S3_GLUING,            3, "Уч.3 склейка"),
    ("s4",            lambda: C.YIELD_S4,                   4, "Уч.4 профилирование"),
]


# ──────────────────────────────────────────────────────────────────────────
def analyze(con, batch_ids: List[str]) -> Dict[str, Any]:
    facts = [_fact_batch(con, b) for b in batch_ids]
    norms = [M.compute(f["volume"], C.OAK_SHARE) for f in facts]

    total_vol = sum(f["volume"] for f in facts)
    total_board = sum(f["s4_board_m2"] for f in facts)
    norm_board = sum(n["s4_board_m2"] for n in norms)

    # ── 1. Отклонения коэффициентов по операциям ─────────────────────────
    ops = []
    for key, getnorm, stage, title in NORM_KEYS:
        nv = getnorm()
        vals = [f["yields"][key] for f in facts]
        avg = sum(vals) / len(vals)
        ops.append({
            "key": key, "stage": stage, "title": title,
            "norm": nv, "fact_avg": avg,
            "dev_rel": (avg / nv - 1.0) if nv else 0.0,
            "per_batch": [{"batch": f["batch_id"], "value": f["yields"][key],
                           "dev_rel": (f["yields"][key] / nv - 1.0) if nv else 0.0}
                          for f in facts],
        })

    # ── 2. Потери по этапам, в м³-эквиваленте и деньгах ──────────────────
    def m2_sandwich_m3(m2):
        return sum(M.m2_to_m3(m2, L) for L in C.LAYERS)

    losses = []
    s1w = sum(f["s1_waste"] for f in facts)
    s2w = sum(f["s2_waste"] for f in facts)
    s3w = sum(f["s3_saw_waste"] for f in facts)
    s3g = sum(f["s3_glue_waste_m2"] for f in facts)
    s4w = sum(f["s4_waste_m2"] for f in facts)
    surplus_m3 = sum(sum(M.m2_to_m3(f["surplus_m2"][L], L) for L in C.LAYERS) for f in facts)
    surplus_m2 = {L: sum(f["surplus_m2"][L] for f in facts) for L in C.LAYERS}

    losses.append({"stage": 1, "name": "Уч.1 Распиловка круглого леса",
                   "loss_m3": s1w, "unit": "м³", "kind": "щепа",
                   "share_of_input": s1w / total_vol if total_vol else 0,
                   "rub": s1w * C.PRICES["chips_m3"]})
    losses.append({"stage": 2, "name": "Уч.2 Калибровка и отбор",
                   "loss_m3": s2w, "unit": "м³", "kind": "щепа",
                   "share_of_input": s2w / total_vol if total_vol else 0,
                   "rub": s2w * C.PRICES["chips_m3"]})
    losses.append({"stage": 3, "name": "Уч.3 Пиление ламелей",
                   "loss_m3": s3w, "unit": "м³", "kind": "щепа",
                   "share_of_input": s3w / total_vol if total_vol else 0,
                   "rub": s3w * C.PRICES["chips_m3"]})
    losses.append({"stage": 3, "name": "Уч.3 Склейка (брак)",
                   "loss_m3": m2_sandwich_m3(s3g), "loss_m2": s3g, "unit": "м²",
                   "kind": "брак",
                   "share_of_input": m2_sandwich_m3(s3g) / total_vol if total_vol else 0,
                   "rub": s3g * C.PRICES["board_m2"]})
    losses.append({"stage": 3, "name": "Уч.3 Излишек слоёв (структурный)",
                   "loss_m3": surplus_m3, "unit": "м³", "kind": "структурный",
                   "share_of_input": surplus_m3 / total_vol if total_vol else 0,
                   "rub": surplus_m3 * C.PRICES["chips_m3"]})
    losses.append({"stage": 4, "name": "Уч.4 Профилирование (брак)",
                   "loss_m3": m2_sandwich_m3(s4w), "loss_m2": s4w, "unit": "м²",
                   "kind": "брак",
                   "share_of_input": m2_sandwich_m3(s4w) / total_vol if total_vol else 0,
                   "rub": s4w * C.PRICES["board_m2"]})

    # ── 3. Узкие места (три РАЗНЫХ типа) ─────────────────────────────────
    def _lost_m2_if_fixed(o):
        """Недобор доски (м²) за период, если операцию вернуть к нормативу."""
        lost = 0.0
        if o["dev_rel"] >= 0:
            return 0.0
        for f in facts:
            y = M.norm_yields()
            fy = f["yields"]
            y["s1"] = {"дуб": fy["s1_дуб"], "береза": fy["s1_береза"]}
            y["s2cal"] = {"дуб": fy["s2cal_дуб"], "береза": fy["s2cal_береза"]}
            y["sel_top"], y["sel_bot"] = fy["sel_top"], fy["sel_bot"]
            y["s3saw"] = {L: fy[f"s3saw_{L}"] for L in C.LAYERS}
            y["glue"], y["s4"] = fy["glue"], fy["s4"]
            cur = M.compute(f["volume"], f["oak_share"], y)
            y2 = json_clone(y)
            k = o["key"]
            if k.startswith("s1_"):
                y2["s1"][k[3:]] = o["norm"]
            elif k.startswith("s2cal_"):
                y2["s2cal"][k[6:]] = o["norm"]
            elif k.startswith("s3saw_"):
                y2["s3saw"][k[6:]] = o["norm"]
            else:
                y2[k] = o["norm"]
            fixed = M.compute(f["volume"], f["oak_share"], y2)
            lost += fixed["s4_board_m2"] - cur["s4_board_m2"]
        return lost

    for o in ops:
        o["lost_m2"] = _lost_m2_if_fixed(o)
    # выбираем операцию не по относительному %, а по реальному урону в доске:
    # отклонение лимитирующего слоя (дуб) бьёт по выходу сильнее, чем
    # отклонение перекормленного слоя (берёза) при той же относительной величине.
    worst = max((o for o in ops if o["dev_rel"] < 0),
                key=lambda o: o["lost_m2"], default=min(ops, key=lambda o: o["dev_rel"]))
    lost_m2_by_dev = worst["lost_m2"]

    mst = db.moisture_stats(con, batch_ids)
    # оптимальная уставка сушилки: минимизируем взвешенную долю досушки
    best_sp, best_cost = None, None
    sp = C.MOISTURE_MIN
    while sp <= C.MOISTURE_MAX + 1e-9:
        w = 0.0
        for L in C.LAYERS:
            share = M.rework_share(L, mu=sp)
            w += share * sum(f["s3_lam_m2"][L] for f in facts)
        if best_cost is None or w < best_cost:
            best_cost, best_sp = w, sp
        sp += 0.05
    cur_rework_m2 = sum(mst[L]["rework_share"] * sum(f["s3_lam_m2"][L] for f in facts)
                        for L in C.LAYERS)

    # ── 3b. Статистическая значимость отклонения операции-лимитера ──────
    # ВАЖНО: при малом числе партий отклонение может быть шумом.
    # Одновыборочный t-критерий: факт vs норматив. Считаем p и
    # минимально нужное число партий для power=80% (α=0.05).
    sig = {}
    if worst["per_batch"]:
        vals = [pb["value"] for pb in worst["per_batch"]]
        nn = len(vals)
        mm = sum(vals) / nn
        var = sum((v - mm) ** 2 for v in vals) / max(1, nn - 1)
        sdd = math.sqrt(var)
        sem = sdd / math.sqrt(nn) if nn else 0.0
        tt = (mm - worst["norm"]) / sem if sem else 0.0
        # p ≈ через erf-аппроксимацию нормального (двусторонний);
        # для df=3 это грубо, но достаточно для вывода «не значимо».
        pp = 2 * (1 - 0.5 * (1 + math.erf(abs(tt) / math.sqrt(2)))) if tt else 1.0
        delta = abs(mm - worst["norm"])
        # N для power 80%: ((z_a + z_b)·σ / δ)^2  (z_a=1.96, z_b=0.84)
        need_n = (((1.96 + 0.84) * sdd / delta) ** 2) if delta else float("inf")
        sig = {
            "key": worst["key"], "title": worst["title"],
            "n": nn, "mean": mm, "norm": worst["norm"],
            "sd": sdd, "sem": sem, "t": tt, "p_approx": pp,
            "significant_at_05": pp < 0.05,
            "need_n_for_sig80": math.ceil(need_n) if delta else None,
        }

    bottlenecks = {
        "a_deviation": {
            "type": "Отклонение от норматива",
            "title": worst["title"], "stage": worst["stage"],
            "norm": worst["norm"], "fact": worst["fact_avg"],
            "dev_rel": worst["dev_rel"],
            "lost_board_m2": lost_m2_by_dev,
            "lost_rub": lost_m2_by_dev * C.PRICES["board_m2"],
            "lost_m2": lost_m2_by_dev,
            "significance": sig,
            "explanation": (
                "Природа проблемы — операционная: состояние оборудования, режимы, "
                "входной контроль заготовки. Норматив заложен в процесс, отклонение "
                "говорит о том, что фактический режим не держится. "
                "Эта операция выбрана как самое узкое место по реальному недобору "
                f"доски за период ({lost_m2_by_dev:,.0f} м²), а не по относительному %: "
                "при равном отклонении сильнее бьёт то, что режет дефицитный слой. "
                + ("Коэффициент относится к дубу — верхней ламели, которая является "
                   "лимитером комплекта, поэтому его отклонение напрямую режет выход "
                   "готовой доски, даже если по % оно равно отклонению берёзы."
                   if "дуб" in worst["title"] else
                   "У берёзы (средняя/нижняя) отклонение бьёт слабее, так как эти слои "
                   "и так перекормлены и не ограничивают комплект.")
            ),
            "recommendation": (
                f"Вернуть коэффициент «{worst['title']}» к нормативу через наладку "
                f"режимов и оборудования, усилить входной контроль заготовки."
            ),
        },
        "b_structural": {
            "type": "Структурное ограничение комплекта",
        "limiting_layer": _aggregate_limiting_layer(facts),
            "surplus_m2": surplus_m2,
            "surplus_m3": surplus_m3,
            "frozen_rub": surplus_m3 * C.PRICES["chips_m3"],
            "note": "Слой-лимитер задаёт комплект; остальные слои производятся "
                    "сверх потребности и не могут быть склеены.",
            "explanation": (
                f"Слой-лимитер — {_aggregate_limiting_layer(facts)}: он задаёт объём "
                f"комплекта, остальные слои производятся сверх потребности "
                f"(излишек {surplus_m3:.2f} м³ = "
                f"{int(surplus_m3 * C.PRICES['chips_m3']):,} ₽ замороженного ресурса). "
                f"В комплекте нужно по одной площади каждого слоя "
                f"(верх:сред:низ = 1:1:1 по площади). По объёму затраченной древесины "
                f"из-за разной толщины ламелей (верх {C.THICKNESS_MM['верхняя']}, "
                f"сред {C.THICKNESS_MM['средняя']}, низ {C.THICKNESS_MM['нижняя']} мм) "
                f"соотношение 1:2:1 — средняя ламель съедает вдвое больше бруса. "
                f"Причина перекорма средней и нижней — планирование закупки: верхняя "
                f"ламель делается только из дуба ({C.OAK_SHARE*100:.0f}% закупки) и "
                f"упирается в его объём, а средняя и нижняя набираются из берёзы и "
                f"дубового остатка."
            ),
            "recommendation": (
                "Поднять долю дуба в закупке, чтобы снять структурное ограничение "
                "комплекта (см. блок «Что-если: доля дуба»)."
            ),
        },
        "c_moisture": {
            "type": "Отбраковка по влажности (досушка)",
            "by_layer": {L: {"n": mst[L]["n"], "avg": mst[L]["avg"],
                             "rework_share": mst[L]["rework_share"],
                             "spec": list(C.MOISTURE_SPEC[L])} for L in C.LAYERS},
            "current_setpoint": C.DRYER_SETPOINT,
            "rework_m2": cur_rework_m2,
            "rework_rub": cur_rework_m2 * C.REWORK_COST_PER_M2,
            "optimal_setpoint": round(best_sp, 2),
            "optimal_rework_m2": best_cost,
            "saving_rub": max(0.0, (cur_rework_m2 - best_cost) * C.REWORK_COST_PER_M2),
            "explanation": (
                f"Уставка сушильной камеры — {C.DRYER_SETPOINT:.1f}% влажности. "
                f"На досушку уходит {cur_rework_m2:,.0f} м² ламели "
                f"({int(cur_rework_m2 * C.REWORK_COST_PER_M2):,} ₽ при "
                f"{C.REWORK_COST_PER_M2:.0f} ₽/м²). Допуск верхней ламели — "
                f"{C.MOISTURE_SPEC['верхняя'][0]:g}–{C.MOISTURE_SPEC['верхняя'][1]:g}%; "
                f"при уставке на границе допуска часть распределения влажности "
                f"выходит за неё и идёт на досушку."
            ),
            "recommendation": (
                (f"Скорректировать уставку с {C.DRYER_SETPOINT:.1f}% до "
                 f"{round(best_sp, 2):g}% — досушка сократится с "
                 f"{cur_rework_m2:,.0f} до {best_cost:,.0f} м², "
                 f"экономия {int(max(0.0, (cur_rework_m2 - best_cost) * C.REWORK_COST_PER_M2)):,} ₽ "
                 f"за период. Снижение уставки означает более сухую древесину."
                 if abs(round(best_sp, 2) - C.DRYER_SETPOINT) > 0.01
                 else f"Уставка {C.DRYER_SETPOINT:.1f}% уже оптимальна (расчётный "
                      f"оптимум {round(best_sp, 2):g}%); заметной экономии на досушке "
                      f"нет, коррекция уставки не требуется.")
            ),
        },
    }

    # ── 4. Экономика ─────────────────────────────────────────────────────
    econ_batches = []
    for f, n in zip(facts, norms):
        raw = f["in_oak"] * C.PRICES["roundwood_дуб"] + f["in_bir"] * C.PRICES["roundwood_береза"]
        rev = f["s4_board_m2"] * C.PRICES["board_m2"]
        chips = (f["s1_waste"] + f["s2_waste"] + f["s3_saw_waste"])
        rev_ch = chips * C.PRICES["chips_m3"]
        econ_batches.append({
            "batch": f["batch_id"], "volume": f["volume"],
            "board_m2": f["s4_board_m2"], "norm_board_m2": n["s4_board_m2"],
            "delta_m2": f["s4_board_m2"] - n["s4_board_m2"],
            "raw_cost_rub": raw, "board_revenue_rub": rev,
            "chips_revenue_rub": rev_ch, "margin_rub": rev + rev_ch - raw,
            "m2_per_m3": f["overall_m2_per_m3"],
        })

    econ = {
        "total_volume_m3": total_vol,
        "total_board_m2": total_board,
        "norm_board_m2": norm_board,
        "delta_board_m2": total_board - norm_board,
        "delta_board_rub": (total_board - norm_board) * C.PRICES["board_m2"],
        "raw_cost_rub": sum(e["raw_cost_rub"] for e in econ_batches),
        "board_revenue_rub": sum(e["board_revenue_rub"] for e in econ_batches),
        "chips_revenue_rub": sum(e["chips_revenue_rub"] for e in econ_batches),
        "margin_rub": sum(e["margin_rub"] for e in econ_batches),
        "by_batch": econ_batches,
    }

    # ── 5. Что-если: доля дуба ───────────────────────────────────────────
    # ВАЖНО: считаем ДВЕ цифры. Прирост выручки (Δм² × цена) завышает эффект,
    # т.к. игнорирует удорожание корзины — дуб дороже берёзы втрое.
    # Честный показатель — прирост МАРЖИ с учётом стоимости сырья.
    pts, best = M.scan_oak_share(100.0)
    base = M.compute(100.0, C.OAK_SHARE)
    opt = M.compute(100.0, best["oak_share"])
    econ_base, econ_opt = M.batch_economics(base), M.batch_economics(opt)
    scale = total_vol / 100.0
    whatif_oak = {
        "current_share": C.OAK_SHARE,
        "current_board_m2": base["s4_board_m2"],
        "optimal_share": best["oak_share"],
        "optimal_board_m2": best["board_m2"],
        "gain_rel": best["board_m2"] / base["s4_board_m2"] - 1.0,
        "gain_m2_on_period": (best["board_m2"] - base["s4_board_m2"]) * scale,
        "gain_rub_on_period": (best["board_m2"] - base["s4_board_m2"]) * scale
                              * C.PRICES["board_m2"],
        # честные показатели с учётом удорожания сырья
        "raw_cost_up_rub": (econ_opt["raw_cost_rub"]
                            - econ_base["raw_cost_rub"]) * scale,
        "gain_margin_rub": (econ_opt["margin_rub"]
                            - econ_base["margin_rub"]) * scale,
        "curve": [{"x": p["oak_share"], "y": p["board_m2"],
                   "lim": p["limiting_layer"]} for p in pts],
        "explanation": (
            f"Механизм: при {C.OAK_SHARE*100:.0f}% дуба верхняя ламель (только из дуба) "
            f"— дефицитный слой, она и ограничивает комплект. Рост доли дуба "
            f"выравнивает слои, пока лимитером не станет средняя ламель."
        ),
        "recommendation": (
            f"Изменить долю дуба в закупке с {C.OAK_SHARE*100:.0f}% до "
            f"{best['oak_share']*100:.1f}% — честный прирост маржи "
            f"{int((econ_opt['margin_rub'] - econ_base['margin_rub']) * scale):,} ₽ "
            f"за период (выручка +{int((best['board_m2'] - base['s4_board_m2']) * scale * C.PRICES['board_m2']):,}, "
            f"но сырьё дорожает на {int((econ_opt['raw_cost_rub'] - econ_base['raw_cost_rub']) * scale):,})."
        ),
    }

    # ── 6. Обратный прогноз ──────────────────────────────────────────────
    avg_m2_per_m3 = total_board / total_vol if total_vol else 0
    forecast_examples = []
    for tgt in (5000.0, 10000.0):
        by_norm = M.required_roundwood(tgt)
        v_fact = tgt / avg_m2_per_m3 if avg_m2_per_m3 else 0
        forecast_examples.append({
            "target_m2": tgt,
            "by_norm_m3": by_norm["roundwood_m3"],
            "by_fact_m3": v_fact,
            "extra_m3": v_fact - by_norm["roundwood_m3"],
            "extra_rub": (v_fact - by_norm["roundwood_m3"]) *
                         (C.OAK_SHARE * C.PRICES["roundwood_дуб"] +
                          (1 - C.OAK_SHARE) * C.PRICES["roundwood_береза"]),
        })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "batches": batch_ids,
        "n_cycles": len(batch_ids),
        "facts": facts,
        "norms": norms,
        "ops": ops,
        "losses": losses,
        "bottlenecks": bottlenecks,
        "economics": econ,
        "whatif_oak": whatif_oak,
        "moisture": mst,
        "forecast": {"avg_m2_per_m3": avg_m2_per_m3,
                     "norm_m2_per_m3": M.compute(1.0)["s4_board_m2"],
                     "examples": forecast_examples},
        "prices": C.PRICES,
    }


def json_clone(o):
    return json.loads(json.dumps(o))


def _aggregate_limiting_layer(facts: List[Dict[str, Any]]) -> str:
    """Слой-лимитер = тот, чьего выхода меньше всего в сумме по всем партиям.

    Раньше брался limiting_layer только из ПЕРВОЙ партии (facts[0]) — на реальных
    данных с разными лимитерами по партиям это давало неверный ответ. Теперь
    суммируем s3_lam_m2 по всем партиям и выбираем минимальный слой.
    """
    totals: Dict[str, float] = {L: 0.0 for L in C.LAYERS}
    for f in facts:
        for L in C.LAYERS:
            totals[L] += f.get("s3_lam_m2", {}).get(L, 0.0)
    return min(totals, key=totals.get)


def forecast(target_m2: float, mode: str = "fact",
             avg_m2_per_m3: float = None, oak_share: float = None) -> Dict[str, Any]:
    """Обратный прогноз для UI. mode: 'norm' — по нормативам, 'fact' — по факту."""
    oak_share = C.OAK_SHARE if oak_share is None else oak_share
    if mode == "fact" and avg_m2_per_m3:
        k = avg_m2_per_m3
    else:
        k = M.compute(1.0, oak_share)["s4_board_m2"]
    v = target_m2 / k if k else 0
    return {
        "target_m2": target_m2, "mode": mode, "m2_per_m3": k,
        "roundwood_m3": v, "oak_m3": v * oak_share, "birch_m3": v * (1 - oak_share),
        "oak_share": oak_share,
        "cost_rub": v * oak_share * C.PRICES["roundwood_дуб"]
                    + v * (1 - oak_share) * C.PRICES["roundwood_береза"],
        "revenue_rub": target_m2 * C.PRICES["board_m2"],
    }


if __name__ == "__main__":
    con = db.connect()
    b = db.complete_batches(con)
    print("Полных циклов:", len(b), b)
    if len(b) >= C.FULL_CYCLES_TRIGGER:
        r = analyze(con, b[:C.FULL_CYCLES_TRIGGER])
        print(json.dumps({
            "board": r["economics"]["total_board_m2"],
            "delta_rub": r["economics"]["delta_board_rub"],
            "bottleneck_a": r["bottlenecks"]["a_deviation"]["title"],
            "dev": r["bottlenecks"]["a_deviation"]["dev_rel"],
            "limiter": r["bottlenecks"]["b_structural"]["limiting_layer"],
            "opt_setpoint": r["bottlenecks"]["c_moisture"]["optimal_setpoint"],
            "opt_oak": r["whatif_oak"]["optimal_share"],
        }, ensure_ascii=False, indent=2))
    con.close()
