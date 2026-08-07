# -*- coding: utf-8 -*-
"""
project_stat / svg_charts.py  (часть 1: примитивы)
Inline-SVG графики без внешних библиотек и CDN — отчёт открывается
двойным кликом на любом ПК в цеху, в том числе офлайн.

Правила оформления (согласованы с заказчиком):
  • подписи-выноски ВНЕ области построения, с линиями-указателями
  • легенда СПРАВА от графика, не снизу
  • график не раздувать, чтобы выноски не уезжали за экран
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple

PALETTE = ["#2e7d32", "#1565c0", "#ef6c00", "#6a1b9a", "#c62828",
           "#00838f", "#9e9d24", "#4e342e"]
GRID = "#dfe3e8"
AXIS = "#8a9099"
TXT = "#1f2328"
TXT_MUTED = "#5c6370"


def esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def fmt(v: float, nd: int = 1) -> str:
    s = f"{v:,.{nd}f}".replace(",", "\u00a0").replace(".", ",")
    return s


def fmt_rub(v: float) -> str:
    return fmt(v, 0) + "\u00a0₽"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    import math
    e = math.floor(math.log10(v))
    base = 10 ** e
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * base:
            return m * base
    return 10 * base


def _grid_y(x0, y0, w, h, vmax, steps=5, nd=0, unit=""):
    out = []
    for i in range(steps + 1):
        y = y0 + h - h * i / steps
        val = vmax * i / steps
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0+w}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x0-8}" y="{y+4:.1f}" text-anchor="end" '
                   f'font-size="11" fill="{TXT_MUTED}">{fmt(val, nd)}{unit}</text>')
    return "".join(out)


def _legend(x, y, items: List[Tuple[str, str]], width=210) -> str:
    """items = [(цвет, подпись)]. Легенда справа от графика."""
    out = [f'<rect x="{x}" y="{y}" width="{width}" height="{18*len(items)+16}" '
           f'rx="6" fill="#ffffff" stroke="{GRID}"/>']
    for i, (col, lab) in enumerate(items):
        yy = y + 16 + i * 18
        out.append(f'<rect x="{x+10}" y="{yy-9}" width="12" height="12" rx="2" fill="{col}"/>')
        out.append(f'<text x="{x+28}" y="{yy+1}" font-size="12" fill="{TXT}">{esc(lab)}</text>')
    return "".join(out)


def _svg(w, h, body, title="") -> str:
    t = (f'<text x="{w/2}" y="22" text-anchor="middle" font-size="14" '
         f'font-weight="600" fill="{TXT}">{esc(title)}</text>') if title else ""
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="auto" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'style="max-width:{w}px;font-family:Segoe UI,Arial,sans-serif">'
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>{t}{body}</svg>')


# ──────────────────────────────────────────────────────────────────────────
# 1. ВОДОПАД: как 100% сырья превращается в готовую доску
# ──────────────────────────────────────────────────────────────────────────
def waterfall(steps: List[Dict[str, Any]], title="") -> str:
    """steps = [{'label','value','kind'}] ; kind: start|loss|end (доли от входа, %)"""
    W, H = 900, 380
    x0, y0, w, h = 70, 50, 640, 250
    vmax = 100.0
    out = [_grid_y(x0, y0, w, h, vmax, 5, 0, "%")]

    n = len(steps)
    bw = w / n * 0.62
    gap = w / n
    run = 0.0
    labels = []
    for i, s in enumerate(steps):
        cx = x0 + gap * i + gap / 2
        v = s["value"]
        if s["kind"] == "start":
            top, bot, col = v, 0.0, "#37474f"
            run = v
        elif s["kind"] == "end":
            top, bot, col = v, 0.0, PALETTE[0]
        else:
            top, bot = run, run - v
            run = bot
            col = "#c62828" if s.get("critical") else "#ef6c00"
        yt = y0 + h - h * top / vmax
        yb = y0 + h - h * bot / vmax
        out.append(f'<rect x="{cx-bw/2:.1f}" y="{yt:.1f}" width="{bw:.1f}" '
                   f'height="{max(1.5,yb-yt):.1f}" rx="2" fill="{col}" opacity="0.92"/>')
        # соединитель
        if 0 < i < n:
            out.append(f'<line x1="{cx-gap+bw/2:.1f}" y1="{yt:.1f}" x2="{cx-bw/2:.1f}" '
                       f'y2="{yt:.1f}" stroke="{AXIS}" stroke-width="1" '
                       f'stroke-dasharray="3,3"/>')
        vlabel = f'{fmt(v,1)}%' if s["kind"] == "loss" else f'{fmt(v,1)}%'
        out.append(f'<text x="{cx:.1f}" y="{yt-6:.1f}" text-anchor="middle" '
                   f'font-size="11" font-weight="600" fill="{TXT}">{vlabel}</text>')
        labels.append((cx, s["label"]))

    out.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" '
               f'stroke="{AXIS}" stroke-width="1.5"/>')
    # подписи оси X — в две строки под графиком
    for i, (cx, lab) in enumerate(labels):
        yy = y0 + h + 16 + (i % 2) * 26
        out.append(f'<line x1="{cx:.1f}" y1="{y0+h}" x2="{cx:.1f}" y2="{yy-11:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        for j, part in enumerate(_wrap(lab, 16)):
            out.append(f'<text x="{cx:.1f}" y="{yy+j*11:.1f}" text-anchor="middle" '
                       f'font-size="10" fill="{TXT_MUTED}">{esc(part)}</text>')

    out.append(_legend(x0 + w + 20, y0, [
        ("#37474f", "Вход (100%)"),
        ("#ef6c00", "Потери этапа"),
        ("#c62828", "Структурные потери"),
        (PALETTE[0], "Готовая доска"),
    ], 160))
    return _svg(W, H, "".join(out), title)


def _wrap(s: str, n: int) -> List[str]:
    words, lines, cur = s.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 <= n:
            cur = (cur + " " + wd).strip()
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines[:3]


# ──────────────────────────────────────────────────────────────────────────
# 2. ГРУППИРОВАННЫЕ СТОЛБЦЫ: факт vs норматив по операциям
# ──────────────────────────────────────────────────────────────────────────
def grouped_bars(cats: List[str], series: List[Dict[str, Any]],
                 title="", unit="%", nd=1, vmin_auto=True, vmax_cap=None) -> str:
    """series = [{'name','color','values':[...]}]
    vmax_cap — жёсткий потолок оси (для процентов = 100), иначе _nice_max
    округляет 96.8 до 150 и половина полотна пустует."""
    W, H = 900, 360
    x0, y0, w, h = 70, 50, 620, 230
    allv = [v for s in series for v in s["values"]]
    vmax = _nice_max(max(allv) * 1.05) if allv else 1
    if vmax_cap is not None and allv and max(allv) <= vmax_cap:
        vmax = vmax_cap
    vlo = 0.0
    if vmin_auto and allv and min(allv) > 0.5 * vmax:
        vlo = _nice_max(min(allv) * 0.9) * 0.0
    out = [_grid_y(x0, y0, w, h, vmax, 5, nd if vmax < 10 else 0, unit)]

    n, m = len(cats), len(series)
    gap = w / n
    bw = gap * 0.7 / m
    for i, c in enumerate(cats):
        gx = x0 + gap * i + gap / 2
        for j, s in enumerate(series):
            v = s["values"][i]
            bh = h * (v - vlo) / (vmax - vlo) if vmax > vlo else 0
            bx = gx - (m * bw) / 2 + j * bw
            by = y0 + h - bh
            out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw-2:.1f}" '
                       f'height="{max(1,bh):.1f}" rx="2" fill="{s["color"]}" '
                       f'opacity="0.92"><title>{esc(c)} — {esc(s["name"])}: '
                       f'{fmt(v,nd)}{unit}</title></rect>')
        # подпись категории
        for k, part in enumerate(_wrap(c, 14)):
            out.append(f'<text x="{gx:.1f}" y="{y0+h+15+k*11:.1f}" '
                       f'text-anchor="middle" font-size="10" '
                       f'fill="{TXT_MUTED}">{esc(part)}</text>')

    out.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" '
               f'stroke="{AXIS}" stroke-width="1.5"/>')
    out.append(_legend(x0 + w + 20, y0,
                       [(s["color"], s["name"]) for s in series], 175))
    return _svg(W, H, "".join(out), title)


# ──────────────────────────────────────────────────────────────────────────
# 3. ГОРИЗОНТАЛЬНЫЕ СТОЛБЦЫ: потери в деньгах по этапам
# ──────────────────────────────────────────────────────────────────────────
def hbars(rows: List[Dict[str, Any]], title="", unit=" ₽") -> str:
    """rows = [{'label','value','color'}] — отсортированы по убыванию"""
    W = 900
    rowh = 34
    y0 = 46
    H = y0 + rowh * len(rows) + 30
    x0, w = 300, 460
    vmax = _nice_max(max((r["value"] for r in rows), default=1))
    out = []
    for i in range(6):
        x = x0 + w * i / 5
        out.append(f'<line x1="{x:.1f}" y1="{y0-6}" x2="{x:.1f}" '
                   f'y2="{y0+rowh*len(rows)}" stroke="{GRID}" stroke-width="1"/>')
    for i, r in enumerate(rows):
        y = y0 + rowh * i + 6
        bw = w * r["value"] / vmax if vmax else 0
        out.append(f'<text x="{x0-10}" y="{y+15}" text-anchor="end" font-size="11.5" '
                   f'fill="{TXT}">{esc(r["label"])}</text>')
        out.append(f'<rect x="{x0}" y="{y}" width="{max(2,bw):.1f}" height="{rowh-14}" '
                   f'rx="3" fill="{r.get("color", PALETTE[2])}" opacity="0.9"/>')
        # значение — ВНЕ полосы, справа
        out.append(f'<text x="{x0+bw+8:.1f}" y="{y+15}" font-size="11.5" '
                   f'font-weight="600" fill="{TXT}">{fmt(r["value"],0)}{unit}</text>')
    return _svg(W, H, "".join(out), title)


# ──────────────────────────────────────────────────────────────────────────
# 4. ДИСБАЛАНС СЛОЁВ: сколько произведено vs сколько вошло в комплект
# ──────────────────────────────────────────────────────────────────────────
def layer_balance(layers: List[str], produced: List[float],
                  used: List[float], title="") -> str:
    W, H = 900, 330
    x0, y0, w, h = 70, 50, 560, 200
    vmax = _nice_max(max(produced) * 1.12)
    out = [_grid_y(x0, y0, w, h, vmax, 5, 0, "")]
    gap = w / len(layers)
    bw = gap * 0.46
    for i, L in enumerate(layers):
        cx = x0 + gap * i + gap / 2
        hp = h * produced[i] / vmax
        hu = h * used[i] / vmax
        # произведено (светлый контур)
        out.append(f'<rect x="{cx-bw:.1f}" y="{y0+h-hp:.1f}" width="{bw*2:.1f}" '
                   f'height="{hp:.1f}" rx="3" fill="#cfd8dc" stroke="#90a4ae"/>')
        # вошло в комплект
        out.append(f'<rect x="{cx-bw:.1f}" y="{y0+h-hu:.1f}" width="{bw*2:.1f}" '
                   f'height="{hu:.1f}" rx="3" fill="{PALETTE[0]}" opacity="0.9"/>')
        surplus = produced[i] - used[i]
        if surplus > 1:
            my = y0 + h - hp + (hp - hu) / 2
            out.append(f'<text x="{cx:.1f}" y="{my:.1f}" text-anchor="middle" '
                       f'font-size="11" font-weight="600" fill="#c62828">'
                       f'+{fmt(surplus,0)} м²</text>')
        out.append(f'<text x="{cx:.1f}" y="{y0+h-hp-8:.1f}" text-anchor="middle" '
                   f'font-size="11" fill="{TXT}">{fmt(produced[i],0)}</text>')
        out.append(f'<text x="{cx:.1f}" y="{y0+h+16:.1f}" text-anchor="middle" '
                   f'font-size="12" fill="{TXT}">{esc(L)}</text>')
    out.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" '
               f'stroke="{AXIS}" stroke-width="1.5"/>')
    out.append(f'<text x="{x0-52}" y="{y0-8}" font-size="11" fill="{TXT_MUTED}">м²</text>')
    out.append(_legend(x0 + w + 24, y0, [
        ("#cfd8dc", "Произведено"),
        (PALETTE[0], "Вошло в комплект"),
        ("#c62828", "Излишек (не склеить)"),
    ], 190))
    return _svg(W, H, "".join(out), title)


# ──────────────────────────────────────────────────────────────────────────
# 5. КРИВАЯ ЧТО-ЕСЛИ: выход доски от доли дуба, с выноской оптимума
# ──────────────────────────────────────────────────────────────────────────
def curve_oak(curve: List[Dict[str, Any]], cur_x: float, cur_y: float,
              opt_x: float, opt_y: float, title="") -> str:
    W, H = 900, 340
    x0, y0, w, h = 70, 50, 600, 210
    xs = [p["x"] for p in curve]
    ys = [p["y"] for p in curve]
    xmin, xmax = min(xs), max(xs)
    vmax = _nice_max(max(ys) * 1.1)
    out = [_grid_y(x0, y0, w, h, vmax, 5, 0, "")]

    px = lambda x: x0 + w * (x - xmin) / (xmax - xmin)
    py = lambda y: y0 + h - h * y / vmax

    # ось X
    t = xmin
    while t <= xmax + 1e-9:
        out.append(f'<text x="{px(t):.1f}" y="{y0+h+16:.1f}" text-anchor="middle" '
                   f'font-size="10" fill="{TXT_MUTED}">{t*100:.0f}%</text>')
        out.append(f'<line x1="{px(t):.1f}" y1="{y0+h}" x2="{px(t):.1f}" '
                   f'y2="{y0+h+4}" stroke="{AXIS}"/>')
        t += 0.10

    d = " ".join(("M" if i == 0 else "L") + f"{px(p['x']):.1f},{py(p['y']):.1f}"
                 for i, p in enumerate(curve))
    out.append(f'<path d="{d}" fill="none" stroke="{PALETTE[1]}" stroke-width="2.4"/>')

    # текущая точка
    out.append(f'<circle cx="{px(cur_x):.1f}" cy="{py(cur_y):.1f}" r="5" '
               f'fill="#ffffff" stroke="{TXT}" stroke-width="2"/>')
    # оптимум
    out.append(f'<circle cx="{px(opt_x):.1f}" cy="{py(opt_y):.1f}" r="6" '
               f'fill="{PALETTE[0]}" stroke="#ffffff" stroke-width="2"/>')

    # выноски ВНЕ области построения
    _cx, _cy = px(cur_x), py(cur_y)
    out.append(f'<line x1="{_cx:.1f}" y1="{_cy:.1f}" x2="{_cx-40:.1f}" '
               f'y2="{y0+h+34:.1f}" stroke="{AXIS}" stroke-width="1" stroke-dasharray="3,2"/>')
    out.append(f'<text x="{_cx-44:.1f}" y="{y0+h+46:.1f}" text-anchor="middle" '
               f'font-size="11" fill="{TXT}">сейчас {cur_x*100:.0f}% → {fmt(cur_y,0)} м²</text>')
    _ox, _oy = px(opt_x), py(opt_y)
    out.append(f'<line x1="{_ox:.1f}" y1="{_oy:.1f}" x2="{_ox+30:.1f}" '
               f'y2="{y0-16:.1f}" stroke="{PALETTE[0]}" stroke-width="1" stroke-dasharray="3,2"/>')
    out.append(f'<text x="{_ox+34:.1f}" y="{y0-18:.1f}" font-size="11.5" '
               f'font-weight="600" fill="{PALETTE[0]}">оптимум {opt_x*100:.1f}% → '
               f'{fmt(opt_y,0)} м² (+{(opt_y/cur_y-1)*100:.1f}%)</text>')

    out.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" '
               f'stroke="{AXIS}" stroke-width="1.5"/>')
    out.append(f'<text x="{x0+w/2:.1f}" y="{H-6}" text-anchor="middle" font-size="11" '
               f'fill="{TXT_MUTED}">доля дуба в закупке</text>')
    out.append(f'<text x="{x0-52}" y="{y0-8}" font-size="11" fill="{TXT_MUTED}">м² доски</text>')
    return _svg(W, H, "".join(out), title)


# ──────────────────────────────────────────────────────────────────────────
# 6. ТРЕНД ПО ПАРТИЯМ: удельный выход м²/м³, факт vs норматив
# ──────────────────────────────────────────────────────────────────────────
def trend(batches: List[str], fact: List[float], norm: float, title="") -> str:
    W, H = 900, 300
    x0, y0, w, h = 70, 50, 600, 180
    vmax = _nice_max(max(fact + [norm]) * 1.15)
    out = [_grid_y(x0, y0, w, h, vmax, 5, 1, "")]
    n = len(batches)
    gap = w / max(1, n - 1) if n > 1 else w
    px = lambda i: x0 + (gap * i if n > 1 else w / 2)
    py = lambda v: y0 + h - h * v / vmax

    # норматив
    out.append(f'<line x1="{x0}" y1="{py(norm):.1f}" x2="{x0+w}" y2="{py(norm):.1f}" '
               f'stroke="{PALETTE[0]}" stroke-width="1.8" stroke-dasharray="6,4"/>')
    out.append(f'<text x="{x0+w+8}" y="{py(norm)+4:.1f}" font-size="11" '
               f'fill="{PALETTE[0]}">норматив {fmt(norm,1)}</text>')

    d = " ".join(("M" if i == 0 else "L") + f"{px(i):.1f},{py(v):.1f}"
                 for i, v in enumerate(fact))
    out.append(f'<path d="{d}" fill="none" stroke="{PALETTE[1]}" stroke-width="2.4"/>')
    for i, v in enumerate(fact):
        below = v < norm
        col = "#c62828" if below else PALETTE[1]
        out.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="5" fill="{col}" '
                   f'stroke="#fff" stroke-width="2"><title>{esc(batches[i])}: '
                   f'{fmt(v,2)} м²/м³</title></circle>')
        dy = 18 if below else -12
        out.append(f'<text x="{px(i):.1f}" y="{py(v)+dy:.1f}" text-anchor="middle" '
                   f'font-size="11" font-weight="600" fill="{col}">{fmt(v,1)}</text>')
        out.append(f'<text x="{px(i):.1f}" y="{y0+h+16:.1f}" text-anchor="middle" '
                   f'font-size="11" fill="{TXT_MUTED}">{esc(batches[i])}</text>')
    out.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" '
               f'stroke="{AXIS}" stroke-width="1.5"/>')
    out.append(f'<text x="{x0-52}" y="{y0-8}" font-size="11" fill="{TXT_MUTED}">м²/м³</text>')
    return _svg(W, H, "".join(out), title)


# ──────────────────────────────────────────────────────────────────────────
# 7. ВЛАЖНОСТЬ: доля ламели на досушку по слоям
# ──────────────────────────────────────────────────────────────────────────
def moisture_bars(layers: List[str], shares: List[float],
                  specs: List[Tuple[float, float]], title="") -> str:
    W, H = 900, 300
    x0, y0, w, h = 70, 50, 520, 180
    vmax = max(0.2, _nice_max(max(shares) * 1.25))
    out = [_grid_y(x0, y0, w, h, vmax * 100, 5, 0, "%")]
    gap = w / len(layers)
    bw = gap * 0.42
    for i, L in enumerate(layers):
        cx = x0 + gap * i + gap / 2
        bh = h * shares[i] / vmax
        col = "#c62828" if shares[i] > 0.25 else ("#ef6c00" if shares[i] > 0.1 else PALETTE[0])
        out.append(f'<rect x="{cx-bw:.1f}" y="{y0+h-bh:.1f}" width="{bw*2:.1f}" '
                   f'height="{max(1,bh):.1f}" rx="3" fill="{col}" opacity="0.9"/>')
        out.append(f'<text x="{cx:.1f}" y="{y0+h-bh-7:.1f}" text-anchor="middle" '
                   f'font-size="12" font-weight="600" fill="{col}">'
                   f'{shares[i]*100:.1f}%</text>')
        out.append(f'<text x="{cx:.1f}" y="{y0+h+16:.1f}" text-anchor="middle" '
                   f'font-size="12" fill="{TXT}">{esc(L)}</text>')
        out.append(f'<text x="{cx:.1f}" y="{y0+h+31:.1f}" text-anchor="middle" '
                   f'font-size="10" fill="{TXT_MUTED}">допуск '
                   f'допуск {specs[i][0]:.1f}–{specs[i][1]:.1f}</text>')
    out.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" '
               f'stroke="{AXIS}" stroke-width="1.5"/>')
    out.append(_legend(x0 + w + 30, y0, [
        (PALETTE[0], "до 10% — норма"),
        ("#ef6c00", "10–25% — внимание"),
        ("#c62828", "> 25% — проблема"),
    ], 185))
    return _svg(W, H, "".join(out), title)
