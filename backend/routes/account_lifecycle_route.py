from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_201_CREATED, HTTP_422_UNPROCESSABLE_ENTITY, HTTP_500_INTERNAL_SERVER_ERROR

from core.deps import get_account_lifecycle_service
from schema.account_lifecycle_request import (
	CreateAccountLifecycleRequest,
	CreateAccountLifecycleResponse,
)
from services.account_lifecycle_service import AccountLifecycleService, AccountLifecycleServiceError


router = APIRouter(prefix="/account-lifecycle", tags=["account-lifecycle"])


@router.post("/signup", response_model=CreateAccountLifecycleResponse, status_code=HTTP_201_CREATED)
def create_account_lifecycle(
	request: CreateAccountLifecycleRequest,
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> CreateAccountLifecycleResponse:
	try:
		payload = request.model_dump(exclude_none=True)
		password = payload.pop("password", None)
		result = service.create_account_lifecycle(account_data=payload, password=password)
		return CreateAccountLifecycleResponse(
			alpaca_account_id=result["alpaca_account_id"],
			cognito_username=result["cognito_username"]
        )
	except AccountLifecycleServiceError as err:
		raise HTTPException(status_code=HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err)) from err
	except Exception as err:
		raise HTTPException(
			status_code=HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Unexpected account lifecycle error: {err}",
		) from err
