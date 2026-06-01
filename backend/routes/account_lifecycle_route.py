from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_201_CREATED, HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

from core.deps import get_account_lifecycle_service
from schema.account_lifecycle_request import (
	CreateAccountLifecycleRequest,
	CreateAccountLifecycleResponse,
)
from services.account_lifecycle_service import AccountLifecycleService, AccountLifecycleServiceError


router = APIRouter(prefix="/accounts", tags=["accounts"])


def _raise_account_lifecycle_http_exception(err: Exception) -> None:
	if isinstance(err, HTTPException):
		raise err

	if isinstance(err, AccountLifecycleServiceError):
		raise HTTPException(status_code=HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err)) from err

	raise HTTPException(
		status_code=HTTP_500_INTERNAL_SERVER_ERROR,
		detail=f"Unexpected account lifecycle error: {err}",
	) from err


@router.post("", response_model=CreateAccountLifecycleResponse, status_code=HTTP_201_CREATED)
def create_baskt_account(
	request: CreateAccountLifecycleRequest,
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> CreateAccountLifecycleResponse:
	try:
		payload = request.model_dump(exclude_none=True)
		password = payload.pop("password", None)
		result = service.create_baskt_account(account_data=payload, password=password)
		return CreateAccountLifecycleResponse(
			alpaca_account_id=result["alpaca_account_id"],
			cognito_username=result["cognito_user_id"]
        )
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)
