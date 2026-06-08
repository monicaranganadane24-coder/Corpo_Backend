from pydantic import BaseModel

class PlayerCreate(BaseModel):
    pseudo: str
    email: str
