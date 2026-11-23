"""Extração incremental das avaliações para o cache, por dia local.

Comportamentos da API V1 que esta camada trata:
- end_date é comparado no segundo: o motor envia 23:59:59 do último dia.
- a paginação é aplicada por shard e ordenada por created_at (com empates);
  em vez de paginar, o motor pede janelas pequenas o bastante para caber numa
  página e divide a janela ao meio sempre que a página volta cheia;
- uma janela pode voltar com HTTP 200 e lista vazia, ou com HTTP 400: o motor
  divide a janela até isolar o trecho sem dados e registra esse trecho na cobertura;
- dias recentes (hoje e os ainda "nao assentados") nao sao baixados de novo por
  inteiro: o motor pede so o que o servidor recebeu (created_at) depois do ultimo
  download desses dias e acrescenta ao cache. A busca por created_at escolhe os
  shards pela janela pedida, entao uma avaliacao atrasada que cai num shard antigo
  (started_at de outro periodo) nao e vista; decisao assumida, os shards antigos
  quase nao recebem dados novos. Dias antigos continuam sendo relidos por inteiro
  a cada `cache_ttl_days`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from .api import ApiClient, WindowError
from .catalog import Catalog
from .config import Settings
from .errors import EngineError
from . import privacy
from .ingest import eval_ref, local_started_at, normalize_evaluation
from .periods import iter_days
from .semantics import Questionnaire
from .store import Store
from . import store as store_mod

PER_PAGE = 10000            # limite da API (per_page acima disso devolve HTTP 400)
SYNC_WORKERS = 4            # janelas baixadas em paralelo por rodada (SOLVIS_SYNC_WORKERS)
MIN_SPLIT_ON_ERROR = dt.timedelta(hours=1)
MIN_SPLIT_ON_OVERFLOW = dt.timedelta(minutes=1)
MAX_CHUNK_DAYS = 7
UNSETTLED_DAYS = 3          # totens offline enviam avaliações atrasadas; dia "assenta" depois disso
UNSETTLED_MAX_AGE_S = 3600
TODAY_MAX_AGE_S = 600
INCREMENTAL_MARGIN = dt.timedelta(minutes=5)   # folga contra avaliacoes recebidas durante o download anterior
INCREMENTAL_MAX_SPAN = dt.timedelta(days=7)    # acima disso, baixar os dias por inteiro e mais simples
DEFAULT_BUDGET_S = 90       # abaixo do tempo limite de comando da maioria dos hosts

ONE_SECOND = dt.timedelta(seconds=1)


START_MONTH_KEY = "start_month"


def start_month_info(store: Store) -> Dict[str, Any]:
    value = store.get_meta(START_MONTH_KEY)
    return {"start_month": value, "earliest_day": f"{value}-01" if value else None}


def set_start_month(store: Store, value: str, today: dt.date) -> Dict[str, Any]:
    """Guarda o primeiro mês que o usuário quer analisar; nada antes dele é baixado."""
    try:
        first = dt.datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        raise EngineError("invalid_argument", "--start-month usa o formato AAAA-MM (ex.: 2026-03).")
    if first > today.replace(day=1):
        raise EngineError("invalid_argument", "O mês inicial não pode estar no futuro.")
    store.set_meta(START_MONTH_KEY, first.strftime("%Y-%m"))
    return start_month_info(store)


def _age_s(fetched_at: str) -> float:
    return (dt.datetime.fromisoformat(store_mod.now_utc()) - dt.datetime.fromisoformat(fetched_at)).total_seconds()


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
    def plan(self, survey_id: int, start: dt.date, end: dt.date, refresh: bool) -> Tuple[List[dt.date], List[dt.date]]:
        """Separa os dias em (baixar por inteiro, atualizar so com o que chegou depois do ultimo download)."""
        end = min(end, self.s.today)
        if start > end:
            return [], []
        rows = self.store.day_rows(survey_id, start, end)
        full: List[dt.date] = []
        incremental: List[dt.date] = []
        for d in iter_days(start, end):
            row = rows.get(d.isoformat())
            if refresh or row is None:
                full.append(d)
                continue
            age = _age_s(row["fetched_at"])
            fetched_day = dt.datetime.fromisoformat(row["fetched_at"]).date()
            settled = fetched_day >= d + dt.timedelta(days=UNSETTLED_DAYS)
            if row["status"] == "partial":
                if age > (TODAY_MAX_AGE_S if d == self.s.today else UNSETTLED_MAX_AGE_S):
                    full.append(d)
                continue
            if d == self.s.today:
                recent_stale = age > TODAY_MAX_AGE_S
            else:
                recent_stale = not settled and age > UNSETTLED_MAX_AGE_S
            if d == self.s.today or not settled:
                if recent_stale:
                    incremental.append(d)
            elif age > self.s.cache_ttl_days * 86400:
                full.append(d)
        return full, incremental

    def days_to_fetch(self, survey_id: int, start: dt.date, end: dt.date, refresh: bool) -> List[dt.date]:
        full, incremental = self.plan(survey_id, start, end, refresh)
        return sorted(full + incremental)

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
               verify_empty: bool = False, received: bool = False) -> None:
        try:
            data = self.api.evaluations_with_tags(survey_id, ws, we, PER_PAGE, received)
        except WindowError as exc:
            if exc.status == 404:
                raise EngineError("not_found", f"A pesquisa {survey_id} não está disponível para esta credencial.")
            stats["error_windows"] += 1
            if we - ws >= MIN_SPLIT_ON_ERROR:
                for a, b in _split(ws, we):
                    self._fetch(survey_id, a, b, out, failed, stats, verify_empty, received)
            else:
                failed.append((ws, we, f"HTTP {exc.status}: {exc.message[:200]}"))
            return
        if len(data) >= PER_PAGE:
            stats["overflow_windows"] += 1
            if we - ws > MIN_SPLIT_ON_OVERFLOW:
                for a, b in _split(ws, we):
                    self._fetch(survey_id, a, b, out, failed, stats, verify_empty, received)
            else:
                failed.append((ws, we, f"mais de {PER_PAGE} avaliações na mesma janela de 1 minuto"))
            return
        if not data and verify_empty and we.date() > ws.date():
            # Lista vazia inesperada: confere dia a dia para que um dia sem dados custe só o próprio dia.
            stats["empty_windows_verified"] += 1
            for d in iter_days(ws.date(), we.date()):
                self._fetch(survey_id, dt.datetime.combine(d, dt.time(0, 0, 0)),
                            dt.datetime.combine(d, dt.time(23, 59, 59)), out, failed, stats)
            return
        out.extend(data)

    @staticmethod
    def _workers() -> int:
        try:
            return max(1, int(os.environ.get("SOLVIS_SYNC_WORKERS", SYNC_WORKERS)))
        except ValueError:
            return SYNC_WORKERS

    def _fetch_batch(self, survey_id: int, qn: Questionnaire, batch: List[Tuple[dt.date, dt.date]],
                     workers: int) -> List[Tuple[List[Dict[str, Any]], List[Tuple[dt.datetime, dt.datetime, str]], Counter]]:
        """Baixa várias janelas ao mesmo tempo (só rede; a gravação no cache fica com quem chama)."""
        def one(chunk: Tuple[dt.date, dt.date]):
            c_start, c_end = chunk
            ws = dt.datetime.combine(c_start, dt.time(0, 0, 0))
            we = dt.datetime.combine(c_end, dt.time(23, 59, 59))
            raws: List[Dict[str, Any]] = []
            failed: List[Tuple[dt.datetime, dt.datetime, str]] = []
            c_stats: Counter = Counter()
            verify = bool(qn.last_evaluation_date and qn.last_evaluation_date >= c_start.isoformat())
            self._fetch(survey_id, ws, we, raws, failed, c_stats, verify_empty=verify)
            return raws, failed, c_stats

        if workers <= 1 or len(batch) <= 1:
            return [one(c) for c in batch]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, batch))

    def _incremental(self, survey_id: int, qn: Questionnaire, days: List[dt.date],
                     stats: Counter) -> Tuple[List[dt.date], Questionnaire]:
        """Acrescenta ao cache o que o servidor recebeu depois do ultimo download de `days`.

        Devolve (dias que nao deu para atualizar assim e precisam de download inteiro, questionario).
        """
        rows = self.store.day_rows(survey_id, min(days), max(days))
        now = dt.datetime.fromisoformat(store_mod.now_utc())
        oldest = min(dt.datetime.fromisoformat(rows[d.isoformat()]["fetched_at"]) for d in days)
        if now - oldest > INCREMENTAL_MAX_SPAN:
            return list(days), qn
        ws = (oldest - INCREMENTAL_MARGIN).replace(tzinfo=None)
        we = now.replace(tzinfo=None)  # created_at e UTC; end_date e comparado no segundo
        raws: List[Dict[str, Any]] = []
        failed: List[Tuple[dt.datetime, dt.datetime, str]] = []
        self._fetch(survey_id, ws, we, raws, failed, stats, received=True)
        if failed:  # trecho que a API nao devolve: o dia inteiro e baixado por started_at
            return list(days), qn
        stats["incremental_windows"] += 1

        day_set = {d.isoformat() for d in days}
        fresh = []
        for raw in raws:
            started = local_started_at(raw["started_at"])
            if started.date().isoformat() in day_set:
                fresh.append((eval_ref(started, raw["id"]), raw))
        known = self.store.known_refs(survey_id, [ref for ref, _ in fresh])
        new_raws = [raw for ref, raw in fresh if ref not in known]

        evals, answers, tags, issues = self._normalize(qn, new_raws, day_set)
        if any(code == "unmapped_question" for _, code, _ in issues):
            qn = self.catalog.refresh_questionnaire(survey_id)
            evals, answers, tags, issues = self._normalize(qn, new_raws, day_set)
        self.store.add_to_days(
            survey_id, sorted(day_set), evals.values(),
            [a for refs in answers.values() for a in refs],
            [t for refs in tags.values() for t in refs],
            dict(issues),
        )
        stats["incremental_new"] += len(evals)
        return [], qn

    def _normalize(self, qn: Questionnaire, raws: List[Dict[str, Any]], day_set: set):
        issues: Counter = Counter()
        evals: Dict[str, Tuple] = {}
        answers: Dict[str, List[Tuple]] = {}
        tags: Dict[str, List[Tuple]] = {}
        for raw in raws:
            ev, ans, tg = normalize_evaluation(raw, qn, issues, privacy.lgpd_text_enabled(self.store))
            if ev[2] not in day_set:  # não deveria acontecer: janelas são alinhadas ao dia
                issues[(ev[2], "evaluation_outside_window", ev[1])] += 1
                continue
            evals[ev[1]], answers[ev[1]], tags[ev[1]] = ev, ans, tg
        issues = Counter({k: v for k, v in issues.items() if k[0] in day_set})
        return evals, answers, tags, issues

    def _check_start_month(self, start: dt.date) -> None:
        info = start_month_info(self.store)
        if not info["start_month"]:
            raise EngineError(
                "start_month_required",
                "Falta definir a partir de que mês o usuário quer analisar os dados.",
                hint="Pergunte ao usuário o primeiro mês que interessa (quanto mais recente, mais rápido o primeiro "
                     "download) e rode `config --start-month AAAA-MM`. Depois repita a consulta.",
            )
        if start.isoformat() < info["earliest_day"]:
            raise EngineError(
                "period_before_start",
                f"O período começa em {start.isoformat()}, antes do mês inicial configurado ({info['start_month']}).",
                hint=f"Use datas a partir de {info['earliest_day']}, ou, se o usuário quiser dados mais antigos, "
                     "rode `config --start-month AAAA-MM` com um mês anterior (o download será maior).",
                details=info,
            )

    def ensure(self, survey_id: int, start: dt.date, end: dt.date, refresh: bool = False) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._check_start_month(start)
        qn = self.catalog.require_survey(survey_id)
        need, recent = self.plan(survey_id, start, end, refresh)
        chunk_days = int(self.store.get_meta(f"chunk_days:{survey_id}") or MAX_CHUNK_DAYS)
        fetched_days: List[str] = []
        failed_all: List[List[str]] = []
        stats: Counter = Counter()
        calls_before = self.api.calls
        refreshed_questionnaire = False
        incremental_days = 0
        if recent:
            qn_before = qn
            leftover, qn = self._incremental(survey_id, qn, recent, stats)
            refreshed_questionnaire = qn is not qn_before
            incremental_days = len(recent) - len(leftover)
            need = sorted(need + leftover)
        remaining = list(need)
        wrote = incremental_days > 0

        chunks = self._chunks(need, chunk_days)
        workers = max(1, min(self._workers(), len(chunks) or 1))
        if workers > 1 and chunks:
            self.api.warm_up()  # token obtido antes das threads, para não logar em paralelo
        pos = 0
        while pos < len(chunks):
            if time.monotonic() - t0 > self.budget_s:
                break
            batch = chunks[pos:pos + workers]
            pos += len(batch)
            results = self._fetch_batch(survey_id, qn, batch, workers)
            for (c_start, c_end), (raws, failed, c_stats) in zip(batch, results):
                overflow_before = stats["overflow_windows"]
                stats.update(c_stats)
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
                wrote = True
                fetched_days.extend(days)
                remaining = [d for d in remaining if d.isoformat() not in day_set]

                # ajusta o tamanho da janela para a próxima rodada
                if stats["overflow_windows"] > overflow_before:
                    chunk_days = max(1, chunk_days // 2)
                elif len(raws) < PER_PAGE // 4 and chunk_days < MAX_CHUNK_DAYS:
                    chunk_days += 1
            self.store.set_meta(f"chunk_days:{survey_id}", str(chunk_days))
            if chunk_days != (chunks[pos - 1][1] - chunks[pos - 1][0]).days + 1 and pos < len(chunks):
                # tamanho de janela mudou: replaneja o que falta com o novo tamanho
                chunks = chunks[:pos] + self._chunks([d for d in remaining], chunk_days)

        if wrote:
            self.store.analyze()

        return {
            "survey_id": survey_id,
            "requested": {"start": start.isoformat(), "end": end.isoformat()},
            "days_fetched": len(fetched_days),
            "days_reused": len([d for d in iter_days(start, min(end, self.s.today))]) - len(need),
            "days_updated_incrementally": incremental_days,
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
