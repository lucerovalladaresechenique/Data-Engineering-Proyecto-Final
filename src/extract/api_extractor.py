"""
api_extractor.py — Extracción desde la API de GeoVictoria
============================================================
Login (sin auth) + AttendanceBook (Token). AttendanceBook trae, en una sola
llamada por rango de fechas + colaboradores: marcas (Punches), turno asignado
por día (Shifts) y permisos vigentes (TimeOffs). No se usa CSV para turnos.

Doc fuente: "API GeoVictoria - Documentación API" (Login, AttendanceBook).

Proyecto: Control de Asistencia — Sesión 2 Python Certified Data Engineer
"""

import time
from datetime import date, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.logger import get_logger

logger = get_logger(__name__)

DATE_FMT = "%Y%m%d%H%M%S"  # yyyyMMddHHmmss exigido por la API


def _build_session(max_retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class GeoVictoriaAPIExtractor:
    """
    Extrae asistencia (marcas + turnos + permisos) desde la API de GeoVictoria.

    Args:
        base_url:   URL del ambiente GeoVictoria, ej. "https://demo.geovictoria.com".
                    Confirmar con el jefe de proyecto asignado cuál ambiente usar.
        api_key:    "Clave Api" del panel Configuraciones Empresa -> Acceso API.
        api_secret: "Secreto" del mismo panel.
        timeout:    Segundos de espera por request.

    Ejemplo:
        extractor = GeoVictoriaAPIExtractor(base_url=..., api_key=..., api_secret=...)
        users = extractor.extract_attendance_book(
            start_date=date(2026, 8, 1), end_date=date(2026, 8, 14),
            user_ids=["76778453", "12345678"],
        )
    """

    def __init__(self, base_url: str, api_key: str, api_secret: str, timeout: int = 30, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.session = _build_session(max_retries=max_retries)
        self._token: str | None = None
        logger.info(f"Extractor inicializado → {self.base_url}")

    # ──────────────────────────────────────────
    # Autenticación
    # ──────────────────────────────────────────

    def login(self) -> str:
        """
        POST /api/v1/Login — único método sin autenticación previa.
        El token expira a las 5 horas; se recomienda pedir uno nuevo por corrida.
        """
        url = f"{self.base_url}/api/v1/Login"
        logger.info(f"Login → {url}")
        resp = self.session.post(
            url, json={"User": self.api_key, "Password": self.api_secret}, timeout=self.timeout
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        logger.info("✓ Token obtenido")
        return self._token

    def _auth_headers(self) -> dict:
        if not self._token:
            self.login()
        return {"Authorization": self._token}

    # ──────────────────────────────────────────
    # AttendanceBook (marcas + turnos + permisos)
    # ──────────────────────────────────────────

    def extract_attendance_book(
        self, start_date: date, end_date: date, user_ids: list[str]
    ) -> list[dict]:
        """
        POST /api/v1/AttendanceBook.

        Args:
            start_date, end_date: rango de fechas a consultar (inclusive).
            user_ids: identificadores de colaboradores registrados en GeoVictoria.

        Returns:
            Lista cruda "Users" tal como la entrega la API (sin aplanar). El
            aplanado a marcas/turnos/permisos se hace en el transformer.
        """
        url = f"{self.base_url}/api/v1/AttendanceBook"
        payload = {
            "StartDate": datetime.combine(start_date, datetime.min.time()).strftime(DATE_FMT),
            "EndDate": datetime.combine(end_date, datetime.max.time()).strftime(DATE_FMT),
            "UserIds": ",".join(user_ids),  # la API espera string con comas, no array JSON, pese al tipo documentado
        }
        logger.info(f"AttendanceBook: {start_date} → {end_date} | {len(user_ids)} colaboradores")
        logger.info(f"Payload enviado: {payload}")

        resp = self.session.post(url, headers=self._auth_headers(), json=payload, timeout=self.timeout)
        if not resp.ok:
            logger.error(f"AttendanceBook falló ({resp.status_code}). Respuesta de la API: {resp.text}")
        resp.raise_for_status()
        users = resp.json().get("Users", [])
        logger.info(f"✓ {len(users)} colaboradores recibidos")
        return users

    def extract_attendance_book_batched(
        self,
        start_date: date,
        end_date: date,
        user_ids: list[str],
        max_users_per_call: int = 200,
        max_records_per_call: int = 1500,
        delay_between_calls: float = 0.3,
    ) -> list[dict]:
        """
        Igual que extract_attendance_book, pero respeta los DOS límites reales
        de la API GeoVictoria:
          - máximo `max_users_per_call` usuarios por llamada (OutOfLimitException 0123)
          - máximo `max_records_per_call` registros totales (usuarios × días) por
            llamada (OutOfLimitException 0008)

        Se parte tanto por lotes de empleados como por ventanas de fechas, y se
        juntan los resultados de todas las llamadas.
        """
        total_days = (end_date - start_date).days + 1
        # Con max_users_per_call fijo, calcula cuántos días caben sin pasar el
        # límite de registros totales (ej. 200 usuarios → 1500//200 = 7 días).
        days_per_batch = max(1, max_records_per_call // max_users_per_call)

        all_users: list[dict] = []
        user_batches = [user_ids[i : i + max_users_per_call] for i in range(0, len(user_ids), max_users_per_call)]

        date_batches = []
        cursor = start_date
        while cursor <= end_date:
            batch_end = min(end_date, date.fromordinal(cursor.toordinal() + days_per_batch - 1))
            date_batches.append((cursor, batch_end))
            cursor = date.fromordinal(batch_end.toordinal() + 1)

        total_calls = len(user_batches) * len(date_batches)
        logger.info(
            f"Batching AttendanceBook: {len(user_batches)} lotes de empleados × "
            f"{len(date_batches)} ventanas de fechas = {total_calls} llamadas totales"
        )

        call_num = 0
        for batch_start, batch_end in date_batches:
            for user_batch in user_batches:
                call_num += 1
                logger.info(f"Llamada {call_num}/{total_calls}: {batch_start}→{batch_end} | {len(user_batch)} empleados")
                users = self.extract_attendance_book(batch_start, batch_end, user_batch)
                all_users.extend(users)
                time.sleep(delay_between_calls)

        logger.info(f"✓ {len(all_users)} registros de colaborador/ventana recibidos en total ({total_calls} llamadas)")
        return all_users

    def extract_attendance_book_by_day(
        self, start_date: date, end_date: date, user_ids: list[str], delay_between_calls: float = 0.2
    ):
        """
        Igual que extract_attendance_book, pero pide un día a la vez y lo entrega
        como generador (lazy loading) — útil para rangos largos, evita respuestas
        gigantes y facilita reprocesar un solo día si falla.

        Yields:
            (fecha, lista_users) por cada día del rango.
        """
        current = start_date
        while current <= end_date:
            users = self.extract_attendance_book(current, current, user_ids)
            yield current, users
            time.sleep(delay_between_calls)
            current = date.fromordinal(current.toordinal() + 1)