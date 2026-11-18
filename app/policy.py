import hashlib
import json

from app.errors import AppError


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def active(value):
    return value in ("active", "enabled", 1, True)


def editable(stream):
    return (
        stream.get("schema") == "landings"
        and stream.get("type") == "regular"
        and active(stream.get("state"))
        and bool(stream.get("offers"))
        and all(active(o.get("state")) for o in stream["offers"])
    )


def revision(stream):
    # Include all routing settings; ignore names and tracker-generated timestamps.
    keys = (
        "campaign_id",
        "type",
        "schema",
        "state",
        "offers",
        "landings",
        "filters",
        "action_type",
        "action_payload",
        "position",
        "weight",
        "collect_clicks",
        "filter_or",
        "offer_selection",
        "landing_selection",
    )
    return fingerprint({k: stream.get(k) for k in keys})


def distribute(offers):
    if not offers:
        raise AppError(422, "last_offer", "Нельзя убрать последний активный оффер.")
    if any(not active(o.get("state")) for o in offers):
        raise AppError(
            422, "disabled_offer", "Поток с выключенными связями доступен только для чтения."
        )
    share, remainder = divmod(100, len(offers))
    return [
        {"offer_id": int(o["offer_id"]), "state": o["state"], "share": share + (i < remainder)}
        for i, o in enumerate(offers)
    ]
