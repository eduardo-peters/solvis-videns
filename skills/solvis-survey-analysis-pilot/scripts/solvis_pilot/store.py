"""Cache local em SQLite, no modelo normalizado (por id), uma pasta por credencial.

Tabelas de resultados:
- evaluations: uma linha por avaliação (eval_ref = unique_id do sistema).
- answers: uma linha por pergunta respondida; em múltipla resposta, uma por alternativa.
- answer_tags: tags aplicadas a (avaliação, pergunta).
- days: livro-razão de cobertura por (pesquisa, dia local): quando foi baixado e se completo.
- issues: respostas que não puderam ser mapeadas para ids, por dia.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import periods

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS catalog (kind TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS days (
  survey_id INTEGER NOT NULL, day TEXT NOT NULL, status TEXT NOT NULL,
  evaluations INTEGER NOT NULL, fetched_at TEXT NOT NULL, failed_windows TEXT,
  PRIMARY KEY (survey_id, day));
CREATE TABLE IF NOT EXISTS evaluations (
  survey_id INTEGER NOT NULL, eval_ref TEXT NOT NULL, day TEXT NOT NULL, started_at TEXT NOT NULL,
  unit_id INTEGER, unit_name TEXT, channel TEXT NOT NULL, completed INTEGER NOT NULL,
  reliable INTEGER, dq INTEGER NOT NULL, duration INTEGER,
  PRIMARY KEY (survey_id, eval_ref));
CREATE INDEX IF NOT EXISTS ev_day ON evaluations (survey_id, day);
CREATE TABLE IF NOT EXISTS answers (
  survey_id INTEGER NOT NULL, eval_ref TEXT NOT NULL, day TEXT NOT NULL,
  question_id INTEGER, qgroup TEXT, kind TEXT NOT NULL,
  choice_id INTEGER, score INTEGER, answered INTEGER NOT NULL, text TEXT);
CREATE INDEX IF NOT EXISTS ans_q ON answers (survey_id, question_id, day);
CREATE INDEX IF NOT EXISTS ans_ev ON answers (survey_id, eval_ref);
CREATE TABLE IF NOT EXISTS answer_tags (
  survey_id INTEGER NOT NULL, eval_ref TEXT NOT NULL, day TEXT NOT NULL,
  question_id INTEGER, tag_id INTEGER NOT NULL, tag_name TEXT);
CREATE INDEX IF NOT EXISTS tag_day ON answer_tags (survey_id, day);
CREATE TABLE IF NOT EXISTS issues (
  survey_id INTEGER NOT NULL, day TEXT NOT NULL, code TEXT NOT NULL, detail TEXT NOT NULL,
  count INTEGER NOT NULL, PRIMARY KEY (survey_id, day, code, detail));
"""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, cache_dir: Path) -> None:
        self.path = cache_dir / "cache.sqlite3"
        fresh = not self.path.exists()
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        if fresh:
            try:
                os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
        current = self.get_meta("schema_version")
        if current is None:
            self.set_meta("schema_version", SCHEMA_VERSION)
        self._register_functions()

    def _register_functions(self) -> None:
        self.db.create_function("bucket", 2, lambda kind, day: periods.bucket_key(kind, day), deterministic=True)
        self.db.create_function("dow", 1, periods.dow_key, deterministic=True)
        self.db.create_function(
            "hour_block", 2, lambda ts, size: periods.hour_block_key(ts, int(size)), deterministic=True
        )

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # --------------------------------------------------------------- catalog
    def get_catalog(self, kind: str) -> Tuple[Optional[Any], Optional[str]]:
        row = self.db.execute("SELECT payload, fetched_at FROM catalog WHERE kind = ?", (kind,)).fetchone()
        if not row:
            return None, None
        return json.loads(row["payload"]), row["fetched_at"]

    def put_catalog(self, kind: str, payload: Any) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO catalog (kind, payload, fetched_at) VALUES (?, ?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False), now_utc()),
            )

    # ------------------------------------------------------------------ days
    def day_rows(self, survey_id: int, start: dt.date, end: dt.date) -> Dict[str, sqlite3.Row]:
        rows = self.db.execute(
            "SELECT * FROM days WHERE survey_id = ? AND day BETWEEN ? AND ?",
            (survey_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return {r["day"]: r for r in rows}

    def replace_days(
        self,
        survey_id: int,
        days: Sequence[str],
        evaluations: Iterable[Tuple],
        answers: Iterable[Tuple],
        tags: Iterable[Tuple],
        issues: Dict[Tuple[str, str, str], int],
        failed: Dict[str, List[List[str]]],
    ) -> None:
        """Troca atomicamente o conteúdo de um conjunto de dias de uma pesquisa."""
        fetched_at = now_utc()
        with self.db:
            for table in ("evaluations", "answers", "answer_tags", "issues"):
                self.db.executemany(
                    f"DELETE FROM {table} WHERE survey_id = ? AND day = ?", [(survey_id, d) for d in days]
                )
            self.db.executemany(
                "INSERT OR REPLACE INTO evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?)", list(evaluations)
            )
            self.db.executemany("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?)", list(answers))
            self.db.executemany("INSERT INTO answer_tags VALUES (?,?,?,?,?,?)", list(tags))
            self.db.executemany(
                "INSERT OR REPLACE INTO issues VALUES (?,?,?,?,?)",
                [(survey_id, d, code, detail, n) for (d, code, detail), n in issues.items()],
            )
            counts = dict(
                self.db.execute(
                    "SELECT day, COUNT(*) FROM evaluations WHERE survey_id = ? AND day IN (%s) GROUP BY day"
                    % ",".join("?" * len(days)),
                    (survey_id, *days),
                ).fetchall()
            )
            self.db.executemany(
                "INSERT OR REPLACE INTO days VALUES (?,?,?,?,?,?)",
                [
                    (
                        survey_id,
                        d,
                        "partial" if failed.get(d) else "ok",
                        counts.get(d, 0),
                        fetched_at,
                        json.dumps(failed[d]) if failed.get(d) else None,
                    )
                    for d in days
                ],
            )

    def known_refs(self, survey_id: int, refs: Sequence[str]) -> set:
        found = set()
        for i in range(0, len(refs), 500):
            part = list(refs[i:i + 500])
            rows = self.db.execute(
                "SELECT eval_ref FROM evaluations WHERE survey_id = ? AND eval_ref IN (%s)" % ",".join("?" * len(part)),
                (survey_id, *part),
            ).fetchall()
            found.update(r["eval_ref"] for r in rows)
        return found

    def add_to_days(
        self,
        survey_id: int,
        days: Sequence[str],
        evaluations: Iterable[Tuple],
        answers: Iterable[Tuple],
        tags: Iterable[Tuple],
        issues: Dict[Tuple[str, str, str], int],
    ) -> None:
        """Acrescenta avaliações novas a dias já baixados e marca esses dias como atualizados agora.

        Quem chama garante que as avaliações não estão no cache (ver known_refs).
        """
        fetched_at = now_utc()
        with self.db:
            self.db.executemany("INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?)", list(evaluations))
            self.db.executemany("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?)", list(answers))
            self.db.executemany("INSERT INTO answer_tags VALUES (?,?,?,?,?,?)", list(tags))
            self.db.executemany(
                "INSERT INTO issues (survey_id, day, code, detail, count) VALUES (?,?,?,?,?) "
                "ON CONFLICT (survey_id, day, code, detail) DO UPDATE SET count = count + excluded.count",
                [(survey_id, d, code, detail, n) for (d, code, detail), n in issues.items()],
            )
            for d in days:
                n = self.db.execute(
                    "SELECT COUNT(*) FROM evaluations WHERE survey_id = ? AND day = ?", (survey_id, d)
                ).fetchone()[0]
                self.db.execute(
                    "UPDATE days SET evaluations = ?, fetched_at = ? WHERE survey_id = ? AND day = ?",
                    (n, fetched_at, survey_id, d),
                )

    def purge(self) -> None:
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                p.unlink()
