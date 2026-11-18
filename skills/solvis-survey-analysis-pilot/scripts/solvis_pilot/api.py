"""Cliente HTTP da API pública V1 da Solvis (somente leitura).

Usa apenas: POST /api/v1/oauth/token, GET /api/v1/surveys(/:id),
GET /api/v1/surveyed_units e GET /api/v1/surveys/:id/evaluations_with_tags.

Regras de segurança aplicadas aqui (não remover):
- nenhum endpoint de escrita é chamado (a API V2 só tem escrita e uma leitura
  que depende de um answer_id que a V1 não expõe);
- avaliações só são pedidas para pesquisas que a própria credencial lista em
  GET /api/v1/surveys (ver Catalog.require_survey);
- os parâmetros search_date_scope e reliable nunca são enviados;
- a credencial e o token nunca vão para a saída.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import USER_AGENT
from .config import Settings
from .errors import EXIT_API, EngineError

LIST_PAGE_SIZE = 100
REQUEST_TIMEOUT_S = 180
RETRY_DELAYS_S = (2, 5, 15)


class WindowError(Exception):
    """A API recusou uma janela de avaliações (HTTP 400/404/5xx persistente)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class ApiClient:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._token_path = settings.cache_dir / "token.json"
        self._token: Optional[Dict[str, Any]] = None
        self.calls = 0

    # ------------------------------------------------------------------ token
    def _load_token(self) -> Optional[Dict[str, Any]]:
        if self._token is not None:
            return self._token
        try:
            self._token = json.loads(self._token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._token = None
        return self._token

    def _save_token(self, body: Dict[str, Any]) -> None:
        expires_in = int(body.get("expires_in") or 7200)
        self._token = {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token"),
            "expires_at": time.time() + expires_in - 120,
        }
        self._token_path.write_text(json.dumps(self._token), encoding="utf-8")
        try:
            os.chmod(self._token_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _post_token(self, payload: Dict[str, str]) -> Tuple[int, Any]:
        return self._raw("POST", "/api/v1/oauth/token", body=payload, auth=False)

    def _login(self) -> None:
        status, body = self._post_token({"username": self.s.username, "password": self.s.password})
        if status in (200, 201) and isinstance(body, dict) and body.get("access_token"):
            self._save_token(body)
            return
        raise EngineError(
            "auth_failed",
            "A API Solvis recusou a credencial (usuário ou senha inválidos, ou credencial resetada).",
            hint="Confira a credencial na tela Arquivo > Cliente > Lista de credenciais da API.",
            exit_code=EXIT_API,
        )

    def _access_token(self, force_new: bool = False) -> str:
        token = None if force_new else self._load_token()
        if token and token.get("expires_at", 0) > time.time():
            return token["access_token"]
        if token and token.get("refresh_token") and not force_new:
            status, body = self._post_token({"refresh_token": token["refresh_token"]})
            if status in (200, 201) and isinstance(body, dict) and body.get("access_token"):
                self._save_token(body)
                return self._token["access_token"]  # type: ignore[index]
        self._login()
        return self._token["access_token"]  # type: ignore[index]

    # ------------------------------------------------------------------ http
    def _raw(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        auth: bool = True,
        token: Optional[str] = None,
    ) -> Tuple[int, Any]:
        url = self.s.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = "Bearer " + (token or self._access_token())

        last_exc: Optional[BaseException] = None
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                    return resp.status, _parse_json(resp.read())
            except urllib.error.HTTPError as exc:
                status = exc.code
                payload = _parse_json(exc.read())
                if status == 429 or status >= 500:
                    last_exc = exc
                    if attempt < len(RETRY_DELAYS_S):
                        retry_after = exc.headers.get("Retry-After") if exc.headers else None
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else RETRY_DELAYS_S[attempt]
                        time.sleep(min(delay, 60))
                        continue
                return status, payload
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_exc = exc
                if attempt < len(RETRY_DELAYS_S):
                    time.sleep(RETRY_DELAYS_S[attempt])
                    continue
        if isinstance(last_exc, urllib.error.HTTPError):
            return last_exc.code, None
        raise EngineError(
            "api_unreachable",
            f"Não consegui falar com a API Solvis em {self.s.base_url}: {last_exc}",
            hint="Verifique a conexão e se o host permite acesso de rede a esse endereço.",
            exit_code=EXIT_API,
        )

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        status, body = self._raw("GET", path, params=params)
        if status == 401:
            status, body = self._raw("GET", path, params=params, token=self._access_token(force_new=True))
        if status == 401:
            raise EngineError("auth_failed", "A API Solvis recusou o token de acesso.", exit_code=EXIT_API)
        return status, body

    # -------------------------------------------------------------- endpoints
    def _paginate(self, path: str) -> List[Dict[str, Any]]:
        seen: Dict[int, Dict[str, Any]] = {}
        page = 1
        while True:
            status, body = self.get(path, {"page": page, "per_page": LIST_PAGE_SIZE})
            if status != 200 or not isinstance(body, dict):
                raise EngineError("api_error", f"{path} respondeu HTTP {status}.", exit_code=EXIT_API)
            items = body.get("data") or []
            if not items:
                break
            for item in items:
                seen[item["id"]] = item
            if len(items) < LIST_PAGE_SIZE:
                break
            page += 1
        return list(seen.values())

    def list_surveys(self) -> List[Dict[str, Any]]:
        return self._paginate("/api/v1/surveys")

    def get_survey(self, survey_id: int) -> Optional[Dict[str, Any]]:
        status, body = self.get(f"/api/v1/surveys/{int(survey_id)}")
        if status != 200 or not isinstance(body, dict):
            raise EngineError("api_error", f"/api/v1/surveys/{survey_id} respondeu HTTP {status}.", exit_code=EXIT_API)
        return body.get("data")

    def list_units(self) -> List[Dict[str, Any]]:
        return self._paginate("/api/v1/surveyed_units")

    def evaluations_with_tags(
        self, survey_id: int, start: dt.datetime, end: dt.datetime, per_page: int
    ) -> List[Dict[str, Any]]:
        """Avaliações com started_at (hora local da unidade) em [start, end], inclusivo.

        A API não converte fuso: o horário enviado sem offset é comparado direto com
        started_at, que já está na hora local da unidade.
        """
        params = {
            "start_date": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end_date": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "page": 1,
            "per_page": per_page,
        }
        status, body = self.get(f"/api/v1/surveys/{int(survey_id)}/evaluations_with_tags", params)
        if status == 200 and isinstance(body, dict) and isinstance(body.get("data"), list):
            return body["data"]
        message = ""
        if isinstance(body, dict):
            message = str(body.get("error") or body.get("message") or "")
        raise WindowError(status, message or "resposta inesperada")


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
