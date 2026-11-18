import httpx
import pytest

from app.config import Settings
from app.errors import AppError
from app.keitaro_client import KeitaroClient


@pytest.mark.parametrize("status,expected", [(401, 502), (403, 502), (404, 404), (500, 502)])
async def test_error_mapping_and_redaction(status, expected):
    settings = Settings(
        _env_file=None, keitaro_base_url="https://tracker.example.test", api_key="never-print-me"
    )
    client = KeitaroClient(
        settings,
        httpx.MockTransport(
            lambda request: httpx.Response(status, json={"message": "never-print-me"})
        ),
    )
    try:
        with pytest.raises(AppError) as caught:
            await client.get("offers")
        assert caught.value.status == expected
        assert "never-print-me" not in str(caught.value.payload)
    finally:
        await client.close()


async def test_timeout_and_bad_json():
    def timeout(request):
        raise httpx.ReadTimeout("never-print-me", request=request)

    settings = Settings(
        _env_file=None, keitaro_base_url="https://tracker.example.test", api_key="never-print-me"
    )
    for transport, expected in [
        (httpx.MockTransport(timeout), 504),
        (httpx.MockTransport(lambda r: httpx.Response(200, text="HTML")), 502),
    ]:
        client = KeitaroClient(settings, transport)
        try:
            with pytest.raises(AppError) as caught:
                await client.get("offers")
            assert caught.value.status == expected
        finally:
            await client.close()
