import copy

import httpx
import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import CreationOperation
from app.policy import distribute
from tests.conftest import create


@pytest.mark.parametrize(
    "count,expected", [(1, [100]), (2, [50, 50]), (3, [34, 33, 33]), (6, [17, 17, 17, 17, 16, 16])]
)
def test_distribution(count, expected):
    result = distribute([{"offer_id": i, "state": "active"} for i in range(count)])
    assert [o["share"] for o in result] == expected
    assert sum(o["share"] for o in result) == 100


def test_last_and_disabled():
    with pytest.raises(AppError):
        distribute([])
    with pytest.raises(AppError):
        distribute([{"offer_id": 1, "state": "disabled"}])


def test_creation_and_replay(env, payload):
    browser, tracker, app = env
    first = create(browser, payload)
    assert first.status_code == 201, first.text
    second = create(browser, payload)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(tracker.campaigns) == 1 and len(tracker.streams) == 2
    assert create(browser, {**payload, "name": "Other"}).status_code == 409
    geo, fallback = tracker.streams.values()
    assert geo["filters"][0]["payload"] == ["AU"]
    assert geo["action_payload"] == "https://www.google.com/"
    assert fallback["filters"] == [] and fallback["offers"][0]["share"] == 100
    for country, expected in [("AU", geo["id"]), ("GE", fallback["id"])]:
        matched = next(
            s
            for s in tracker.streams.values()
            if not s["filters"] or country in s["filters"][0]["payload"]
        )
        assert matched["id"] == expected
    assert tracker.campaigns[1]["state"] == "active"
    with app.state.service.sessions() as session:
        assert session.scalar(select(CreationOperation)).stage == "complete"


@pytest.mark.parametrize("lost_path", ["campaigns", "streams"])
def test_lost_response_resumes_without_duplicates(env, payload, lost_path):
    browser, tracker, _ = env
    tracker.lose = lost_path
    first = create(browser, payload)
    assert first.status_code == 504
    assert first.json()["operation_id"]
    assert create(browser, payload).status_code == 201
    assert len(tracker.campaigns) == 1 and len(tracker.streams) == 2


def test_lost_second_stream(env, payload):
    browser, tracker, _ = env
    original = tracker.handle

    def handle(request):
        if (
            request.method == "POST"
            and request.url.path.endswith("/streams")
            and len(tracker.streams) == 1
        ):
            tracker.lose = "streams"
        return original(request)

    browser.app.state.service.client.http._transport = httpx.MockTransport(handle)
    assert create(browser, payload).status_code == 504
    assert create(browser, payload).status_code == 201
    assert len(tracker.streams) == 2


def test_ambiguous_does_not_post_again(env, payload):
    browser, tracker, _ = env
    tracker.lose = "campaigns"
    assert create(browser, payload).status_code == 504
    tracker.campaigns.clear()
    writes = len(tracker.writes)
    response = create(browser, payload)
    assert response.status_code == 409
    assert response.json()["code"] == "ambiguous_operation"
    assert len(tracker.writes) == writes


def get_stream(browser):
    return browser.get("/api/campaigns/1").json()["streams"][1]


def test_edit_conflicts_and_preservation(env, payload):
    browser, tracker, _ = env
    create(browser, payload)
    tracker.streams[2]["landings"] = [{"landing_id": 5, "share": 100}]
    original_geo = copy.deepcopy(tracker.streams[1])
    stream = get_stream(browser)
    added = browser.post(
        "/api/campaigns/1/streams/2/offers", json={"offer_id": 20, "revision": stream["revision"]}
    )
    assert added.status_code == 200, added.text
    assert [o["share"] for o in added.json()["streams"][1]["offers"]] == [50, 50]
    stale = browser.post(
        "/api/campaigns/1/streams/2/offers", json={"offer_id": 30, "revision": stream["revision"]}
    )
    assert stale.status_code == 409
    current = get_stream(browser)
    duplicate = browser.post(
        "/api/campaigns/1/streams/2/offers", json={"offer_id": 20, "revision": current["revision"]}
    )
    assert duplicate.status_code == 409
    removed = browser.delete(
        "/api/campaigns/1/streams/2/offers/10", headers={"If-Match": f'"{current["revision"]}"'}
    )
    assert removed.status_code == 200
    assert removed.json()["streams"][1]["offers"] == [
        {"id": 20, "name": "Кофемашина", "state": "active", "share": 100}
    ]
    current = get_stream(browser)
    assert (
        browser.delete(
            "/api/campaigns/1/streams/2/offers/20", headers={"If-Match": f'"{current["revision"]}"'}
        ).status_code
        == 422
    )
    assert tracker.streams[1] == original_geo
    assert tracker.streams[2]["landings"] == [{"landing_id": 5, "share": 100}]
    assert len(tracker.offers) == 3


def test_manual_campaign_and_disabled_links(env, payload):
    browser, tracker, app = env
    create(browser, payload)
    with app.state.service.sessions.begin() as session:
        session.query(CreationOperation).delete()
    tracker.streams[2]["offers"] = [
        {"id": 900, "offer_id": 10, "state": "active", "share": 70},
        {"id": 901, "offer_id": 20, "state": "active", "share": 30},
    ]
    stream = get_stream(browser)
    assert [o["id"] for o in stream["offers"]] == [10, 20]
    assert [o["share"] for o in stream["offers"]] == [70, 30]
    tracker.streams[2]["offers"][0]["state"] = "disabled"
    stream = get_stream(browser)
    assert not stream["editable"]
    assert (
        browser.post(
            "/api/campaigns/1/streams/2/offers",
            json={"offer_id": 30, "revision": stream["revision"]},
        ).status_code
        == 422
    )


def test_wrong_campaign_and_missing_link(env, payload):
    browser, _, _ = env
    create(browser, payload)
    stream = get_stream(browser)
    assert (
        browser.post(
            "/api/campaigns/2/streams/2/offers",
            json={"offer_id": 20, "revision": stream["revision"]},
        ).status_code
        == 404
    )
    assert (
        browser.delete(
            "/api/campaigns/1/streams/2/offers/999", headers={"If-Match": f'"{stream["revision"]}"'}
        ).status_code
        == 404
    )


def test_edit_timeout_readback(env, payload):
    browser, tracker, _ = env
    create(browser, payload)
    tracker.lose = "streams/2"
    stream = get_stream(browser)
    response = browser.post(
        "/api/campaigns/1/streams/2/offers", json={"offer_id": 20, "revision": stream["revision"]}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "field,value", [("name", "  "), ("country_code", "ZZ"), ("offer_id", 0), ("domain_id", 999)]
)
def test_invalid_input_no_remote_writes(env, payload, field, value):
    browser, tracker, _ = env
    assert create(browser, {**payload, field: value}).status_code == 422
    assert tracker.writes == []


def test_errors_and_pages(env):
    browser, tracker, _ = env
    assert browser.get("/").status_code == 200
    assert browser.get("/campaigns/123/edit").status_code == 200
    assert browser.get("/health").json() == {"status": "ok"}
    assert browser.get("/api/countries?q=австралия").json()["items"][0]["id"] == "AU"
    tracker.reject = 403
    result = browser.get("/api/offers")
    assert result.status_code == 502
    assert "test-secret" not in result.text
    assert result.json()["code"] == "upstream_access"


async def test_concurrent_create_single_executor(env, payload):
    import asyncio

    _, tracker, app = env
    original = tracker.handle

    async def delayed(request):
        if request.method == "POST":
            await asyncio.sleep(0.02)
        return original(request)

    app.state.service.client.http._transport = httpx.MockTransport(delayed)
    results = await asyncio.gather(
        app.state.service.create("parallel", payload),
        app.state.service.create("parallel", payload),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AppError) and result.status == 409 for result in results) == 1
    assert len(tracker.campaigns) == 1


async def test_concurrent_edit_detects_stale_revision(env, payload):
    import asyncio

    browser, tracker, app = env
    create(browser, payload)
    stream = get_stream(browser)
    original = tracker.handle

    async def delayed(request):
        if request.method == "PUT":
            await asyncio.sleep(0.02)
        return original(request)

    app.state.service.client.http._transport = httpx.MockTransport(delayed)
    results = await asyncio.gather(
        app.state.service.edit(1, 2, 20, stream["revision"]),
        app.state.service.edit(1, 2, 30, stream["revision"]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AppError) and result.status == 409 for result in results) == 1
    assert len(tracker.streams[2]["offers"]) == 2


def test_removing_from_unequal_shares(env, payload):
    browser, tracker, _ = env
    create(browser, payload)
    tracker.streams[2]["offers"] = [
        {"offer_id": oid, "share": share, "state": "active"}
        for oid, share in [(10, 70), (20, 20), (30, 10)]
    ]
    stream = get_stream(browser)
    response = browser.delete(
        "/api/campaigns/1/streams/2/offers/20",
        headers={"If-Match": f'"{stream["revision"]}"'},
    )
    assert response.status_code == 200
    assert [(o["id"], o["share"]) for o in response.json()["streams"][1]["offers"]] == [
        (10, 50),
        (30, 50),
    ]


def test_unknown_empty_and_weight_rotation(env, payload):
    browser, tracker, _ = env
    create(browser, payload)
    tracker.campaigns[1]["type"] = "weight"
    tracker.streams[1]["schema"] = "custom-version"
    tracker.streams[1]["type"] = "default"
    tracker.streams[2]["weight"] = 80
    result = browser.get("/api/campaigns/1").json()
    assert result["rotation"] == "weight"
    assert result["streams"][0]["id"] == 2
    assert result["streams"][0]["weight"] == 80
    assert "предыдущие" not in result["streams"][0]["filters_summary"]
    assert not result["streams"][1]["editable"]
    tracker.streams.clear()
    assert browser.get("/api/campaigns/1").json()["streams"] == []
