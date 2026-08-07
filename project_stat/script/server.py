# -*- coding: utf-8 -*-
"""
project_stat / server.py
HTTP-сервер фронтенд-оболочки. Только stdlib.

Эндпоинты:
  GET  /                 -> ui.html
  GET  /api/status       -> состояние БД, циклы, доступность ИИ
  GET  /api/analytics    -> полные агрегаты (JSON)
  GET  /api/report       -> последний HTML-отчёт
  POST /api/forecast     -> {target_m2, mode, oak_share} детерминированный прогноз
  POST /api/whatif       -> {oak_share, setpoint, volume} пересчёт цепочки
  POST /api/ask          -> {question, history} свободный вопрос к ИИ
  POST /api/explain      -> {target_m2, mode} прогноз + комментарий ИИ
  POST /api/reanalyze    -> принудительный пересчёт + новый отчёт
"""
from __future__ import annotations
import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import config as C
import db
import analytics
import model as M

_lock = threading.Lock()
# Состояние этапа ИИ для видимости шага «аналитика -> ИИ -> вывод» на фронте.
# phase: 'idle' | 'analytics' | 'ai' | 'ready' | 'error'
_ai_state = {"phase": "idle", "ts": 0.0, "note": ""}


def _analytics_now():
    con = db.connect()
    try:
        b = db.complete_batches(con)
        if len(b) < 1:
            return None, b
        return analytics.analyze(con, b), b
    finally:
        con.close()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    # ── утилиты ответа ────────────────────────────────────────────────
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False,
                                    default=str).encode("utf-8"))

    def _err(self, msg, code=500):
        self._json({"ok": False, "error": str(msg)}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        # Некоторые клиенты (curl из cp1251-консоли Windows) шлют не-UTF-8.
        for enc in ("utf-8", "cp1251"):
            try:
                return json.loads(raw.decode(enc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return json.loads(raw.decode("utf-8", "replace"))

    def do_OPTIONS(self):
        self._send(204, b"")

    # ── GET ───────────────────────────────────────────────────────────
    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p in ("/", "/index.html", "/ui.html"):
                if not os.path.exists(C.UI_PATH):
                    return self._send(404, b"ui.html not found", "text/plain; charset=utf-8")
                with open(C.UI_PATH, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")

            if p == "/api/status":
                con = db.connect()
                try:
                    s = db.stats(con)
                    runs = con.execute(
                        "SELECT run_at,cycles,report_path,ai_used FROM analysis_runs "
                        "ORDER BY id DESC LIMIT 1").fetchone()
                finally:
                    con.close()
                import ai_client
                return self._json({
                    "ok": True,
                    "files": s["files"], "movements": s["movements"],
                    "batches": s["batches"], "complete": s["complete"],
                    "trigger": C.FULL_CYCLES_TRIGGER,
                    "ready": len(s["complete"]) >= C.FULL_CYCLES_TRIGGER,
                    "last_run": dict(runs) if runs else None,
                    "ai": ai_client.ping(),
                    "ai_mode": C.AI_MODE, "anonymize": C.ANONYMIZE,
                    "watch_dir": C.TEST_REPORTS,
                })

            if p == "/api/analytics":
                r, b = _analytics_now()
                if r is None:
                    return self._json({"ok": False, "reason": "not_enough_cycles",
                                       "complete": b, "need": C.FULL_CYCLES_TRIGGER})
                return self._json({"ok": True, "data": r})

            if p == "/api/report":
                latest = os.path.join(C.REPORTS_DIR, "latest.html")
                if not os.path.exists(latest):
                    return self._send(404, b"report not generated yet",
                                      "text/plain; charset=utf-8")
                with open(latest, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")

            if p == "/api/ai_status":
                return self._json({"ok": True, **_ai_state})

            return self._send(404, b"not found", "text/plain; charset=utf-8")
        except Exception as e:
            traceback.print_exc()
            self._err(e)

    # ── POST ──────────────────────────────────────────────────────────
    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = self._body()

            if p == "/api/forecast":
                r, _ = _analytics_now()
                avg = r["forecast"]["avg_m2_per_m3"] if r else None
                f = analytics.forecast(float(body.get("target_m2", 1000)),
                                       body.get("mode", "fact"), avg,
                                       body.get("oak_share"))
                return self._json({"ok": True, "data": f})

            if p == "/api/whatif":
                oak = float(body.get("oak_share", C.OAK_SHARE))
                vol = float(body.get("volume", 100.0))
                sp = float(body.get("setpoint", C.DRYER_SETPOINT))
                res = M.compute(vol, oak)
                econ = M.batch_economics(res)
                base = M.compute(vol, C.OAK_SHARE)
                rework = {L: M.rework_share(L, mu=sp) for L in C.LAYERS}
                rework_m2 = sum(rework[L] * res["s3_lam_m2"][L] for L in C.LAYERS)
                return self._json({"ok": True, "data": {
                    "oak_share": oak, "volume": vol, "setpoint": sp,
                    "board_m2": res["s4_board_m2"],
                    "base_board_m2": base["s4_board_m2"],
                    "gain_m2": res["s4_board_m2"] - base["s4_board_m2"],
                    "gain_rub": (res["s4_board_m2"] - base["s4_board_m2"])
                                * C.PRICES["board_m2"],
                    "limiting_layer": res["limiting_layer"],
                    "complect_m2": res["complect_m2"],
                    "surplus_m2": res["surplus_m2"],
                    "lam_m2": res["s3_lam_m2"],
                    "margin_rub": econ["margin_rub"],
                    "rework": rework, "rework_m2": rework_m2,
                    "rework_rub": rework_m2 * C.REWORK_COST_PER_M2,
                }})

            if p == "/api/ask":
                import ai_client
                r, _ = _analytics_now()
                q = (body.get("question") or "").strip()
                if not q:
                    return self._err("пустой вопрос", 400)
                _ai_state.update(phase="ai", ts=__import__("time").time(),
                                 note="модель отвечает на вопрос")
                with _lock:
                    # ai_client.ask возвращает ТОЛЬКО текст (см. сигнатуру в ai_client.py)
                    ans = ai_client.ask(q, r, history=body.get("history") or [])
                _ai_state.update(phase="ready", ts=__import__("time").time(),
                                 note="ответ ИИ получен")
                con = db.connect()
                try:
                    from datetime import datetime
                    now = datetime.now().isoformat(timespec="seconds")
                    db.log_ai(con, now, "user", C.AI_MODEL_CHAT, q)
                    db.log_ai(con, now, "assistant", C.AI_MODEL_CHAT, ans)
                    con.commit()
                finally:
                    con.close()
                return self._json({"ok": True, "answer": ans, "model": C.AI_MODEL_CHAT})

            if p == "/api/explain":
                import ai_client
                r, _ = _analytics_now()
                avg = r["forecast"]["avg_m2_per_m3"] if r else None
                f = analytics.forecast(float(body.get("target_m2", 1000)),
                                       body.get("mode", "fact"), avg,
                                       body.get("oak_share"))
                with _lock:
                    # explain_forecast возвращает ТОЛЬКО текст (см. ai_client.py)
                    txt = ai_client.explain_forecast(f, r)
                return self._json({"ok": True, "data": f, "comment": txt, "model": C.AI_MODEL_CHAT})

            if p == "/api/reanalyze":
                import report as report_mod
                import ai_client
                _ai_state.update(phase="analytics",
                                 ts=__import__("time").time(),
                                 note="аналитика рассчитывает агрегаты")
                r, b = _analytics_now()
                if r is None:
                    _ai_state.update(phase="error", ts=__import__("time").time(),
                                     note="недостаточно циклов")
                    return self._err(f"недостаточно циклов: {len(b)}/{C.FULL_CYCLES_TRIGGER}", 400)
                ai_text = ""
                if body.get("with_ai", True):
                    try:
                        _ai_state.update(phase="analytics",
                                         ts=__import__("time").time(),
                                         note="агрегаты готовы, запрос к ИИ")
                        with _lock:
                            _ai_state.update(phase="ai",
                                             ts=__import__("time").time(),
                                             note="модель генерирует заключение")
                            # analyze_production возвращает ТОЛЬКО текст (см. сигнатуру
                            # в ai_client.py); модель-источник не нужна серверу.
                            ai_text = ai_client.analyze_production(r, timeout=C.AI_TIMEOUT)
                        _ai_state.update(phase="ready",
                                         ts=__import__("time").time(),
                                         note="ответ ИИ получен")
                    except Exception as e:
                        _ai_state.update(phase="error",
                                         ts=__import__("time").time(),
                                         note=str(e)[:120])
                        ai_text = f"(ИИ недоступен: {e})"
                path = report_mod.build(r, ai_text)
                con = db.connect()
                try:
                    from datetime import datetime
                    db.log_run(con, datetime.now().isoformat(timespec="seconds"),
                               len(b), ",".join(b), path,
                               1 if ai_text and not ai_text.startswith("(ИИ") else 0)
                    con.commit()
                finally:
                    con.close()
                return self._json({"ok": True, "report": path, "ai": ai_text})

            return self._err("unknown endpoint", 404)
        except Exception as e:
            traceback.print_exc()
            self._err(e)


def main():
    db.init()
    srv = ThreadingHTTPServer((C.SERVER_HOST, C.SERVER_PORT), H)
    print(f"Фронтенд: http://{C.SERVER_HOST}:{C.SERVER_PORT}/")
    print(f"ИИ: {C.AI_MODE} {C.AI_BASE_URL} "
          f"({C.AI_MODEL_ANALYTICS} / {C.AI_MODEL_CHAT}), "
          f"обезличивание={'вкл' if C.ANONYMIZE else 'выкл'}")
    print("Ctrl+C для остановки")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлен")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
