from fastapi import APIRouter

router = APIRouter(


@router.get("/broken")
def broken(:
    return {}