import gettext
from typing import Annotated

import pycountry
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.errors import AppError

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
translation = gettext.translation(
    "iso3166-1", pycountry.LOCALES_DIR, languages=["ru"], fallback=True
)
COUNTRIES = sorted(
    [{"id": c.alpha_2, "name": translation.gettext(c.name)} for c in pycountry.countries],
    key=lambda c: c["name"],
)


class CreateCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    country_code: str
    offer_id: int = Field(gt=0)
    domain_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)
    traffic_source_id: int | None = Field(default=None, gt=0)

    @field_validator("country_code")
    @classmethod
    def country(cls, value):
        code = value.upper()
        if not pycountry.countries.get(alpha_2=code):
            raise ValueError("Выберите существующий код страны ISO 3166-1 alpha-2")
        return code


class AddOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: int = Field(gt=0)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/")
@router.get("/campaigns/{cid}/edit")
async def page(request: Request, cid: int | None = None):
    return templates.TemplateResponse(request=request, name="index.html", context={"cid": cid})


@router.get("/api/countries")
async def countries(q: str = ""):
    q = q.casefold().strip()
    return {"items": [c for c in COUNTRIES if q in c["id"].lower() or q in c["name"].lower()]}


@router.get("/api/configuration")
async def configuration(request: Request):
    return await request.app.state.service.configuration()


@router.get("/api/offers")
async def offers(request: Request, q: str = ""):
    return {"items": await request.app.state.service.catalog("offers", q)}


@router.get("/api/campaigns")
async def campaigns(request: Request, q: str = ""):
    return {"items": await request.app.state.service.catalog("campaigns", q)}


@router.get("/api/campaigns/{cid}")
async def campaign(request: Request, cid: int):
    return await request.app.state.service.campaign(cid)


@router.post("/api/campaigns")
async def create(
    request: Request,
    data: CreateCampaign,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
):
    payload = data.model_dump()
    for field in ("domain_id", "group_id", "traffic_source_id"):
        if payload[field] is None:
            default = getattr(request.app.state.settings, "keitaro_" + field)
            if not default.isdigit() or int(default) <= 0:
                raise AppError(
                    422,
                    "configuration",
                    "Выберите домен, группу и источник.",
                    field_errors={field: "Выберите значение"},
                )
            payload[field] = int(default)
    result, status = await request.app.state.service.create(idempotency_key, payload)
    return JSONResponse(result, status_code=status)


@router.post("/api/campaigns/{cid}/streams/{sid}/offers")
async def add(request: Request, cid: int, sid: int, data: AddOffer):
    return await request.app.state.service.edit(cid, sid, data.offer_id, data.revision)


@router.delete("/api/campaigns/{cid}/streams/{sid}/offers/{oid}")
async def remove(
    request: Request,
    cid: int,
    sid: int,
    oid: int,
    if_match: Annotated[str, Header(pattern=r'^"[a-f0-9]{64}"$')],
):
    return await request.app.state.service.edit(cid, sid, oid, if_match[1:-1], remove=True)
