import asyncio
from collections import defaultdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.errors import AppError
from app.models import CreationOperation
from app.policy import active, distribute, editable, fingerprint, revision


class CampaignService:
    def __init__(self, client, sessions, settings):
        self.client = client
        self.sessions = sessions
        self.settings = settings
        self.operations_lock = asyncio.Lock()
        self.stream_locks = defaultdict(asyncio.Lock)
        self.running = set()

    async def catalog(self, kind, query=""):
        rows = await self.client.get(kind)
        if not isinstance(rows, list):
            raise AppError(502, "upstream_format", "Ожидался список записей Keitaro.")
        q = query.strip().casefold()
        return [
            {"id": int(x["id"]), "name": x.get("name", "")}
            for x in rows
            if q in str(x["id"]) or q in x.get("name", "").casefold()
        ][:50]

    async def configuration(self):
        domains, groups, sources = await asyncio.gather(
            self.client.get("domains"),
            self.client.get("groups?type=campaigns"),
            self.client.get("traffic_sources"),
        )

        def items(rows):
            return [
                {"id": int(x["id"]), "name": x.get("name") or x.get("domain") or str(x["id"])}
                for x in rows
            ]

        return {
            "domains": items(domains),
            "groups": items(groups),
            "sources": items(sources),
            "defaults": {
                "domain_id": self.settings.keitaro_domain_id,
                "group_id": self.settings.keitaro_group_id,
                "traffic_source_id": self.settings.keitaro_traffic_source_id,
            },
        }

    async def campaign(self, cid):
        campaign, streams, offers, config = await asyncio.gather(
            self.client.get(f"campaigns/{cid}"),
            self.client.get(f"campaigns/{cid}/streams"),
            self.client.get("offers"),
            self.configuration(),
        )
        names = {int(x["id"]): x.get("name", "") for x in offers}

        def lookup(rows, value):
            return next((x for x in rows if str(x["id"]) == str(value)), {"id": value, "name": ""})

        result = {
            "id": int(campaign["id"]),
            "name": campaign.get("name", ""),
            "rotation": campaign.get("type", "unknown"),
            "domain": lookup(config["domains"], campaign.get("domain_id")),
            "group": lookup(config["groups"], campaign.get("group_id")),
            "traffic_source": lookup(config["sources"], campaign.get("traffic_source_id")),
            "streams": [],
        }
        priority = {"forced": 0, "regular": 1, "default": 2}
        streams = sorted(
            streams,
            key=lambda s: (
                priority.get(s.get("type"), 3),
                int(s.get("position") or 0),
                int(s["id"]),
            ),
        )
        for s in streams:
            is_offers = s.get("schema") == "landings"
            filters = s.get("filters") or []
            summary = "; ".join(self.describe_filter(f) for f in filters)
            if not summary:
                summary = "Без фильтров"
            if not filters and s.get("type") == "regular" and campaign.get("type") == "position":
                summary += ", если предыдущие потоки не приняли посетителя"
            result["streams"].append(
                {
                    "id": int(s["id"]),
                    "name": s.get("name", ""),
                    "type": s.get("type"),
                    "position": s.get("position"),
                    "weight": s.get("weight"),
                    "state": "active" if active(s.get("state")) else s.get("state"),
                    "filters_summary": summary,
                    "destination_kind": "offers" if is_offers else s.get("schema", "unknown"),
                    "destination_label": "Офферы"
                    if is_offers
                    else str(
                        s.get("action_payload") or s.get("action_type") or "Неизвестная схема"
                    ),
                    "editable": editable(s),
                    "revision": revision(s),
                    "readonly_reason": (
                        "Изменение доступно для обычного активного потока с активными офферами."
                    ),
                    "offers": [
                        {
                            "id": int(o["offer_id"]),
                            "name": names.get(int(o["offer_id"]), ""),
                            "state": "active" if active(o.get("state")) else o.get("state"),
                            "share": o.get("share"),
                        }
                        for o in s.get("offers", [])
                    ],
                }
            )
        return result

    @staticmethod
    def describe_filter(item):
        payload = item.get("payload", "")
        value = ", ".join(map(str, payload)) if isinstance(payload, list) else str(payload)
        if item.get("name") == "country" and item.get("mode") in ("accept", "reject"):
            condition = "входит в" if item["mode"] == "accept" else "не входит в"
            return f"Страна {condition} {value}"
        return f"{item.get('name', '?')} {item.get('mode', '')}: {value}"

    async def edit(self, cid, sid, oid, expected_revision, remove=False):
        async with self.stream_locks[sid]:
            stream = await self.client.get(f"streams/{sid}")
            if int(stream["campaign_id"]) != cid:
                raise AppError(404, "not_found", "Поток не принадлежит выбранной кампании.")
            if revision(stream) != expected_revision:
                raise AppError(409, "stale_revision", "Поток изменился. Обновите данные.")
            if not editable(stream):
                raise AppError(422, "readonly_stream", "Этот поток доступен только для чтения.")
            offers = stream["offers"]
            exists = any(int(o["offer_id"]) == oid for o in offers)
            if remove:
                if not exists:
                    raise AppError(404, "not_found", "Оффер отсутствует в потоке.")
                offers = [o for o in offers if int(o["offer_id"]) != oid]
            else:
                if exists:
                    raise AppError(409, "duplicate_offer", "Оффер уже добавлен в поток.")
                catalog = await self.client.get("offers")
                if not any(int(o["id"]) == oid for o in catalog):
                    raise AppError(422, "invalid_offer", "Оффер не найден в каталоге.")
                offers = [*offers, {"offer_id": oid, "state": "active"}]
            updated = distribute(offers)
            try:
                await self.client.put(f"streams/{sid}", {"offers": updated})
            except AppError as error:
                if error.status not in (502, 504):
                    raise
                actual = await self.client.get(f"streams/{sid}")
                if not self.same_offers(actual.get("offers", []), updated):
                    raise error
            actual = await self.client.get(f"streams/{sid}")
            if not self.same_offers(actual.get("offers", []), updated):
                raise AppError(409, "write_conflict", "Состав потока отличается. Обновите данные.")
            # Verify omitted fields survived a partial PUT.
            before = {k: v for k, v in stream.items() if k not in ("offers", "updated_at")}
            after = {k: v for k, v in actual.items() if k not in ("offers", "updated_at")}
            if before != after:
                raise AppError(
                    409, "settings_changed", "Настройки потока изменились. Проверьте состояние."
                )
            return await self.campaign(cid)

    @staticmethod
    def same_offers(actual, expected):
        fields = ("offer_id", "share", "state")
        return [{k: x.get(k) for k in fields} for x in actual] == expected

    def save(self, op, **changes):
        with self.sessions.begin() as session:
            row = session.get(CreationOperation, op.id)
            for key, value in changes.items():
                setattr(row, key, value)
                setattr(op, key, value)

    async def create(self, request_key, payload):
        request_hash = fingerprint(payload)
        async with self.operations_lock:
            with self.sessions() as session:
                op = session.scalar(
                    select(CreationOperation).where(CreationOperation.request_key == request_key)
                )
            if op and op.input_hash != request_hash:
                raise AppError(409, "key_conflict", "Этот ключ уже использован с другими данными.")
            if request_key in self.running:
                raise AppError(
                    409,
                    "operation_running",
                    "Операция уже выполняется.",
                    operation_id=op.id if op else None,
                )
            if op and op.stage == "complete":
                return {"campaign_id": op.campaign_id, "operation_id": op.id}, 200
            if not op:
                op = CreationOperation(
                    id=str(uuid4()),
                    request_key=request_key,
                    alias="wrapper-" + uuid4().hex,
                    input_hash=request_hash,
                    payload=payload,
                    stage="pending",
                )
                try:
                    with self.sessions.begin() as session:
                        session.add(op)
                except IntegrityError:
                    raise AppError(
                        409, "operation_running", "Операция уже зарегистрирована."
                    ) from None
            self.running.add(request_key)
        try:
            await self.validate_creation(payload)
            await self.run_creation(op)
            return {"campaign_id": op.campaign_id, "operation_id": op.id}, 201
        except AppError as error:
            self.save(op, last_error=error.payload["message"])
            error.payload.update(operation_id=op.id, campaign_id=op.campaign_id, stage=op.stage)
            raise
        finally:
            self.running.discard(request_key)

    async def validate_creation(self, payload):
        config = await self.configuration()
        for field, group in (
            ("domain_id", "domains"),
            ("group_id", "groups"),
            ("traffic_source_id", "sources"),
        ):
            if not any(int(x["id"]) == payload[field] for x in config[group]):
                raise AppError(
                    422,
                    "invalid_configuration",
                    "Выберите существующую запись справочника.",
                    field_errors={field: "Запись отсутствует в Keitaro"},
                )
        offers = await self.client.get("offers")
        if not any(int(o["id"]) == payload["offer_id"] for o in offers):
            raise AppError(
                422,
                "invalid_offer",
                "Выберите существующий оффер.",
                field_errors={"offer_id": "Оффер отсутствует в Keitaro"},
            )

    def stream_payload(self, op, geo):
        return {
            "campaign_id": op.campaign_id,
            "name": f"{op.alias}-{'geo' if geo else 'offers'}",
            "type": "regular",
            "schema": "redirect" if geo else "landings",
            "position": 1 if geo else 2,
            "state": "active",
            "action_type": "http",
            "action_payload": "https://www.google.com/" if geo else "",
            "filters": [
                {"name": "country", "mode": "accept", "payload": [op.payload["country_code"]]}
            ]
            if geo
            else [],
            "offers": []
            if geo
            else [{"offer_id": op.payload["offer_id"], "share": 100, "state": "active"}],
        }

    def ambiguous(self):
        return AppError(
            409,
            "ambiguous_operation",
            "Исход записи не установлен однозначно. Проверьте Keitaro и повторите проверку; "
            "новый запрос с другим ключом может создать дубликат.",
        )

    async def run_creation(self, op):
        if not op.campaign_id:
            if op.stage == "creating_campaign":
                matches = [
                    c for c in await self.client.get("campaigns") if c.get("alias") == op.alias
                ]
                if len(matches) != 1:
                    raise self.ambiguous()
                self.save(op, campaign_id=int(matches[0]["id"]), stage="campaign_created")
            else:
                self.save(op, stage="creating_campaign")
                p = op.payload
                campaign = await self.client.post(
                    "campaigns",
                    {
                        "name": p["name"],
                        "alias": op.alias,
                        "type": "position",
                        "state": "disabled",
                        "domain_id": p["domain_id"],
                        "group_id": str(p["group_id"]),
                        "traffic_source_id": p["traffic_source_id"],
                    },
                )
                self.save(op, campaign_id=int(campaign["id"]), stage="campaign_created")
        for geo, field, stage in (
            (True, "geo_stream_id", "creating_geo"),
            (False, "offer_stream_id", "creating_offers"),
        ):
            if getattr(op, field):
                continue
            body = self.stream_payload(op, geo)
            if op.stage == stage:
                rows = await self.client.get(f"campaigns/{op.campaign_id}/streams")
                matches = [s for s in rows if s.get("name") == body["name"]]
                if len(matches) != 1:
                    raise self.ambiguous()
                stream = matches[0]
            else:
                self.save(op, stage=stage)
                stream = await self.client.post("streams", body)
            self.save(op, **{field: int(stream["id"]), "stage": field + "_saved"})
        await self.verify_creation(op, require_active=False)
        self.save(op, stage="activating")
        await self.client.put(f"campaigns/{op.campaign_id}", {"state": "active"})
        await self.verify_creation(op, require_active=True)
        self.save(op, stage="complete", last_error=None)

    async def verify_creation(self, op, require_active):
        campaign = await self.client.get(f"campaigns/{op.campaign_id}")
        streams = await self.client.get(f"campaigns/{op.campaign_id}/streams")
        p = op.payload
        valid = campaign.get("type") == "position" and campaign.get("alias") == op.alias
        valid &= campaign.get("name") == p["name"]
        for key in ("domain_id", "group_id", "traffic_source_id"):
            valid &= str(campaign.get(key)) == str(p[key])
        if require_active:
            valid &= active(campaign.get("state"))
        valid &= len(streams) == 2
        for geo, sid in ((True, op.geo_stream_id), (False, op.offer_stream_id)):
            actual = next((s for s in streams if int(s["id"]) == sid), {})
            expected = self.stream_payload(op, geo)
            for key in ("type", "schema", "position", "state", "filters"):
                valid &= actual.get(key) == expected[key]
            if geo:
                valid &= actual.get("action_payload") == "https://www.google.com/"
                valid &= actual.get("action_type") == "http"
            else:
                valid &= self.same_offers(actual.get("offers", []), expected["offers"])
        if not valid:
            raise AppError(
                409, "verification_failed", "Настройки кампании не подтверждены. Проверьте Keitaro."
            )
