from pydantic import BaseModel, ConfigDict


class ErrorResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str = "error"
    status_code: int
    error_code: str
    message: str
    detail: str | None = None
