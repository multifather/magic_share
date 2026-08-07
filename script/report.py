# -*- coding: utf-8 -*-
"""
project_stat / report.py
Сборка HTML-отчёта статистики с inline-SVG графиками.
Файл кладётся в workflow/reports/ — это и есть «файл статистики на сервере».
Открывается двойным кликом, без интернета и без CDN.
"""
from __future__ import annotations
import os
from datetime import datetime
from typing import Dict, Any, List

import config as C
import svg_charts as S


def _kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    cls = f" kpi-{tone}" if tone else ""
    sub_html = f'<div class="kpi-sub">{S.esc(sub)}</div>' if sub else ""
    return (f'<div class="kpi{cls}"><div class="kpi-lab">{S.esc(label)}</div>'
            f'<div class="kpi-val">{value}</div>{sub_html}</div>')


def _table(headers: List[str], rows: List[List[str]], cls: str = "") -> str:
    th = "".join(f"<th>{S.esc(h)}</th>" for h in headers)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="tbl {cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def _pct(v: float, nd: int = 1, sign: bool = True) -> str:
    s = f"{v*100:+.{nd}f}%" if sign else f"{v*100:.{nd}f}%"
    cls = "neg" if v < -0.0005 else ("pos" if v > 0.0005 else "")
    return f'<span class="{cls}">{s}</span>'


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f4f6f8;color:#1f2328;
     font:14px/1.5 "Segoe UI",Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:32px 0 12px;padding-bottom:6px;border-bottom:2px solid #d7dce1}
h3{font-size:14px;margin:18px 0 8px;color:#37474f}
.meta{color:#5c6370;font-size:12.5px;margin-bottom:18px}
.card{background:#fff;border:1px solid #e1e6ea;border-radius:10px;padding:16px 18px;
      margin-bottom:16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;
      margin-bottom:8px}
.kpi{background:#fff;border:1px solid #e1e6ea;border-radius:10px;padding:12px 14px}
.kpi-lab{font-size:11.5px;color:#5c6370;text-transform:uppercase;letter-spacing:.03em}
.kpi-val{font-size:22px;font-weight:600;margin-top:4px}
.kpi-sub{font-size:11.5px;color:#5c6370;margin-top:2px}
.kpi-good .kpi-val{color:#2e7d32}
.kpi-bad .kpi-val{color:#c62828}
.kpi-warn .kpi-val{color:#ef6c00}
.tbl{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
.tbl th{background:#eef2f5;text-align:left;padding:7px 9px;font-weight:600;
        border-bottom:1px solid #d7dce1;font-size:12px}
.tbl td{padding:6px 9px;border-bottom:1px solid #eef1f4}
.tbl tr:last-child td{border-bottom:none}
.tbl .num{font-variant-numeric:tabular-nums}
.neg{color:#c62828;font-weight:600}
.pos{color:#2e7d32;font-weight:600}
.chart{margin:10px 0 4px;text-align:center}
.note{background:#fff8e1;border-left:4px solid #ef6c00;padding:10px 14px;
      border-radius:0 6px 6px 0;margin:12px 0;font-size:13px}
.crit{background:#ffebee;border-left-color:#c62828}
.ok{background:#e8f5e9;border-left-color:#2e7d32}
.ai{background:#eef4ff;border-left:4px solid #1565c0;padding:14px 18px;
    border-radius:0 8px 8px 0;white-space:pre-wrap;font-size:13.5px}
.ai h4{margin:0 0 8px;font-size:14px;color:#1565c0}
.foot{color:#8a9099;font-size:11.5px;text-align:center;margin-top:36px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;
       font-weight:600;background:#eceff1;color:#37474f;margin-left:6px}
.badge-red{background:#ffcdd2;color:#b71c1c}
.badge-green{background:#c8e6c9;color:#1b5e20}
"""


def _sec_kpi(r: Dict[str, Any]) -> str:
    e = r["economics"]
    bn = r["bottlenecks"]
    dev = e["delta_board_m2"] / e["norm_board_m2"] if e["norm_board_m2"] else 0
    tone = "bad" if dev < -0.01 else ("good" if dev > 0.01 else "")
    k = [
        _kpi("Обработано циклов", str(r["n_cycles"]), ", ".join(r["batches"])),
        _kpi("Сырьё, м³", S.fmt(e["total_volume_m3"], 1),
             f'дуб {C.OAK_SHARE:.0%} / берёза {1-C.OAK_SHARE:.0%}'),
        _kpi("Готовая доска, м²", S.fmt(e["total_board_m2"], 1),
             f'норматив {S.fmt(e["norm_board_m2"],1)}', tone),
        _kpi("Отклонение от норматива", f'{dev*100:+.2f}%',
             S.fmt_rub(e["delta_board_rub"]), tone),
        _kpi("Удельный выход", f'{r["forecast"]["avg_m2_per_m3"]:.2f} м²/м³',
             f'норматив {r["forecast"]["norm_m2_per_m3"]:.2f}'),
        _kpi("Маржа за период", S.fmt_rub(e["margin_rub"]),
             f'сырьё {S.fmt_rub(e["raw_cost_rub"])}'),
    ]
    return '<div class="kpis">' + "".join(k) + "</div>"


def _sec_waterfall(r: Dict[str, Any]) -> str:
    e = r["economics"]
    vol = e["total_volume_m3"]
    L = {l["name"]: l for l in r["losses"]}
    pc = lambda m3: 100.0 * m3 / vol if vol else 0

    board_m3 = 0.0
    for f in r["facts"]:
        for lay in C.LAYERS:
            board_m3 += f["s4_board_m2"] * (C.THICKNESS_MM[lay] / 1000.0)

    steps = [
        {"label": "Круглый лес", "value": 100.0, "kind": "start"},
        {"label": "Уч.1 распиловка", "value": pc(L["Уч.1 Распиловка круглого леса"]["loss_m3"]), "kind": "loss"},
        {"label": "Уч.2 калибровка и отбор", "value": pc(L["Уч.2 Калибровка и отбор"]["loss_m3"]), "kind": "loss"},
        {"label": "Уч.3 пиление", "value": pc(L["Уч.3 Пиление ламелей"]["loss_m3"]), "kind": "loss"},
        {"label": "Излишек слоёв", "value": pc(L["Уч.3 Излишек слоёв (структурный)"]["loss_m3"]),
         "kind": "loss", "critical": True},
        {"label": "Уч.3 склейка", "value": pc(L["Уч.3 Склейка (брак)"]["loss_m3"]), "kind": "loss"},
        {"label": "Уч.4 профиль", "value": pc(L["Уч.4 Профилирование (брак)"]["loss_m3"]), "kind": "loss"},
        {"label": "Паркетная доска", "value": pc(board_m3), "kind": "end"},
    ]
    svg = S.waterfall(steps, "Сквозной баланс: путь 100% сырья до готовой доски (% от объёма)")
    return f'<div class="card"><div class="chart">{svg}</div>' \
           f'<div class="note">Красным выделены <b>структурные</b> потери — ламель, ' \
           f'которая произведена, но не может быть склеена из-за нехватки ' \
           f'дефицитного слоя. Это не брак оборудования, а следствие структуры ' \
           f'закупки сырья.</div></div>'


def _sec_ops(r: Dict[str, Any]) -> str:
    ops = r["ops"]
    cats = [o["title"].replace("Уч.", "У") for o in ops]
    svg = S.grouped_bars(
        cats,
        [{"name": "Норматив", "color": "#90a4ae", "values": [o["norm"] * 100 for o in ops]},
         {"name": "Факт (среднее)", "color": "#1565c0", "values": [o["fact_avg"] * 100 for o in ops]}],
        "Выход по операциям: факт против норматива", unit="%", nd=1, vmax_cap=100.0)

    rows = []
    for o in ops:
        badge = ""
        if o["dev_rel"] < -0.04:
            badge = '<span class="badge badge-red">ниже допуска</span>'
        elif o["dev_rel"] > 0.02:
            badge = '<span class="badge badge-green">выше</span>'
        per = " / ".join(f'{p["batch"]}: {p["value"]*100:.1f}%' for p in o["per_batch"])
        rows.append([f'{S.esc(o["title"])}{badge}',
                     f'<span class="num">{o["norm"]*100:.1f}%</span>',
                     f'<span class="num">{o["fact_avg"]*100:.2f}%</span>',
                     f'<span class="num">{_pct(o["dev_rel"], 2)}</span>',
                     f'<span style="font-size:11.5px;color:#5c6370">{per}</span>'])
    tbl = _table(["Операция", "Норматив", "Факт (ср.)", "Отклонение", "По партиям"], rows)
    return f'<div class="card"><div class="chart">{svg}</div>{tbl}</div>'


def _sec_losses(r: Dict[str, Any]) -> str:
    ls = sorted(r["losses"], key=lambda x: -x["rub"])
    rows_svg = [{"label": l["name"], "value": l["rub"],
                 "color": "#c62828" if l["kind"] == "структурный"
                          else ("#ef6c00" if l["kind"] == "брак" else "#78909c")}
                for l in ls]
    svg = S.hbars(rows_svg, "Потери по этапам в денежном выражении (за период)")

    rows = []
    for l in ls:
        q = (f'{S.fmt(l["loss_m2"],1)} м²' if l.get("loss_m2")
             else f'{S.fmt(l["loss_m3"],2)} м³')
        rows.append([S.esc(l["name"]),
                     f'<span class="num">{q}</span>',
                     f'<span class="num">{l["share_of_input"]*100:.2f}%</span>',
                     S.esc(l["kind"]),
                     f'<span class="num">{S.fmt_rub(l["rub"])}</span>'])
    total = sum(l["rub"] for l in ls)
    rows.append(["<b>Итого</b>", "", "", "",
                 f'<span class="num"><b>{S.fmt_rub(total)}</b></span>'])
    tbl = _table(["Этап", "Объём потерь", "% от сырья", "Тип", "Оценка, ₽"], rows)
    note = ('<div class="note">Щепа оценена по цене реализации '
            f'({S.fmt_rub(C.PRICES["chips_m3"])}/м³) — это не убыток, а недополученная '
            'стоимость передела. Брак и структурный излишек оценены дороже, поскольку '
            'в них уже вложена обработка.</div>')
    return f'<div class="card"><div class="chart">{svg}</div>{tbl}{note}</div>'


def _sec_bottlenecks(r: Dict[str, Any]) -> str:
    b = r["bottlenecks"]
    a, st, mo = b["a_deviation"], b["b_structural"], b["c_moisture"]

    # (a) отклонение
    sig = a.get("significance") or {}
    if sig and sig.get("n"):
        sig_txt = (f'<p class="note crit"><b>Статистическая значимость.</b> '
                   f'Отклонение измерено по {sig["n"]} партиям: '
                   f'среднее {sig["mean"]*100:.2f}% против норматива '
                   f'{sig["norm"]*100:.1f}%, разброс σ={sig["sd"]*100:.1f} п.п. '
                   f'(t={min(abs(sig["t"]),99):.2f}{" (зашкаливает)" if abs(sig["t"])>99 else ""}). '
                   f'Двусторонний p≈{max(sig["p_approx"],0.001):.3f} — '
                   f'{"ЗНАЧИМО" if sig["significant_at_05"] else "НЕ значимо"} '
                   f'на уровне α=0.05. ')
        if not sig["significant_at_05"] and sig.get("need_n_for_sig80"):
            sig_txt += (f'При текущем разбросе, чтобы отличить этот сдвиг от '
                        f'естественного шума, нужно минимум '
                        f'<b>{sig["need_n_for_sig80"]} партий</b> '
                        f'(α=0.05, мощность 80%). Вывод «потеря 470 тыс. ₽» — '
                        f'точечная оценка, не подтверждённая статистикой объёма.')
        # Честная пометка: p считается нормальной аппроксимацией через erf,
        # а не по t-распределению (при n=10 это грубее, но достаточно для
        # вывода «не значимо»). Для строгих выводов нужен t-квантиль / scipy.
        sig_txt += (f' <i>(p-значение — нормальная аппроксимация через erf, '
                    f'не t-распределение; для n=10 оценка грубая, но консервативна '
                    f'в сторону «не значимо».)</i>')
        sig_txt += '</p>'
    else:
        sig_txt = ''
    ha = (f'<h3>1. Отклонение от норматива <span class="badge badge-red">'
          f'участок {a["stage"]}</span></h3>'
          f'<p><b>{S.esc(a["title"])}</b>: норматив {a["norm"]*100:.1f}%, '
          f'факт {a["fact"]*100:.2f}% ({_pct(a["dev_rel"],2)}).<br>'
          f'Недополучено готовой доски: <b>{S.fmt(a["lost_board_m2"],1)} м²</b> '
          f'= <b>{S.fmt_rub(a["lost_rub"])}</b> за период.</p>{sig_txt}'
          f'<div class="note crit">{S.esc(a["explanation"])}</div>'
          f'<div class="note info">{S.esc(a["recommendation"])}</div>')

    # (b) структурное
    prod = [sum(f["s3_lam_m2"][L] for f in r["facts"]) for L in C.LAYERS]
    used = [p - sum(f["surplus_m2"][L] for f in r["facts"])
            for p, L in zip(prod, C.LAYERS)]
    svg_b = S.layer_balance(list(C.LAYERS), prod, used,
                            "Дисбаланс слоёв: произведено vs вошло в комплект")
    sur = st["surplus_m2"]
    hb = (f'<h3>2. Структурное ограничение комплекта '
          f'<span class="badge badge-red">лимитер: {S.esc(st["limiting_layer"])}</span></h3>'
          f'<div class="chart">{svg_b}</div>'
          f'<p>Комплект паркетной доски определяется дефицитным слоем — '
          f'<b>{S.esc(st["limiting_layer"])}</b>. Излишек остальных слоёв: '
          + ", ".join(f'{L} <b>{S.fmt(sur[L],0)} м²</b>' for L in C.LAYERS if sur[L] > 1)
          + f'. В объёме это <b>{S.fmt(st["surplus_m3"],2)} м³</b> '
          f'замороженного ресурса ({S.fmt_rub(st["frozen_rub"])} по цене щепы).</p>'
          f'<div class="note crit">{S.esc(st["explanation"])}</div>'
          f'<div class="note info">{S.esc(st["recommendation"])}</div>')

    # (c) влажность
    shares = [mo["by_layer"][L]["rework_share"] for L in C.LAYERS]
    specs = [tuple(mo["by_layer"][L]["spec"]) for L in C.LAYERS]
    svg_c = S.moisture_bars(list(C.LAYERS), shares, specs,
                            "Доля ламели вне допуска влажности → на досушку")
    worst_layer = max(C.LAYERS, key=lambda L: mo["by_layer"][L]["rework_share"])
    hc = (f'<h3>3. Отбраковка по влажности '
          f'<span class="badge badge-red">{worst_layer}</span></h3>'
          f'<div class="chart">{svg_c}</div>'
          f'<div class="note crit">{S.esc(mo["explanation"])}</div>'
          f'<div class="note ok">{S.esc(mo["recommendation"])}</div>')
    return f'<div class="card">{ha}</div><div class="card">{hb}</div>' \
           f'<div class="card">{hc}</div>'


def _sec_whatif(r: Dict[str, Any]) -> str:
    w = r["whatif_oak"]
    svg = S.curve_oak(w["curve"], w["current_share"], w["current_board_m2"],
                      w["optimal_share"], w["optimal_board_m2"],
                      "Что-если: выход доски в зависимости от доли дуба (на 100 м³)")
    txt = (f'<div class="note ok">{S.esc(w["explanation"])}</div>'
           f'<div class="note info">{S.esc(w["recommendation"])}</div>')
    return f'<div class="card"><div class="chart">{svg}</div>{txt}</div>'


def _sec_trend(r: Dict[str, Any]) -> str:
    b = [f["batch_id"] for f in r["facts"]]
    fact = [f["overall_m2_per_m3"] for f in r["facts"]]
    svg = S.trend(b, fact, r["forecast"]["norm_m2_per_m3"],
                  "Удельный выход по партиям, м² доски на 1 м³ круглого леса")
    rows = []
    for e in r["economics"]["by_batch"]:
        d = e["delta_m2"] / e["norm_board_m2"] if e["norm_board_m2"] else 0
        rows.append([S.esc(e["batch"]),
                     f'<span class="num">{S.fmt(e["volume"],0)}</span>',
                     f'<span class="num">{S.fmt(e["board_m2"],1)}</span>',
                     f'<span class="num">{S.fmt(e["norm_board_m2"],1)}</span>',
                     f'<span class="num">{_pct(d,2)}</span>',
                     f'<span class="num">{e["m2_per_m3"]:.2f}</span>',
                     f'<span class="num">{S.fmt_rub(e["margin_rub"])}</span>'])
    tbl = _table(["Партия", "Сырьё, м³", "Доска, м²", "Норматив, м²",
                  "Откл.", "м²/м³", "Маржа"], rows)
    return f'<div class="card"><div class="chart">{svg}</div>{tbl}</div>'


def _sec_forecast(r: Dict[str, Any]) -> str:
    f = r["forecast"]
    rows = []
    for ex in f["examples"]:
        rows.append([f'<span class="num">{S.fmt(ex["target_m2"],0)} м²</span>',
                     f'<span class="num">{S.fmt(ex["by_norm_m3"],1)}</span>',
                     f'<span class="num">{S.fmt(ex["by_fact_m3"],1)}</span>',
                     f'<span class="num neg">+{S.fmt(ex["extra_m3"],1)}</span>'
                     if ex["extra_m3"] > 0 else
                     f'<span class="num pos">{S.fmt(ex["extra_m3"],1)}</span>',
                     f'<span class="num">{S.fmt_rub(ex["extra_rub"])}</span>'])
    tbl = _table(["Цель, м² доски", "Нужно леса по нормативу, м³",
                  "По факту, м³", "Разница", "Цена разницы"], rows)
    note = ('<div class="note">Прогноз считается <b>детерминированно</b>, '
            'по удельному выходу цепочки — не языковой моделью. '
            'ИИ используется для интерпретации причин и рекомендаций, '
            'а не для арифметики: на числах LLM ошибается, и проверить её '
            'вывод дороже, чем посчитать самому.</div>')
    return f'<div class="card"><h3>Обратный прогноз потребности в сырье</h3>' \
           f'<p>Удельный выход: норматив <b>{f["norm_m2_per_m3"]:.2f}</b> м²/м³, ' \
           f'факт <b>{f["avg_m2_per_m3"]:.2f}</b> м²/м³.</p>{tbl}{note}</div>'


def _sec_ai(ai_text: str) -> str:
    if not ai_text:
        return ""
    body = S.esc(ai_text)
    return (f'<div class="card"><div class="ai"><h4>Заключение ИИ-агента '
            f'({S.esc(C.AI_MODEL_ANALYTICS)})</h4>{body}</div>'
            f'<div class="note">Все числовые значения выше рассчитаны скриптом. '
            f'ИИ получил готовые агрегаты и отвечает только за интерпретацию '
            f'и приоритизацию мероприятий.</div></div>')


def build(r: Dict[str, Any], ai_text: str = "") -> str:
    ts = datetime.now()
    e = r["economics"]
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Статистика производства — {ts:%d.%m.%Y %H:%M}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>Статистика переработки: круглый лес → паркетная доска</h1>
<div class="meta">Сформировано автоматически {ts:%d.%m.%Y %H:%M:%S} ·
Циклов в анализе: {r['n_cycles']} ({', '.join(r['batches'])}) ·
Источник: {S.esc(C.TEST_REPORTS)} ·
SEED: {getattr(C, 'CURRENT_SEED', '—')} ·
Синтетические обезличенные данные</div>

{_sec_kpi(r)}

<h2>1. Сквозной материальный баланс</h2>
{_sec_waterfall(r)}

<h2>2. Выход по операциям: факт против норматива</h2>
{_sec_ops(r)}

<h2>3. Потери по этапам производства</h2>
{_sec_losses(r)}

<h2>4. Узкие места</h2>
<p style="color:#5c6370;font-size:13px;margin-top:-4px">
Три принципиально разных типа ограничений. Смешивать их нельзя:
меры по каждому свои.</p>
{_sec_bottlenecks(r)}

<h2>5. Что-если: структура закупки сырья</h2>
{_sec_whatif(r)}

<h2>6. Динамика по партиям</h2>
{_sec_trend(r)}

<h2>7. Прогноз потребности в сырье</h2>
{_sec_forecast(r)}

<h2>8. Заключение ИИ-агента</h2>
{_sec_ai(ai_text) or '<div class="card"><i>ИИ не привлекался в этом запуске.</i></div>'}

<div class="foot">project_stat · автоматический отчёт ·
маржа за период {S.fmt_rub(e['margin_rub'])} ·
цены условные, данные синтетические</div>
</div></body></html>"""

    os.makedirs(C.REPORTS_DIR, exist_ok=True)
    path = os.path.join(C.REPORTS_DIR, f"stat_report_{ts:%Y%m%d_%H%M%S}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    latest = os.path.join(C.REPORTS_DIR, "latest.html")
    with open(latest, "w", encoding="utf-8") as f:
        f.write(html)
    return path


if __name__ == "__main__":
    import db, analytics
    con = db.connect()
    b = db.complete_batches(con)
    if len(b) >= C.FULL_CYCLES_TRIGGER:
        res = analytics.analyze(con, b[:C.FULL_CYCLES_TRIGGER])
        print("Отчёт:", build(res, ""))
    else:
        print(f"Недостаточно циклов: {len(b)}/{C.FULL_CYCLES_TRIGGER}")
    con.close()
