"""Run with RUN_BROWSER_TESTS=1 uv run --group browser pytest tests/browser."""

import os
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Browser opt-in")


def connect(page, client):
    page.set_default_timeout(10000)
    page.on("pageerror", lambda error: print("Browser error:", error))

    def respond(route):
        request = route.request
        url = urlsplit(request.url)
        response = client.request(
            request.method,
            "http://localhost" + url.path + ("?" + url.query if url.query else ""),
            content=request.post_data_buffer,
            headers=request.headers,
        )
        route.fulfill(
            status=response.status_code, headers=dict(response.headers), body=response.content
        )

    page.route("http://localhost/**", respond)


def select(page, name, query):
    control = page.get_by_label(name, exact=True)
    control.fill(query)
    page.locator("#" + control.get_attribute("aria-controls")).get_by_role(
        "option"
    ).first.wait_for()
    control.press("ArrowDown")
    control.press("Enter")


def test_keyboard_create_edit_reload_mobile(page, env):
    from playwright.sync_api import expect

    client, tracker, _ = env
    connect(page, client)
    page.set_viewport_size({"width": 375, "height": 900})
    page.goto("http://localhost/")
    page.get_by_label("Название кампании").fill("Кофемашина — ноябрь")
    select(page, "Страна", "AU")
    select(page, "Оффер", "10")
    for label in ("Домен", "Группа", "Источник трафика"):
        page.get_by_label(label, exact=True).select_option("1")
    page.get_by_role("button", name="Создать кампанию", exact=True).click()
    expect(page).to_have_url("http://localhost/campaigns/1/edit")
    expect(page.locator("#streams .stream")).to_have_count(2)
    page.get_by_role("button", name="Добавить оффер", exact=True).click()
    select(page, "Найти оффер по ID или названию", "20")
    page.get_by_role("button", name="Добавить", exact=True).click()
    expect(page.locator(".share")).to_have_text(["50%", "50%"])
    page.reload()
    expect(page.locator(".share")).to_have_text(["50%", "50%"])
    page.get_by_role("button", name="Убрать из потока").first.click()
    expect(page.locator(".share")).to_have_text(["100%"])
    expect(page.get_by_role("button", name="Убрать из потока")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        page.evaluate(
            """Array.from(document.querySelectorAll('*'))
        .filter(el => el.getBoundingClientRect().right > window.innerWidth)
        .map(el => ({tag:el.tagName, cls:el.className, width:el.getBoundingClientRect().width}))"""
        )
    )
    assert len(tracker.offers) == 3


def test_two_tabs_conflict(page, context, env, payload):
    from playwright.sync_api import expect

    from tests.conftest import create

    client, _, _ = env
    create(client, payload)
    other = context.new_page()
    for tab in (page, other):
        connect(tab, client)
        tab.goto("http://localhost/campaigns/1/edit")
        tab.get_by_role("button", name="Добавить оффер", exact=True).click()
        select(tab, "Найти оффер по ID или названию", "20")
    page.get_by_role("button", name="Добавить", exact=True).click()
    expect(page.locator(".share")).to_have_text(["50%", "50%"])
    other.get_by_role("button", name="Добавить", exact=True).click()
    expect(other.get_by_text("Поток изменился. Обновите данные.", exact=False)).to_be_visible()
    expect(other.locator(".share")).to_have_text(["100%"])
    other.locator("#streams").get_by_role("button", name="Обновить", exact=True).click()
    expect(other.locator(".share")).to_have_text(["50%", "50%"])
    other.close()


def test_server_failure_does_not_show_success(page, env, payload):
    from playwright.sync_api import expect

    from tests.conftest import create

    client, tracker, _ = env
    create(client, payload)
    connect(page, client)
    page.goto("http://localhost/campaigns/1/edit")
    page.get_by_role("button", name="Добавить оффер", exact=True).click()
    select(page, "Найти оффер по ID или названию", "20")
    tracker.reject = 500
    page.get_by_role("button", name="Добавить", exact=True).click()
    expect(page.get_by_role("button", name="Проверить состояние")).to_be_visible()
    expect(page.locator(".share")).to_have_text(["100%"])
    expect(page.get_by_text("Изменения подтверждены Keitaro.")).to_have_count(0)
