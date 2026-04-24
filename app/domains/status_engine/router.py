from fastapi import APIRouter

from app.domains.status_engine.schemas import StatusEngineArtifact
from app.domains.status_engine.service import status_engine_service


router = APIRouter()


@router.get("/{version}", response_model=StatusEngineArtifact)
def get_status_engine(version: str) -> StatusEngineArtifact:
    return status_engine_service.get_engine(version)


@router.put("/{version}", response_model=StatusEngineArtifact)
def save_status_engine(version: str, artifact: StatusEngineArtifact) -> StatusEngineArtifact:
    return status_engine_service.save_engine(version, artifact)


@router.delete("/{version}")
def delete_status_engine(version: str) -> dict[str, str]:
    status_engine_service.delete_engine(version)
    return {"status": "deleted"}
