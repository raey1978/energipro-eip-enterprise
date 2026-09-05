"""
EnergiPro – License status route.
Deliberately unauthenticated: the frontend needs to know whether the
instance is locked BEFORE a user can even log in, and a trial client has no
account to authenticate with in the first place.
"""
from fastapi import APIRouter

from core.license import check_license

router = APIRouter()


@router.get("")
@router.get("/status")
async def license_status():
    return check_license()
