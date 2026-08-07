# -*- coding: utf-8 -*-
"""
project_stat / ai_client.py
Клиент к OpenAI-совместимому эндпоинту (FreeQwenApi / локальная модель).

ПРИНЦИП: ИИ НЕ СЧИТАЕТ. Все числа приходят уже рассчитанными из analytics.py.
Модель отвечает за интерпретацию, приоритизацию и формулировку мероприятий.
Причина: LLM систематически ошибается в арифметике, а проверка её вывода
обходится дороже, чем прямой расчёт.

ЛОКАЛЬНЫЙ РЕЖИМ (AI_MODE='local'): эндпоинт LM Studio OpenAI-совместимый (:1234/v1). При multiple-loaded моделях обязателен явный model (уже шлётся в chat()). Reasoning у Qwen3.5 гасится через chat_template_kwargs.enable_thinking.

БЕЗОПАСНОСТЬ: AI_MODE='cloud' означает, что запрос уходит во внешний сервис.
При ANONYMIZE=True из промпта вычищаются идентификаторы (партии, операторы).
Для реального контура — AI_MODE='local'.

FALLBACK: маршрут «основная модель -> запасная» реализован ЗДЕСЬ, в клиенте,
а не у вызывающего кода. Поэтому и автоматический конвейер watcher'а, и
любые UI-запросы (/api/ask, /api/explain, /api/reanalyze) получают одну и ту же
логику отказоустойчивости.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

import config as C


class AIError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────────────────
def _post(payload: Dict[str, Any], timeout: int = None) -> Dict[str, Any]:
    url = C.AI_BASE_URL.rstrip("/") + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout or C.AI_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AIError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise AIError(f"нет связи с {url}: {e.reason}")


def ping() -> Dict[str, Any]:
    """Проверка доступности эндпоинта и списка моделей."""
    url = C.AI_BASE_URL.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "models": [m["id"] for m in d.get("data", [])][:20],
                "mode": C.AI_MODE, "url": C.AI_BASE_URL}
    except Exception as e:
        return {"ok": False, "error": str(e), "mode": C.AI_MODE, "url": C.AI_BASE_URL}


def chat(messages: List[Dict[str, str]], model: str = None,
         timeout: int = None) -> str:
    payload = {"model": model or C.AI_MODEL_CHAT, "messages": messages}
    # Qwen3.5 — reasoning-модель; на локальном iGPU reasoning платит 2x latency
    # и провоцирует "допересчёт" чисел вопреки инструкции SYSTEM. Гасим, если
    # выключено в конфиге. (В cloud-режиме FreeQwenApi этот параметр не шлём.)
    if C.AI_MODE == "local" and not getattr(C, "AI_ENABLE_THINKING", True):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if getattr(C, "AI_MAX_TOKENS", 0):
        payload["max_tokens"] = C.AI_MAX_TOKENS
    # Для ЛЁГКОЙ модели (1.5B) держим низкую temperature: меньше бреда и
    # «самодеятельности» с числами. На 9b можно поднять до 0.4-0.7.
    payload["temperature"] = float(getattr(C, "AI_TEMPERATURE", 0.2))
    resp = _post(payload, timeout)
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise AIError(f"неожиданный ответ: {json.dumps(resp, ensure_ascii=False)[:300]}")


def anonymize(text: str) -> str:
    """Убирает идентификаторы перед отправкой во внешний сервис."""
    if not C.ANONYMIZE:
        return text
    text = re.sub(r"Оператор-[А-ЯA-Z]\w*", "оператор", text)
    text = re.sub(r"\bB(\d{3})\b", lambda m: f"партия-{int(m.group(1))}", text)
    return text


SYSTEM = (
    "Ты — производственный аналитик деревообрабатывающего предприятия "
    "(производство паркетной доски). Тебе передают УЖЕ РАССЧИТАННЫЕ показатели "
    "материального баланса. Категорически не пересчитывай числа и не выдумывай "
    "новые — используй только те, что даны. Единицы измерения бери строго из "
    "исходных данных: не подставляй градусы Цельсия, проценты или кубометры "
    "там, где единица не указана явно. Твоя задача: объяснить причины, "
    "расставить приоритеты и предложить конкретные мероприятия. "
    "Отвечай по-русски, сжато, без воды и без похвал. Структурируй по пунктам. "
    "Если данных для вывода не хватает — прямо скажи, каких именно."
)


# ──────────────────────────────────────────────────────────────────────────
# ФАКТ-ЛИСТ: компактная сводка рассчитанных показателей для промпта
# ──────────────────────────────────────────────────────────────────────────
def build_factsheet(r: Dict[str, Any]) -> str:
    e, bn, w = r["economics"], r["bottlenecks"], r["whatif_oak"]
    a, st, mo = bn["a_deviation"], bn["b_structural"], bn["c_moisture"]
    P = C.PRICES
    L = []
    ap = L.append

    ap("=== ПЕРИОД ===")
    ap(f"Обработано полных производственных циклов: {r['n_cycles']}")
    ap(f"Переработано круглого леса: {e['total_volume_m3']:.1f} м³ "
       f"(дуб {C.OAK_SHARE:.0%}, берёза {1-C.OAK_SHARE:.0%})")
    ap(f"Получено паркетной доски: {e['total_board_m2']:.1f} м² "
       f"(норматив {e['norm_board_m2']:.1f} м², отклонение "
       f"{(e['total_board_m2']/e['norm_board_m2']-1)*100:+.2f}%)")
    ap(f"Удельный выход: факт {r['forecast']['avg_m2_per_m3']:.2f} м²/м³, "
       f"норматив {r['forecast']['norm_m2_per_m3']:.2f} м²/м³")
    ap(f"Маржа за период: {e['margin_rub']:,.0f} руб "
       f"(сырьё {e['raw_cost_rub']:,.0f}, доска {e['board_revenue_rub']:,.0f}, "
       f"щепа {e['chips_revenue_rub']:,.0f})")

    ap("\n=== ВЫХОД ПО ОПЕРАЦИЯМ (норматив -> факт средний, отклонение) ===")
    for o in r["ops"]:
        ap(f"{o['title']}: {o['norm']*100:.1f}% -> {o['fact_avg']*100:.2f}% "
           f"({o['dev_rel']*100:+.2f}%)")

    ap("\n=== ПОТЕРИ ПО ЭТАПАМ ===")
    for l in sorted(r["losses"], key=lambda x: -x["rub"]):
        q = f"{l['loss_m2']:.1f} м²" if l.get("loss_m2") else f"{l['loss_m3']:.2f} м³"
        ap(f"{l['name']}: {q} ({l['share_of_input']*100:.2f}% от сырья), "
           f"тип «{l['kind']}», оценка {l['rub']:,.0f} руб")

    ap("\n=== УЗКОЕ МЕСТО 1: отклонение от норматива ===")
    ap(f"Операция: {a['title']} (участок {a['stage']})")
    ap(f"Норматив {a['norm']*100:.1f}%, факт {a['fact']*100:.2f}%, "
       f"отклонение {a['dev_rel']*100:+.2f}%")
    ap(f"Недополучено доски: {a['lost_board_m2']:.1f} м² = {a['lost_rub']:,.0f} руб")
    sig = a.get("significance") or {}
    if sig and sig.get("n"):
        ap(f"СТАТ. ЗНАЧИМОСТЬ: измерено по {sig['n']} партиям, "
           f"t={min(abs(sig['t']),99):.2f}{' (зашкаливает)' if abs(sig['t'])>99 else ''}, "
           f"p≈{max(sig['p_approx'],0.001):.3f}. "
           f"{'ЗНАЧИМО' if sig['significant_at_05'] else 'НЕ значимо'} при α=0.05."
           + (f" Для значимости нужно минимум {sig['need_n_for_sig80']} партий "
              f"(мощность 80%). Текущий вывод — точечная оценка, не подтверждённая "
              f"объёмом выборки."
              if (not sig['significant_at_05'] and sig.get('need_n_for_sig80'))
              else ""))
    ap("По партиям (та же операция): " + "; ".join(
        f"{p['batch']}: {p['value']*100:.2f}% ({p['dev_rel']*100:+.2f}%)"
        for o in r["ops"] if o["key"] == a.get("key", "")
        for p in o["per_batch"]) or "—")

    ap("\n=== УЗКОЕ МЕСТО 2: структурное ограничение комплекта ===")
    ap(f"Слой-лимитер: {st['limiting_layer']} (он определяет объём комплекта)")
    ap("Излишек слоёв, который невозможно склеить: " + ", ".join(
        f"{k} {v:.0f} м²" for k, v in st["surplus_m2"].items() if v > 1))
    ap(f"В объёме: {st['surplus_m3']:.2f} м³, оценка {st['frozen_rub']:,.0f} руб")
    ap("Причина: верхняя ламель производится только из дуба (30% закупки), "
       "нижняя — только из берёзы (70%). Пропорции слоёв в комплекте 1:1:1.")

    ap("\n=== УЗКОЕ МЕСТО 3: влажность и досушка ===")
    ap("ВНИМАНИЕ по единицам: влажность измеряется в % влажности древесины "
       "(шкала прибора 5..10). Это НЕ температура и НЕ градусы Цельсия. "
       "«Уставка» — целевая влажность на выходе сушильной камеры, тоже в % влажности.")
    for L2, d in mo["by_layer"].items():
        lo, hi = d["spec"]
        avg = d["avg"]
        where = ("выше верхней границы" if avg > hi else
                 "ниже нижней границы" if avg < lo else
                 f"внутри допуска, ближе к {'верхней' if (hi-avg) < (avg-lo) else 'нижней'} границе")
        ap(f"{L2}: допуск {lo:.0f}-{hi:.0f}% влажности, "
           f"среднее фактическое {avg:.2f}% ({where}), "
           f"вне допуска {d['rework_share']*100:.1f}% объёма (уходит на досушку), "
           f"замеров {d['n']}")
    ap(f"Текущая уставка сушильной камеры: {mo['current_setpoint']:.1f}% влажности")
    ap(f"Ключевая причина: верхняя ламель имеет самый узкий допуск "
       f"{C.MOISTURE_SPEC['верхняя'][0]:.0f}-{C.MOISTURE_SPEC['верхняя'][1]:.0f}%, "
       f"а уставка {mo['current_setpoint']:.1f}% стоит РОВНО НА ВЕРХНЕЙ ГРАНИЦЕ этого "
       f"допуска. Поэтому примерно половина распределения выходит за границу. "
       f"Снижение уставки означает более СУХУЮ древесину, а не более влажную.")
    ap(f"На досушку уходит {mo['rework_m2']:.0f} м², стоимость "
       f"{mo['rework_rub']:,.0f} руб (при {C.REWORK_COST_PER_M2:.0f} руб/м²)")
    ap(f"Расчётный оптимум уставки: {mo['optimal_setpoint']:.2f}% влажности "
       f"-> досушка {mo['optimal_rework_m2']:.0f} м², "
       f"экономия {mo['saving_rub']:,.0f} руб за период")

    ap("\n=== РАСЧЁТ «ЧТО-ЕСЛИ»: структура закупки ===")
    ap(f"Текущая доля дуба {w['current_share']*100:.0f}% -> "
       f"{w['current_board_m2']:.0f} м² доски со 100 м³")
    ap(f"Оптимальная доля дуба {w['optimal_share']*100:.1f}% -> "
       f"{w['optimal_board_m2']:.0f} м² ({w['gain_rel']*100:+.2f}%)")
    ap(f"На объёме периода это +{w['gain_m2_on_period']:.0f} м² "
       f"дополнительной доски.")
    ap(f"  прирост ВЫРУЧКИ: {w['gain_rub_on_period']:,.0f} руб")
    ap(f"  удорожание сырья (дуб дороже берёзы): "
       f"-{w['raw_cost_up_rub']:,.0f} руб")
    ap(f"  ПРИРОСТ МАРЖИ (честный эффект): {w['gain_margin_rub']:,.0f} руб")
    ap("  При ранжировании мероприятий используй ПРИРОСТ МАРЖИ, "
       "а не прирост выручки.")

    ap("\n=== ПРОГНОЗ ПОТРЕБНОСТИ В СЫРЬЕ (рассчитан детерминированно) ===")
    for ex in r["forecast"]["examples"]:
        ap(f"Цель {ex['target_m2']:.0f} м² доски: по нормативу "
           f"{ex['by_norm_m3']:.1f} м³, по факту {ex['by_fact_m3']:.1f} м³ "
           f"(перерасход {ex['extra_m3']:.1f} м³ = {ex['extra_rub']:,.0f} руб)")

    ap("\n=== ЦЕНЫ (условные) ===")
    ap(f"дуб {P['roundwood_дуб']:,.0f} руб/м³; берёза {P['roundwood_береза']:,.0f} руб/м³; "
       f"доска {P['board_m2']:,.0f} руб/м²; щепа {P['chips_m3']:,.0f} руб/м³")
    return "\n".join(L)

def build_factsheet_compact(r: Dict[str, Any]) -> str:
    """Компактный фактлист для демонстрации/быстрого запроса: только ПЕРИОД
    и три УЗКИХ МЕСТА (без детализации по операциям/потерям/что-если/прогнозу).
    ~900 знаков вместо ~4000 -> генерация на iGPU ~37 с вместо ~170 с."""
    e = r["economics"]
    bn = r["bottlenecks"]
    a, st, mo = bn["a_deviation"], bn["b_structural"], bn["c_moisture"]
    L = []
    ap = L.append
    ap("=== ПЕРИОД ===")
    ap(f"Обработано полных производственных циклов: {r['n_cycles']}")
    ap(f"Переработано круглого леса: {e['total_volume_m3']:.1f} м³ "
       f"(дуб {C.OAK_SHARE:.0%}, берёза {1-C.OAK_SHARE:.0%})")
    ap(f"Получено паркетной доски: {e['total_board_m2']:.1f} м² "
       f"(норматив {e['norm_board_m2']:.1f} м², "
       f"{(e['total_board_m2']/e['norm_board_m2']-1)*100:+.2f}%)")
    ap(f"Маржа за период: {e['margin_rub']:,.0f} руб")
    ap("\n=== УЗКОЕ МЕСТО 1: отклонение от норматива ===")
    ap(f"Операция: {a['title']} (участок {a['stage']})")
    ap(f"Норматив {a['norm']*100:.1f}%, факт {a['fact']*100:.2f}%, "
       f"отклонение {a['dev_rel']*100:+.2f}%")
    ap(f"Недополучено доски: {a['lost_board_m2']:.1f} м² = {a['lost_rub']:,.0f} руб")
    ap("\n=== УЗКОЕ МЕСТО 2: структурное ограничение комплекта ===")
    ap(f"Слой-лимитер: {st['limiting_layer']}")
    ap(f"В объёме: {st['surplus_m3']:.2f} м³, оценка {st['frozen_rub']:,.0f} руб")
    ap("\n=== УЗКОЕ МЕСТО 3: влажность и досушка ===")
    for L2, d in mo["by_layer"].items():
        lo, hi = d["spec"]
        ap(f"{L2}: допуск {lo:.0f}-{hi:.0f}% влажности, среднее {d['avg']:.2f}%, "
           f"вне допуска {d['rework_share']*100:.1f}%")
    ap(f"Уставка: {mo['current_setpoint']:.1f}% влажности; на досушку "
       f"{mo['rework_m2']:.0f} м², {mo['rework_rub']:,.0f} руб")
    return "\n".join(L)





# ЛЁГКАЯ модель (1.5B) плохо держит длинные многоступенчатые инструкции,
# поэтому задача СОКРАЩЕНА до 3 пунктов с жёстким запретом на выдумку чисел.
# Для 9b развёрнутый вариант (5 пунктов) можно вернуть — он в ПРЕЗЕНТАЦИЯ.md.
ANALYSIS_TASK = """Производство паркетной доски. Ниже — УЖЕ РАССЧИТАННЫЕ показатели.
Категорически НЕ придумывай и не пересчитывай числа, используй только данные.

Дай короткое заключение по пунктам:
1. ГДЕ ТЕРЯЕМ ДЕНЬГИ (2-3 предложения): главная причина потерь и почему.
2. ТРИ УЗКИХ МЕСТА по приоритету (эффект / сложность): отклонение от нормы,
   дисбаланс слоёв комплекта, влажность и досушка. Назови главное.
3. МЕРЫ (список): что трогать в первую очередь, эффект брать из данных.

Пиши по-русски, сжато, без похвал и без воды."""


def chat_with_fallback(messages: List[Dict[str, str]],
                       primary: str = None,
                       fallback: str = None,
                       timeout: int = None,
                       attempts: int = None) -> tuple[str, str]:
    """Единая точка отказоустойчивости ИИ.

    Сначала зовёт primary-модель (таймаут timeout). При любой ошибке
    (таймаут / нет связи / HTTP-ошибка) переключается на fallback-модель
    и делает до `attempts` попыток, каждая с тем же таймаутом.

    Возвращает (текст, использованная_модель). При полном провале
    бросает AIError (вызывающий код ловит и подставляет "(ИИ недоступен: ...)").
    """
    primary = primary or C.AI_MODEL_ANALYTICS
    fallback = fallback or C.AI_MODEL_ANALYTICS_FALLBACK
    timeout = timeout or C.AI_TIMEOUT
    attempts = attempts or getattr(C, "AI_FALLBACK_ATTEMPTS", 2)

    try:
        return chat(messages, model=primary, timeout=timeout), primary
    except Exception as e1:
        # Fallback отключён (fallback is None) — не ретраим ту же модель,
        # сразу поднимаем ошибку. Вызывающий код ловит AIError и подставляет
        # "(ИИ недоступен: ...)". Вернуть fallback = прописать модель в config.py.
        if not fallback:
            raise AIError(f"модель недоступна и fallback отключён: {e1}")
        last = e1
        for i in range(1, attempts + 1):
            try:
                return chat(messages, model=fallback, timeout=timeout), fallback
            except Exception as e2:
                last = e2
        raise AIError(f"обе модели недоступны: primary={e1}; fallback(x{attempts})={last}")


def analyze_production(r: Dict[str, Any], model: str = None, timeout: int = None) -> str:
    """Основной вызов: агрегаты -> заключение ИИ (с авто-fallback)."""
    # Компактный фактлист (Период + 3 узких места) -> ~37 с на iGPU вместо ~170 с.
    # Полный build_factsheet оставлен для ask()/explain_forecast().
    facts = anonymize(build_factsheet_compact(r))
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": ANALYSIS_TASK + "\n\n" + facts}]
    text, _ = chat_with_fallback(msgs, primary=model or C.AI_MODEL_ANALYTICS,
                                 fallback=C.AI_MODEL_ANALYTICS_FALLBACK,
                                 timeout=timeout)
    return text


def ask(question: str, r: Dict[str, Any] = None, model: str = None,
        history: List[Dict[str, str]] = None) -> str:
    """Свободный вопрос по данным производства (для фронтенда).

    ВАЖНО (проверено на FreeQwenApi): промежуточные system-сообщения прокси
    отбрасывает — модель отвечает «данных не предоставлено». Поэтому фактлист
    кладём в ТО ЖЕ user-сообщение, что и вопрос.
    """
    msgs = [{"role": "system", "content": SYSTEM}]
    for m in (history or [])[-8:]:
        msgs.append(m)
    if r:
        content = ("Актуальные рассчитанные показатели производства "
                   "(числа не пересчитывай, бери как есть):\n"
                   + anonymize(build_factsheet(r))
                   + "\n\nВОПРОС: " + question)
    else:
        content = question
    msgs.append({"role": "user", "content": content})
    text, _ = chat_with_fallback(msgs, primary=model or C.AI_MODEL_CHAT,
                                 fallback=C.AI_MODEL_CHAT,
                                 timeout=C.AI_TIMEOUT)
    return text


def explain_forecast(f: Dict[str, Any], r: Dict[str, Any] = None,
                     model: str = None) -> str:
    """Интерпретация уже посчитанного прогноза потребности в сырье."""
    txt = (f"Рассчитано детерминированно (не пересчитывай):\n"
           f"Цель: {f['target_m2']:.0f} м² паркетной доски\n"
           f"Режим: {'по фактическому выходу' if f['mode']=='fact' else 'по нормативам'}\n"
           f"Удельный выход: {f['m2_per_m3']:.3f} м²/м³\n"
           f"Требуется круглого леса: {f['roundwood_m3']:.1f} м³ "
           f"(дуб {f['oak_m3']:.1f} м³, берёза {f['birch_m3']:.1f} м³)\n"
           f"Стоимость сырья: {f['cost_rub']:,.0f} руб\n"
           f"Выручка при цене {C.PRICES['board_m2']:,.0f} руб/м²: "
           f"{f['revenue_rub']:,.0f} руб\n\n"
           f"Дай короткий комментарий (не более 8 строк): что учесть при "
           f"планировании такой закупки, какие риски по срокам и качеству сырья, "
           f"на что обратить внимание, чтобы фактический выход не просел.")
    msgs = [{"role": "system", "content": SYSTEM}]
    if r:
        txt = anonymize(build_factsheet(r)) + "\n\n" + txt
    msgs.append({"role": "user", "content": txt})
    text, _ = chat_with_fallback(msgs, primary=model or C.AI_MODEL_CHAT,
                                 fallback=C.AI_MODEL_CHAT,
                                 timeout=C.AI_TIMEOUT)
    return text


if __name__ == "__main__":
    print("PING:", json.dumps(ping(), ensure_ascii=False)[:300])
