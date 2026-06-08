from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

from core.deps import get_account_lifecycle_service, get_current_active_alpaca_account, get_current_user
from schema.account_lifecycle_request import (
	CreateBasktACHRelationshipRequest,
	CreateBasktAccountLifecycleRequest,
	CreateBasktBankRequest,
	CreateBasktPlaidRelationshipRequest,
	CreateBasktTransferRequest
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
	request: CreateBasktAccountLifecycleRequest,
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, str]:
	try:
		payload = request.model_dump(exclude_none=True)
		password = payload.pop("password", None)
		result = service.create_baskt_account(account_data=payload, password=password)
		return result

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)

@router.get("/trade-account", status_code=HTTP_200_OK)
def get_trade_account(
	user: Any = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service)
) -> Dict[str, Any]:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		trade_account = service.get_trade_account(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
		return _to_response_dict(trade_account)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.post("/ach-relationship", status_code=HTTP_201_CREATED)
def create_ach_relationship(
	request: CreateBasktACHRelationshipRequest | CreateBasktPlaidRelationshipRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		if isinstance(request, CreateBasktPlaidRelationshipRequest):
			ach_relationship = service.create_plaid_ach_relationship(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				processor_token=request.processor_token,
			)
			return _to_response_dict(ach_relationship)
		
		ach_relationship = service.create_direct_ach_relationship(
			alpaca_account_id=alpaca_account_id,
			cognito_user_id=cognito_user_id,
			account_owner_name=request.account_owner_name,
			bank_account_type=request.bank_account_type,
			bank_account_number=request.bank_account_number,
			bank_routing_number=request.bank_routing_number,
			nickname=request.nickname,
		)
		return _to_response_dict(ach_relationship)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.put("/ach-relationship", status_code=HTTP_201_CREATED)
def update_ach_relationship(
	request: CreateBasktACHRelationshipRequest | CreateBasktPlaidRelationshipRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		ach_relationships = service.get_ach_relationships(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
		service.delete_ach_relationship(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, ach_relationship_id=str(ach_relationships[0].id))
		if isinstance(request, CreateBasktPlaidRelationshipRequest):
			ach_relationship = service.create_plaid_ach_relationship(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				processor_token=request.processor_token,
			)
			return _to_response_dict(ach_relationship)
		
		ach_relationship = service.create_direct_ach_relationship(
			alpaca_account_id=alpaca_account_id,
			cognito_user_id=cognito_user_id,
			account_owner_name=request.account_owner_name,
			bank_account_type=request.bank_account_type,
			bank_account_number=request.bank_account_number,
			bank_routing_number=request.bank_routing_number,
			nickname=request.nickname,
		)
		return _to_response_dict(ach_relationship)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/ach-relationships", status_code=HTTP_200_OK)
def get_ach_relationships(
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> List[Dict[str, Any]]:
	try:
		cognito_user_id = user["sub"]
		alpaca_account_id = user["custom:alpaca_acct_id"]
		ach_relationships = service.get_ach_relationships(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
		)
		return [_to_response_dict(ach_relationship) for ach_relationship in ach_relationships]

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)





@router.post("/bank", status_code=HTTP_201_CREATED)
def create_bank(
	request: CreateBasktBankRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		bank = service.create_bank(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			name=request.name,
			bank_code_type=request.bank_code_type,
			bank_code=request.bank_code,
			account_number=request.account_number,
			country=request.country,
			state_province=request.state_province,
			postal_code=request.postal_code,
			city=request.city,
			street_address=request.street_address,
		)
		return _to_response_dict(bank)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.put("/bank", status_code=HTTP_201_CREATED)
def update_bank(
	request: CreateBasktBankRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		banks = service.get_banks(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
		service.delete_bank(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, bank_id=str(banks[0].id))
		bank = service.create_bank(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			name=request.name,
			bank_code_type=request.bank_code_type,
			bank_code=request.bank_code,
			account_number=request.account_number,
			country=request.country,
			state_province=request.state_province,
			postal_code=request.postal_code,
			city=request.city,
			street_address=request.street_address,
		)
		return _to_response_dict(bank)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.post("/transfer", status_code=HTTP_201_CREATED)
def create_transfer(
	request: CreateBasktTransferRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		if request.funding_source_type.upper() == "ACH":
			transfer = service.create_ach_transfer(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				amount=request.amount,
				direction=request.direction,
				timing=request.timing,
				relationship_id=request.relationship_id,
				fee_payment_method=request.fee_payment_method,
			)
			return _to_response_dict(transfer)

		if request.funding_source_type.upper() == "BANK":
			transfer = service.create_bank_transfer(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				amount=request.amount,
				direction=request.direction,
				timing=request.timing,
				bank_id=request.bank_id,
				fee_payment_method=request.fee_payment_method,
			)
			return _to_response_dict(transfer)

		raise AccountLifecycleServiceError(
			message=f"Unsupported funding source type '{request.funding_source_type}'",
			code="ACCOUNT_LIFECYCLE_UNSUPPORTED_TRANSFER_SOURCE",
		)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/banks", status_code=HTTP_200_OK)
def get_banks(
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> List[Dict[str, Any]]:
	try:
		cognito_user_id = user["sub"]
		alpaca_account_id = user["custom:alpaca_acct_id"]
		banks = service.get_banks(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
		)
		return [_to_response_dict(bank) for bank in banks]

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/transfers", status_code=HTTP_200_OK)
def get_transfers(
	limit: int = Query(default=10, ge=1, le=100),
	offset: int = Query(default=0, ge=0),
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> Dict[str, Any]:
	try:
		cognito_user_id = user["sub"]
		alpaca_account_id = user["custom:alpaca_acct_id"]
		transfers = service.get_transfers(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			limit=limit,
			offset=offset,
		)
		transfer_items = [_to_response_dict(transfer) for transfer in transfers]
		return {
			"items": transfer_items,
			"limit": limit,
			"offset": offset,
			"has_next": len(transfer_items) == limit,
			"has_previous": offset > 0,
		}

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)
