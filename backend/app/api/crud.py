from typing import Type, TypeVar
from fastapi import HTTPException
from sqlalchemy.orm import Session

T = TypeVar("T")

def get_or_404(db: Session, model: Type[T], object_id: int) -> T:
    obj = db.get(model, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return obj