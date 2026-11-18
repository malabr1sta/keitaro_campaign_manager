import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.keitaro_client import KeitaroClient
from app.main import create_app
from app.models import Base


class Tracker:
    """Synthetic API contract, not a captured response from the user's installation."""

    def __init__(self):
        self.campaigns = {}
        self.streams = {}
        self.offers = [{"id": i, "name": "Кофемашина"} for i in (10, 20, 30)]
        self.writes = []
        self.lose = None
        self.reject = None

    def handle(self, request):
        path = request.url.path.removeprefix("/admin_api/v1/")
        method = request.method
        assert request.headers["Api-Key"] == "test-secret"
        if self.reject:
            return httpx.Response(self.reject, json={"error": "test-secret"})
        if method == "GET":
            if path == "domains":
                data = [{"id": 1, "name": "tracker.example.test"}]
            elif path in ("groups", "traffic_sources"):
                data = [{"id": 1, "name": "Тест"}]
            elif path == "offers":
                data = self.offers
            elif path == "campaigns":
                data = list(self.campaigns.values())
            elif path.startswith("campaigns/"):
                cid = int(path.split("/")[1])
                data = (
                    [s for s in self.streams.values() if s["campaign_id"] == cid]
                    if path.endswith("/streams")
                    else self.campaigns.get(cid)
                )
            elif path.startswith("streams/"):
                data = self.streams.get(int(path.split("/")[1]))
            else:
                data = None
            return httpx.Response(200 if data is not None else 404, json=copy.deepcopy(data))
        body = json.loads(request.content)
        self.writes.append((method, path, copy.deepcopy(body)))
        if method == "POST":
            collection = self.campaigns if path == "campaigns" else self.streams
            item = {**body, "id": len(collection) + 1}
            collection[item["id"]] = item
        else:
            kind, identifier = path.split("/")
            collection = self.campaigns if kind == "campaigns" else self.streams
            item = collection[int(identifier)]
            item.update(body)
        if self.lose == path:
            self.lose = None
            raise httpx.ReadTimeout("Lost response", request=request)
        return httpx.Response(200, json=copy.deepcopy(item))


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        _env_file=None,
        api_key="test-secret",
        keitaro_base_url="https://tracker.example.test",
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
    tracker = Tracker()
    client = KeitaroClient(settings, httpx.MockTransport(tracker.handle))
    app = create_app(settings, client)
    Base.metadata.create_all(app.state.service.sessions.kw["bind"])
    with TestClient(app) as browser:
        yield browser, tracker, app


@pytest.fixture
def payload():
    return {
        "name": "Кофемашина — ноябрь",
        "country_code": "AU",
        "offer_id": 10,
        "domain_id": 1,
        "group_id": 1,
        "traffic_source_id": 1,
    }


def create(browser, payload, key="attempt-1"):
    return browser.post("/api/campaigns", json=payload, headers={"Idempotency-Key": key})
