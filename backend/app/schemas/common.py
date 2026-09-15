from pydantic import BaseModel, ConfigDict
from datetime import datetime

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class Message(BaseModel):
    message: str