import httpx

from app.errors import AppError


class KeitaroClient:
    """Version-specific API boundary. Write payloads never copy raw responses."""

    def __init__(self, settings, transport=None):
        self.configured = bool(settings.keitaro_base_url and settings.api_key)
        self.http = httpx.AsyncClient(
            base_url=settings.keitaro_base_url.rstrip("/") + "/admin_api/v1/",
            headers={"Api-Key": settings.api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(20, connect=5),
            transport=transport,
        )

    async def request(self, method, path, **kwargs):
        if not self.configured:
            raise AppError(502, "configuration", "Задайте KEITARO_BASE_URL и API_KEY в .env.")
        try:
            response = await self.http.request(method, path.lstrip("/"), **kwargs)
        except httpx.TimeoutException:
            raise AppError(504, "upstream_timeout", "Keitaro не ответил вовремя.") from None
        except httpx.HTTPError:
            raise AppError(
                502, "upstream_unavailable", "Не удалось подключиться к Keitaro."
            ) from None
        if response.status_code == 404:
            raise AppError(404, "not_found", "Запись не найдена в Keitaro.")
        if response.status_code in (401, 403):
            raise AppError(
                502, "upstream_access", "Доступ к API закрыт. Проверьте ключ, права и Cloudflare."
            )
        if response.is_error:
            raise AppError(
                502, "upstream_error", "Keitaro отклонил запрос. Проверьте контракт API стенда."
            )
        try:
            return response.json()
        except ValueError:
            raise AppError(
                502, "upstream_format", "Keitaro вернул неожиданный формат ответа."
            ) from None

    async def get(self, path):
        return await self.request("GET", path)

    async def post(self, path, data):
        return await self.request("POST", path, json=data)

    async def put(self, path, data):
        return await self.request("PUT", path, json=data)

    async def close(self):
        await self.http.aclose()
