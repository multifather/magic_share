# -*- coding: utf-8 -*-
"""
project_stat / db.py
SQLite-хранилище. Идемпотентность обеспечивается SHA-256 содержимого файла:
повторная загрузка того же CSV не задваивает строки.
"""
from __future__ import annotations
import sqlite3
import hashlib
import os
from typing import List, Dict, Any, Optional

import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    sha256      TEXT NOT NULL UNIQUE,
    loaded_at   TEXT NOT NULL,
    rows        INTEGER NOT NULL,
    stage       INTEGER,
    batch_id    TEXT
);

CREATE TABLE IF NOT EXISTS movements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id      INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    report_id    TEXT NOT NULL,
    ts           TEXT NOT NULL,
    batch_id     TEXT NOT NULL,
    stage        INTEGER NOT NULL,
    operation    TEXT NOT NULL,
    direction    TEXT NOT NULL,        -- IN | OUT | WASTE
    material     TEXT NOT NULL,
    species      TEXT,
    layer        TEXT,
    thickness_mm REAL,
    qty          REAL NOT NULL,
    unit         TEXT NOT NULL,        -- m3 | m2
    operator     TEXT
);

CREATE INDEX IF NOT EXISTS ix_mov_batch  ON movements(batch_id);
CREATE INDEX IF NOT EXISTS ix_mov_stage  ON movements(stage);
CREATE INDEX IF NOT EXISTS ix_mov_dir    ON movements(direction);

CREATE TABLE IF NOT EXISTS moisture (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    batch_id  TEXT NOT NULL,
    layer     TEXT NOT NULL,
    value     REAL NOT NULL,
    in_spec   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,
    cycles      INTEGER NOT NULL,
    batches     TEXT NOT NULL,
    report_path TEXT,
    ai_used     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ai_dialog (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    role      TEXT NOT NULL,
    model     TEXT,
    content   TEXT NOT NULL
);
"""

MOVEMENT_COLS = [
    "report_id", "timestamp", "batch_id", "stage", "operation", "direction",
    "material", "species", "layer", "thickness_mm", "qty", "unit", "operator",
]


def connect(path: str = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or C.DB_PATH)
    con.row_factory = sqlite3.Row
    # WAL + busy_timeout: при одновременной работе ThreadingHTTPServer (UI)
    # и watcher'а (запись) снимает "database is locked" под нагрузкой.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(path: str = None) -> None:
    con = connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_loaded(con: sqlite3.Connection, sha: str) -> bool:
    return con.execute("SELECT 1 FROM files WHERE sha256=?", (sha,)).fetchone() is not None


def insert_file(con: sqlite3.Connection, filename: str, sha: str, loaded_at: str,
                rows: int, stage: Optional[int], batch_id: Optional[str]) -> int:
    cur = con.execute(
        "INSERT INTO files(filename,sha256,loaded_at,rows,stage,batch_id) VALUES(?,?,?,?,?,?)",
        (filename, sha, loaded_at, rows, stage, batch_id))
    return cur.lastrowid


def insert_movements(con: sqlite3.Connection, file_id: int, rows: List[Dict[str, Any]]) -> None:
    con.executemany(
        """INSERT INTO movements
           (file_id,report_id,ts,batch_id,stage,operation,direction,material,
            species,layer,thickness_mm,qty,unit,operator)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(file_id, r["report_id"], r["timestamp"], r["batch_id"], int(r["stage"]),
          r["operation"], r["direction"], r["material"], r.get("species") or None,
          r.get("layer") or None,
          float(r["thickness_mm"]) if r.get("thickness_mm") not in (None, "") else None,
          float(r["qty"]), r["unit"], r.get("operator") or None) for r in rows])


def insert_moisture(con: sqlite3.Connection, file_id: int, batch_id: str,
                    samples: List[Dict[str, Any]]) -> None:
    con.executemany(
        "INSERT INTO moisture(file_id,batch_id,layer,value,in_spec) VALUES(?,?,?,?,?)",
        [(file_id, batch_id, s["layer"], float(s["value"]), int(s["in_spec"]))
         for s in samples])


# ──────────────────────────────────────────────────────────────────────────
# ЗАПРОСЫ
# ──────────────────────────────────────────────────────────────────────────
def complete_batches(con: sqlite3.Connection) -> List[str]:
    """Партии, прошедшие ВСЕ 4 участка (есть OUT на каждом). Порядок — по первому касанию."""
    rows = con.execute("""
        SELECT batch_id, COUNT(DISTINCT stage) AS n, MIN(ts) AS t0
        FROM movements WHERE direction='OUT'
        GROUP BY batch_id HAVING n >= 4 ORDER BY t0
    """).fetchall()
    return [r["batch_id"] for r in rows]


def batch_ids(con: sqlite3.Connection) -> List[str]:
    return [r["batch_id"] for r in con.execute(
        "SELECT batch_id, MIN(ts) t0 FROM movements GROUP BY batch_id ORDER BY t0")]


def movements_of(con: sqlite3.Connection, batch_id: str) -> List[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM movements WHERE batch_id=? ORDER BY stage, id", (batch_id,)).fetchall()


def qty(con: sqlite3.Connection, batch_id: str, stage: int, direction: str,
        material: str = None, species: str = None, layer: str = None) -> float:
    q = "SELECT COALESCE(SUM(qty),0) v FROM movements WHERE batch_id=? AND stage=? AND direction=?"
    p: List[Any] = [batch_id, stage, direction]
    if material is not None:
        q += " AND material=?"; p.append(material)
    if species is not None:
        q += " AND species=?"; p.append(species)
    if layer is not None:
        q += " AND layer=?"; p.append(layer)
    return float(con.execute(q, p).fetchone()["v"])


def moisture_stats(con: sqlite3.Connection, batch_ids_: List[str]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    ph = ",".join("?" * len(batch_ids_))
    for L in C.LAYERS:
        r = con.execute(
            f"""SELECT COUNT(*) n, COALESCE(AVG(value),0) avg_v,
                       COALESCE(SUM(in_spec),0) ok
                FROM moisture WHERE layer=? AND batch_id IN ({ph})""",
            [L] + batch_ids_).fetchone()
        n = int(r["n"])
        out[L] = {"n": n, "avg": float(r["avg_v"]), "ok": int(r["ok"]),
                  "rework_share": (1.0 - r["ok"] / n) if n else 0.0}
    return out


def log_run(con: sqlite3.Connection, run_at: str, cycles: int, batches: str,
            report_path: str, ai_used: int) -> int:
    cur = con.execute(
        "INSERT INTO analysis_runs(run_at,cycles,batches,report_path,ai_used) VALUES(?,?,?,?,?)",
        (run_at, cycles, batches, report_path, ai_used))
    return cur.lastrowid


def log_ai(con: sqlite3.Connection, ts: str, role: str, model: str, content: str) -> None:
    con.execute("INSERT INTO ai_dialog(ts,role,model,content) VALUES(?,?,?,?)",
                (ts, role, model, content))


def stats(con: sqlite3.Connection) -> Dict[str, Any]:
    f = con.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
    m = con.execute("SELECT COUNT(*) n FROM movements").fetchone()["n"]
    return {"files": f, "movements": m,
            "batches": batch_ids(con), "complete": complete_batches(con)}


if __name__ == "__main__":
    init()
    con = connect()
    print(stats(con))
    con.close()
    print("DB:", C.DB_PATH, "exists:", os.path.exists(C.DB_PATH))
