# -*- coding: utf-8 -*-
"""
project_stat / model.py
Детерминированная модель техпроцесса «круглый лес → паркетная доска».

Один и тот же движок используют:
  • gen_test_data.py — генерация синтетики (нормативы + случайное отклонение)
  • analytics.py     — эталон для сравнения с фактом, обратный прогноз, что-если

Единицы: до склейки — м³, после — м².
Перевод: м² = м³ / (толщина_мм / 1000).
"""
from __future__ import annotations
import copy
from typing import Dict, Any

import config as C


# ──────────────────────────────────────────────────────────────────────────
# НОРМАТИВНЫЕ КОЭФФИЦИЕНТЫ
# ──────────────────────────────────────────────────────────────────────────
def norm_yields() -> Dict[str, Any]:
    """Плоский словарь всех коэффициентов цепочки — то, что можно «крутить»."""
    return {
        "s1":       dict(C.YIELD_S1),
        "s2cal":    dict(C.YIELD_S2_CALIBRATION),
        "sel_top":  C.SELECT_TOP_FROM_OAK,
        "sel_bot":  C.SELECT_BOTTOM_FROM_BIR,
        "joint_oak": C.JOINT_OAK_REST,
        "joint_bir": C.JOINT_BIRCH_REST,
        "s3saw":    dict(C.YIELD_S3_SAWING),
        "glue":     C.YIELD_S3_GLUING,
        "s4":       C.YIELD_S4,
    }


def m3_to_m2(v_m3: float, layer: str) -> float:
    return v_m3 / (C.THICKNESS_MM[layer] / 1000.0)


def m2_to_m3(v_m2: float, layer: str) -> float:
    return v_m2 * (C.THICKNESS_MM[layer] / 1000.0)


# ──────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ РАСЧЁТ ЦЕПОЧКИ
# ──────────────────────────────────────────────────────────────────────────
def compute(volume: float,
            oak_share: float = None,
            y: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    volume    — м³ круглого леса на входе участка 1
    oak_share — доля дуба в закупке
    y         — словарь коэффициентов (norm_yields() или построенный в gen_test_data)
    """
    oak_share = C.OAK_SHARE if oak_share is None else oak_share
    y = norm_yields() if y is None else y

    r = {"volume": volume, "oak_share": oak_share, "yields": y}

    # ── вход ──────────────────────────────────────────────────────────────
    r["in_oak"] = volume * oak_share
    r["in_bir"] = volume * (1.0 - oak_share)

    # ── Участок 1: круглый лес → брус ─────────────────────────────────────
    r["s1_out_oak"] = r["in_oak"] * y["s1"]["дуб"]
    r["s1_out_bir"] = r["in_bir"] * y["s1"]["береза"]
    r["s1_waste_oak"] = r["in_oak"] - r["s1_out_oak"]
    r["s1_waste_bir"] = r["in_bir"] - r["s1_out_bir"]

    # ── Участок 2а: калибровка ────────────────────────────────────────────
    r["s2_cal_oak"] = r["s1_out_oak"] * y["s2cal"]["дуб"]
    r["s2_cal_bir"] = r["s1_out_bir"] * y["s2cal"]["береза"]
    r["s2_calwaste_oak"] = r["s1_out_oak"] - r["s2_cal_oak"]
    r["s2_calwaste_bir"] = r["s1_out_bir"] - r["s2_cal_bir"]

    # ── Участок 2б: отбор бруса на слои ───────────────────────────────────
    # ПРАВИЛО МАРШРУТИЗАЦИИ ОТХОДОВ (согласовано с заказчиком):
    #   дуб отбирается 60% в верхнюю; остаток дуба на 50% уходит в НИЖНЮЮ
    #   ламель (через сращивание), 50% — в щепу.
    #   берёза отбирается sel_bot в нижнюю; остаток берёзы на 90% уходит в
    #   СРЕДНЮЮ ламель (через сращивание), 10% — в щепу.
    #   => средняя = ТОЛЬКО сращённый берёза-остаток; нижняя = берёза-отбор + дуб-остаток.
    r["s2_top_brus"] = r["s2_cal_oak"] * y["sel_top"]          # дуб → верхняя
    r["s2_rest_oak"] = r["s2_cal_oak"] - r["s2_top_brus"]
    r["s2_oak_to_low"] = r["s2_rest_oak"] * y["joint_oak"]     # дуб-остаток → нижняя
    r["s2_selwaste_oak"] = r["s2_rest_oak"] - r["s2_oak_to_low"]

    r["s2_bot_brus"] = r["s2_cal_bir"] * y["sel_bot"]          # берёза → нижняя
    r["s2_rest_bir"] = r["s2_cal_bir"] - r["s2_bot_brus"]
    r["s2_joint_bir"] = r["s2_rest_bir"] * y["joint_bir"]      # берёза-остаток → средняя
    r["s2_selwaste_bir"] = r["s2_rest_bir"] - r["s2_joint_bir"]

    r["s2_mid_brus"] = r["s2_joint_bir"]                       # средняя = только берёза-остаток
    r["s2_low_brus"] = r["s2_bot_brus"] + r["s2_oak_to_low"]   # нижняя = берёза-отбор + дуб-остаток

    # ── Участок 3а: пиление бруса на ламели (м³) ──────────────────────────
    brus_by_layer = {
        "верхняя": r["s2_top_brus"],
        "средняя": r["s2_mid_brus"],
        "нижняя":  r["s2_low_brus"],
    }
    r["s3_brus_in"] = brus_by_layer
    r["s3_lam_m3"] = {L: brus_by_layer[L] * y["s3saw"][L] for L in C.LAYERS}
    r["s3_sawwaste_m3"] = {L: brus_by_layer[L] - r["s3_lam_m3"][L] for L in C.LAYERS}
    r["s3_lam_m2"] = {L: m3_to_m2(r["s3_lam_m3"][L], L) for L in C.LAYERS}

    # ── Участок 3б: склейка. Комплект ограничен дефицитным слоем ──────────
    complect = min(r["s3_lam_m2"].values())
    r["complect_m2"] = complect
    r["limiting_layer"] = min(r["s3_lam_m2"], key=lambda L: r["s3_lam_m2"][L])
    r["surplus_m2"] = {L: r["s3_lam_m2"][L] - complect for L in C.LAYERS}
    r["surplus_m3"] = {L: m2_to_m3(r["surplus_m2"][L], L) for L in C.LAYERS}

    r["s3_semi_m2"] = complect * y["glue"]
    r["s3_gluewaste_m2"] = complect - r["s3_semi_m2"]

    # ── Участок 4: профилирование ─────────────────────────────────────────
    r["s4_board_m2"] = r["s3_semi_m2"] * y["s4"]
    r["s4_waste_m2"] = r["s3_semi_m2"] - r["s4_board_m2"]

    # ── Сквозные показатели ───────────────────────────────────────────────
    r["overall_m2_per_m3"] = r["s4_board_m2"] / volume if volume else 0.0
    board_m3 = m2_to_m3(r["s4_board_m2"], "верхняя") \
             + m2_to_m3(r["s4_board_m2"], "средняя") \
             + m2_to_m3(r["s4_board_m2"], "нижняя")     # «сэндвич» 20 мм
    r["board_m3_equiv"] = board_m3
    r["overall_volume_yield"] = board_m3 / volume if volume else 0.0

    return r


# ──────────────────────────────────────────────────────────────────────────
# ВЛАЖНОСТЬ: доля ламели, уходящей на досушку (возврат в цикл)
# ──────────────────────────────────────────────────────────────────────────
def _norm_cdf(x: float) -> float:
    import math
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def rework_share(layer: str, mu: float = None, sigma: float = None) -> float:
    """Ожидаемая доля ламели вне допуска влажности → на досушку."""
    mu = C.DRYER_SETPOINT if mu is None else mu
    sigma = C.MOISTURE_SIGMA if sigma is None else sigma
    lo, hi = C.MOISTURE_SPEC[layer]
    # усечение генеральным диапазоном измерения 5..10
    tl, th = C.MOISTURE_MIN, C.MOISTURE_MAX
    z = lambda v: _norm_cdf((v - mu) / sigma)
    total = z(th) - z(tl)
    if total <= 0:
        return 0.0
    inside = max(0.0, min(z(hi), z(th)) - max(z(lo), z(tl)))
    return max(0.0, 1.0 - inside / total)


def sample_moisture(rng, mu: float = None, sigma: float = None,
                    lo: float = None, hi: float = None) -> float:
    """Одно измерение влажности.

    Распределение — нормальное вокруг mu (уставка сушилки) с разбросом sigma,
    усечённое ЗАДАННЫМ диапазоном [lo, hi] (допустимый коридор по слою),
    а не общим диапазоном прибора 5..10. Средний слой принимает любую влажность
    из среза прибора; верхний/нижний — в своих более узких коридорах.
    """
    mu = C.SYNTH["moisture_mu"] if mu is None else mu
    sigma = C.SYNTH["moisture_sigma"] if sigma is None else sigma
    lo = C.MOISTURE_MIN if lo is None else lo
    hi = C.MOISTURE_MAX if hi is None else hi
    for _ in range(50):
        v = rng.gauss(mu, sigma)
        if lo <= v <= hi:
            return round(v, 2)
    return round(min(max(mu, lo), hi), 2)


# ──────────────────────────────────────────────────────────────────────────
# ОБРАТНЫЙ ПРОГНОЗ: сколько леса нужно на целевой объём доски
# ──────────────────────────────────────────────────────────────────────────
def required_roundwood(target_m2: float,
                       oak_share: float = None,
                       y: Dict[str, Any] = None) -> Dict[str, float]:
    """
    Цепочка линейна по объёму → достаточно посчитать удельный выход на 1 м³
    и поделить. Никакого ИИ здесь не нужно: это арифметика, а LLM на числах
    ошибается.
    """
    base = compute(1.0, oak_share, y)
    k = base["s4_board_m2"]                       # м² доски с 1 м³ леса
    if k <= 0:
        raise ValueError("нулевой удельный выход")
    v = target_m2 / k
    oak_share = C.OAK_SHARE if oak_share is None else oak_share
    return {
        "target_m2": target_m2,
        "m2_per_m3": k,
        "roundwood_m3": v,
        "oak_m3": v * oak_share,
        "birch_m3": v * (1.0 - oak_share),
        "cost_rub": v * oak_share * C.PRICES["roundwood_дуб"]
                    + v * (1.0 - oak_share) * C.PRICES["roundwood_береза"],
    }


# ──────────────────────────────────────────────────────────────────────────
# ЧТО-ЕСЛИ: оптимальная доля дуба
# ──────────────────────────────────────────────────────────────────────────
def scan_oak_share(volume: float = 100.0,
                   y: Dict[str, Any] = None,
                   lo: float = 0.10, hi: float = 0.60, step: float = 0.005):
    """Скан доли дуба → выход доски. Возвращает (точки, оптимум)."""
    pts, best = [], None
    a = lo
    while a <= hi + 1e-9:
        r = compute(volume, a, y)
        row = {
            "oak_share": round(a, 4),
            "board_m2": r["s4_board_m2"],
            "complect_m2": r["complect_m2"],
            "limiting_layer": r["limiting_layer"],
            "margin_rub": _batch_margin(r),
        }
        pts.append(row)
        if best is None or row["board_m2"] > best["board_m2"]:
            best = row
        a += step
    return pts, best


def _batch_margin(r: Dict[str, Any]) -> float:
    """Грубая маржа партии: выручка(доска+щепа) − стоимость сырья."""
    cost = r["in_oak"] * C.PRICES["roundwood_дуб"] \
         + r["in_bir"] * C.PRICES["roundwood_береза"]
    rev_board = r["s4_board_m2"] * C.PRICES["board_m2"]
    chips_m3 = (r["s1_waste_oak"] + r["s1_waste_bir"]
                + r["s2_calwaste_oak"] + r["s2_calwaste_bir"]
                + r["s2_selwaste_oak"] + r["s2_selwaste_bir"]
                + sum(r["s3_sawwaste_m3"].values()))
    rev_chips = chips_m3 * C.PRICES["chips_m3"]
    return rev_board + rev_chips - cost


def batch_economics(r: Dict[str, Any]) -> Dict[str, float]:
    """Развёрнутая экономика одной партии."""
    cost = r["in_oak"] * C.PRICES["roundwood_дуб"] \
         + r["in_bir"] * C.PRICES["roundwood_береза"]
    rev_board = r["s4_board_m2"] * C.PRICES["board_m2"]
    chips_m3 = (r["s1_waste_oak"] + r["s1_waste_bir"]
                + r["s2_calwaste_oak"] + r["s2_calwaste_bir"]
                + r["s2_selwaste_oak"] + r["s2_selwaste_bir"]
                + sum(r["s3_sawwaste_m3"].values()))
    rev_chips = chips_m3 * C.PRICES["chips_m3"]
    frozen = sum(m2_to_m3(r["surplus_m2"][L], L) for L in C.LAYERS)
    return {
        "raw_cost_rub": cost,
        "board_revenue_rub": rev_board,
        "chips_m3": chips_m3,
        "chips_revenue_rub": rev_chips,
        "margin_rub": rev_board + rev_chips - cost,
        "frozen_surplus_m3": frozen,
        "frozen_surplus_rub": frozen * C.PRICES["chips_m3"],
    }


if __name__ == "__main__":
    r = compute(100.0)
    print(f"Эталон на 100 м³ (дуб {C.OAK_SHARE:.0%}):")
    print(f"  Уч.1 брус:      дуб {r['s1_out_oak']:.3f} / берёза {r['s1_out_bir']:.3f} м³")
    print(f"  Уч.2 калибр.:   дуб {r['s2_cal_oak']:.3f} / берёза {r['s2_cal_bir']:.3f} м³")
    print(f"  Уч.2 отбор:     верх {r['s2_top_brus']:.3f} / средн {r['s2_mid_brus']:.3f} / низ {r['s2_bot_brus']:.3f} м³")
    for L in C.LAYERS:
        print(f"  Уч.3 ламель {L:8s}: {r['s3_lam_m3'][L]:.3f} м³ = {r['s3_lam_m2'][L]:.1f} м²  (досушка {rework_share(L):.1%})")
    print(f"  Комплект:       {r['complect_m2']:.1f} м²  лимитер={r['limiting_layer']}")
    print(f"  Излишек:        " + " / ".join(f"{L} {r['surplus_m2'][L]:.1f}" for L in C.LAYERS))
    print(f"  Полуфабрикат:   {r['s3_semi_m2']:.1f} м²")
    print(f"  Готовая доска:  {r['s4_board_m2']:.1f} м²  ({r['overall_volume_yield']:.1%} по объёму)")
    e = batch_economics(r)
    print(f"  Маржа партии:   {e['margin_rub']:,.0f} ₽")
    pts, best = scan_oak_share(100.0)
    print(f"  Оптимум дуба:   {best['oak_share']:.1%} → {best['board_m2']:.1f} м² "
          f"(+{best['board_m2']/r['s4_board_m2']-1:.2%})")
