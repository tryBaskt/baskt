from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_201_CREATED, HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

from core.deps import get_account_lifecycle_service, get_current_active_alpaca_account, get_current_user
from schema.account_lifecycle_request import (
	CreateACHRelationshipRequest,
	CreateAccountLifecycleRequest,
)
from services.account_lifecycle_service import AccountLifecycleService, AccountLifecycleServiceError


router = APIRouter(prefix="/accounts", tags=["accounts"])


def _to_response_dict(value: Any) -> Dict[str, Any]:
	if isinstance(value, dict):
		return value
	if hasattr(value, "model_dump"):
		return value.model_dump()
	if hasattr(value, "dict"):
		return value.dict()
	return {"result": value}


def _raise_account_lifecycle_http_exception(err: Exception) -> None:
	if isinstance(err, HTTPException):
		raise err

	if isinstance(err, AccountLifecycleServiceError):
		raise HTTPException(status_code=HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err)) from err

	raise HTTPException(
		status_code=HTTP_500_INTERNAL_SERVER_ERROR,
		detail=f"Unexpected account lifecycle error: {err}",
	) from err


@router.post("/create-baskt-account", status_code=HTTP_201_CREATED)
def create_baskt_account(
	request: CreateAccountLifecycleRequest,
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, str]:
	try:
		payload = request.model_dump(exclude_none=True)
		password = payload.pop("password", None)
		result = service.create_baskt_account(account_data=payload, password=password)
		return result

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.post("/create-ach-relationships", status_code=HTTP_201_CREATED)
def create_ach_relationship(
	request: CreateACHRelationshipRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	alpaca_account_id = str(alpaca_account.id)
	cognito_user_id = user["sub"]
	try:
		ach_relationship = service.create_ach_relationship(
			alpaca_account_id=alpaca_account_id,
			cognito_user_id=cognito_user_id,
			account_owner_name=request.bank_account_owner_name,
			bank_account_type=request.bank_account_type,
			bank_account_number=request.bank_account_number,
			bank_routing_number=request.bank_account_routing_number,
			nickname=request.bank_account_nickname,
		)
		return _to_response_dict(ach_relationship)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/ach-relationships", status_code=HTTP_201_CREATED)
def get_ach_relationships(
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> List[Dict[str, Any]]:
	try:
		alpaca_account_id = str(alpaca_account.id)
		return service.get_ach_relationship(alpaca_account_id=alpaca_account_id)

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)

