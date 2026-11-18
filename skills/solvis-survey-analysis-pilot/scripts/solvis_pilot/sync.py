"""Extração incremental das avaliações para o cache, por dia local.

Comportamentos da API V1 que esta camada contorna (surveys_controller.rb):
- end_date é comparado no segundo: o motor envia 23:59:59 do último dia.
- a paginação é aplicada por shard e ordenada por created_at (com empates);
  em vez de paginar, o motor pede janelas pequenas o bastante para caber numa
  página e divide a janela ao meio sempre que a página volta cheia;
- um erro na montagem das respostas devolve HTTP 200 com lista vazia, e outros
  erros devolvem HTTP 400 para a janela inteira: o motor divide a janela até
  isolar o trecho com falha e registra esse trecho na cobertura.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .api import ApiClient, WindowError
from .catalog import Catalog
from .config import Settings
from .errors import EngineError
from .ingest import normalize_evaluation
from .periods import iter_days
from .semantics import Questionnaire
from .store import Store

PER_PAGE = 5000
MIN_SPLIT_ON_ERROR = dt.timedelta(hours=1)
MIN_SPLIT_ON_OVERFLOW = dt.timedelta(minutes=1)
MAX_CHUNK_DAYS = 7
UNSETTLED_DAYS = 3          # totens offline enviam avaliações atrasadas; dia "assenta" depois disso
UNSETTLED_MAX_AGE_S = 3600
TODAY_MAX_AGE_S = 600
DEFAULT_BUDGET_S = 90       # abaixo do tempo limite de comando da maioria dos hosts

ONE_SECOND = dt.timedelta(seconds=1)


def _age_s(fetched_at: str) -> float:
    return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(fetched_at)).total_seconds()


def _split(ws: dt.datetime, we: dt.datetime) -> Tuple[Tuple[dt.datetime, dt.datetime], Tuple[dt.datetime, dt.datetime]]:
    span_days = (we.date() - ws.date()).days + 1
    if span_days >= 2:
        mid = dt.datetime.combine(ws.date() + dt.timedelta(days=span_days // 2), dt.time(0, 0, 0))
    else:
        total = int((we - ws).total_seconds()) + 1
        mid = ws + dt.timedelta(seconds=total // 2)
    return (ws, mid - ONE_SECOND), (mid, we)


class Syncer:
    def __init__(self, store: Store, api: ApiClient, catalog: Catalog, settings: Settings,
                 budget_s: Optional[float] = None) -> None:
        self.store = store
        self.api = api
        self.catalog = catalog
        self.s = settings
        self.budget_s = DEFAULT_BUDGET_S if budget_s is None else budget_s

    # ------------------------------------------------------------ planning
    def days_to_fetch(self, survey_id: int, start: dt.date, end: dt.date, refresh: bool) -> List[dt.date]:
        end = min(end, self.s.today)
        if start > end:
            return []
        rows = self.store.day_rows(survey_id, start, end)
        need: List[dt.date] = []
        for d in iter_days(start, end):
            row = rows.get(d.isoformat())
            if refresh or row is None:
                need.append(d)
                continue
            age = _age_s(row["fetched_at"])
            fetched_day = dt.datetime.fromisoformat(row["fetched_at"]).date()
            settled = fetched_day >= d + dt.timedelta(days=UNSETTLED_DAYS)
            if d == self.s.today:
                stale = age > TODAY_MAX_AGE_S
            elif not settled:
                stale = age > UNSETTLED_MAX_AGE_S
            else:
                stale = age > self.s.cache_ttl_days * 86400
            if stale or (row["status"] == "partial" and age > UNSETTLED_MAX_AGE_S):
                need.append(d)
        return need

    @staticmethod
    def _chunks(days: List[dt.date], size: int) -> List[Tuple[dt.date, dt.date]]:
        chunks: List[Tuple[dt.date, dt.date]] = []
        run: List[dt.date] = []
        for d in days:
            if run and (d - run[-1]).days != 1 or len(run) >= size:
                chunks.append((run[0], run[-1]))
                run = []
            run.append(d)
        if run:
            chunks.append((run[0], run[-1]))
        return chunks

    # ------------------------------------------------------------- fetching
    def _fetch(self, survey_id: int, ws: dt.datetime, we: dt.datetime,
               out: List[Dict[str, Any]], failed: List[Tuple[dt.datetime, dt.datetime, str]], stats: Counter,
               verify_empty: bool = False) -> None:
        try:
            data = self.api.evaluations_with_tags(survey_id, ws, we, PER_PAGE)
        except WindowError as exc:
            if exc.status == 404:
                raise EngineError("not_found", f"A pesquisa {survey_id} não está disponível para esta credencial.")
            stats["error_windows"] += 1
            if we - ws >= MIN_SPLIT_ON_ERROR:
                for a, b in _split(ws, we):
                    self._fetch(survey_id, a, b, out, failed, stats, verify_empty)
            else:
                failed.append((ws, we, f"HTTP {exc.status}: {exc.message[:200]}"))
            return
        if len(data) >= PER_PAGE:
            stats["overflow_windows"] += 1
            if we - ws > MIN_SPLIT_ON_OVERFLOW:
                for a, b in _split(ws, we):
                    self._fetch(survey_id, a, b, out, failed, stats, verify_empty)
            else:
                failed.append((ws, we, f"mais de {PER_PAGE} avaliações na mesma janela de 1 minuto"))
            return
        if not data and verify_empty and we.date() > ws.date():
            # Lista vazia pode ser falha silenciosa da API (uma avaliação que não monta zera a janela).
            # Confere dia a dia para que uma falha custe só o próprio dia.
            stats["empty_windows_verified"] += 1
            for d in iter_days(ws.date(), we.date()):
                self._fetch(survey_id, dt.datetime.combine(d, dt.time(0, 0, 0)),
                            dt.datetime.combine(d, dt.time(23, 59, 59)), out, failed, stats)
            return
        out.extend(data)

    def _normalize(self, qn: Questionnaire, raws: List[Dict[str, Any]], day_set: set):
        issues: Counter = Counter()
        evals: Dict[str, Tuple] = {}
        answers: Dict[str, List[Tuple]] = {}
        tags: Dict[str, List[Tuple]] = {}
        for raw in raws:
            ev, ans, tg = normalize_evaluation(raw, qn, issues)
            if ev[2] not in day_set:  # não deveria acontecer: janelas são alinhadas ao dia
                issues[(ev[2], "evaluation_outside_window", ev[1])] += 1
                continue
            evals[ev[1]], answers[ev[1]], tags[ev[1]] = ev, ans, tg
        issues = Counter({k: v for k, v in issues.items() if k[0] in day_set})
        return evals, answers, tags, issues

    def ensure(self, survey_id: int, start: dt.date, end: dt.date, refresh: bool = False) -> Dict[str, Any]:
        t0 = time.monotonic()
        qn = self.catalog.require_survey(survey_id)
        need = self.days_to_fetch(survey_id, start, end, refresh)
        chunk_days = int(self.store.get_meta(f"chunk_days:{survey_id}") or MAX_CHUNK_DAYS)
        fetched_days: List[str] = []
        failed_all: List[List[str]] = []
        stats: Counter = Counter()
        calls_before = self.api.calls
        refreshed_questionnaire = False
        remaining = list(need)

        for c_start, c_end in self._chunks(need, chunk_days):
            if time.monotonic() - t0 > self.budget_s:
                break
            ws = dt.datetime.combine(c_start, dt.time(0, 0, 0))
            we = dt.datetime.combine(c_end, dt.time(23, 59, 59))
            raws: List[Dict[str, Any]] = []
            failed: List[Tuple[dt.datetime, dt.datetime, str]] = []
            overflow_before = stats["overflow_windows"]
            verify = bool(qn.last_evaluation_date and qn.last_evaluation_date >= c_start.isoformat())
            self._fetch(survey_id, ws, we, raws, failed, stats, verify_empty=verify)

            days = [d.isoformat() for d in iter_days(c_start, c_end)]
            day_set = set(days)
            evals, answers, tags, issues = self._normalize(qn, raws, day_set)
            if not refreshed_questionnaire and any(code == "unmapped_question" for _, code, _ in issues):
                # questionário editado depois do último download: relê e mapeia de novo
                qn = self.catalog.refresh_questionnaire(survey_id)
                refreshed_questionnaire = True
                evals, answers, tags, issues = self._normalize(qn, raws, day_set)

            failed_by_day: Dict[str, List[List[str]]] = {}
            for fs, fe, reason in failed:
                window = [fs.strftime("%Y-%m-%d %H:%M:%S"), fe.strftime("%Y-%m-%d %H:%M:%S"), reason]
                failed_all.append(window)
                for d in iter_days(fs.date(), fe.date()):
                    failed_by_day.setdefault(d.isoformat(), []).append(window)

            self.store.replace_days(
                survey_id,
                days,
                evals.values(),
                [a for refs in answers.values() for a in refs],
                [t for refs in tags.values() for t in refs],
                dict(issues),
                failed_by_day,
            )
            fetched_days.extend(days)
            remaining = [d for d in remaining if d.isoformat() not in day_set]

            # ajusta o tamanho da janela para a próxima rodada
            if stats["overflow_windows"] > overflow_before:
                chunk_days = max(1, chunk_days // 2)
            elif len(raws) < PER_PAGE // 4 and chunk_days < MAX_CHUNK_DAYS:
                chunk_days += 1
            self.store.set_meta(f"chunk_days:{survey_id}", str(chunk_days))

        return {
            "survey_id": survey_id,
            "requested": {"start": start.isoformat(), "end": end.isoformat()},
            "days_fetched": len(fetched_days),
            "days_reused": len([d for d in iter_days(start, min(end, self.s.today))]) - len(need),
            "days_remaining": len(remaining),
            "complete": not remaining,
            "failed_windows": failed_all,
            "api_calls": self.api.calls - calls_before,
            "elapsed_s": round(time.monotonic() - t0, 1),
            "questionnaire_refreshed": refreshed_questionnaire,
        }


def coverage(store: Store, survey_id: int, start: dt.date, end: dt.date, today: dt.date) -> Dict[str, Any]:
    """Cobertura do cache para um período: o que foi baixado, quando, e o que falhou."""
    rows = store.day_rows(survey_id, start, end)
    past_end = min(end, today)
    expected = [d.isoformat() for d in iter_days(start, past_end)] if start <= past_end else []
    missing = [d for d in expected if d not in rows]
    partial = [d for d in expected if d in rows and rows[d]["status"] == "partial"]
    failed: List[Any] = []
    for d in partial:
        failed.extend(json.loads(rows[d]["failed_windows"] or "[]"))
    fetched = [rows[d]["fetched_at"] for d in expected if d in rows]
    empty_days = [d for d in expected if d in rows and rows[d]["evaluations"] == 0]
    unique_failed = []
    for w in failed:
        if w not in unique_failed:
            unique_failed.append(w)
    return {
        "days_expected": len(expected),
        "days_complete": len(expected) - len(missing) - len(partial),
        "days_partial": len(partial),
        "days_missing": len(missing),
        "days_without_evaluations": len(empty_days),
        "failed_windows": unique_failed[:20],
        "fetched_oldest": min(fetched) if fetched else None,
        "fetched_newest": max(fetched) if fetched else None,
    }
