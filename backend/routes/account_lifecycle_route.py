# backend/routes/

# Python imports
from __future__ import annotations
from typing import Any, Dict

# Fast api Imports
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_403_FORBIDDEN, HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

# Baskt Imports
from core.deps import get_account_lifecycle_service, get_current_active_alpaca_account, get_current_user
from schema.account_lifecycle_schema import (
	CreateBasktACHRelationshipRequest,
	CreateBasktAccountLifecycleRequest,
	CreateBasktBankRequest,
	CreateBasktPlaidRelationshipRequest,
	CreateBasktTransferRequest,
	BasktTradeAccountResponse,
	BasktACHRelationshipResponse,
	BasktListACHRelationshipResponse,
	BasktBankResponse,
	BasktListBankResponse,
	BasktOneTransferResponse,
	BasktTransferResponse
)
from services.account_lifecycle_service import AccountLifecycleService, AccountLifecycleServiceBasktAccountDisabled, AccountLifecycleServiceError

# Alpaca imports
from alpaca.broker.models import ACHRelationship, Bank, Transfer, TradeAccount


router = APIRouter(prefix="/accounts", tags=["accounts"])


def _raise_account_lifecycle_http_exception(err: Exception) -> None:
	"""
	Convert account lifecycle exceptions into FastAPI HTTP exceptions.
	"""
	if isinstance(err, AccountLifecycleServiceError):
		if isinstance(err, AccountLifecycleServiceBasktAccountDisabled):
			status_code = HTTP_403_FORBIDDEN
		elif "UNSUPPORTED" in err.code:
			status_code = HTTP_422_UNPROCESSABLE_CONTENT
		else:
			status_code = HTTP_500_INTERNAL_SERVER_ERROR
		raise HTTPException(
			status_code=status_code,
			detail={"message": str(err), "code": err.code},
		) from err
	raise HTTPException(
		status_code=HTTP_500_INTERNAL_SERVER_ERROR,
		detail={"message": str(err), "code": "ACCOUNT_LIFECYCLE_UNEXPECTED_ERROR"},
	) from err


def _to_optional_str(value: Any) -> str | None:
	"""
	Convert an optional SDK value or enum value into a string.
	"""
	if value is None:
		return None
	return str(getattr(value, "value", value))


def _to_enum_name(value: Any) -> str:
	"""
	Convert an SDK enum-like value into its uppercase enum name.
	"""
	return str(getattr(value, "name", value)).upper()


def _to_trade_account_response(trade_account: TradeAccount) -> BasktTradeAccountResponse:
	"""
	Convert an Alpaca trade account model into the API response schema.
	"""
	return BasktTradeAccountResponse(
		cash_withdrawable=_to_optional_str(getattr(trade_account, "cash_withdrawable", None)),
		cash_transferable=_to_optional_str(getattr(trade_account, "cash_transferable", None)),
		previous_close=_to_optional_str(getattr(trade_account, "previous_close", None)),
		last_long_market_value=_to_optional_str(getattr(trade_account, "last_long_market_value", None)),
		last_short_market_value=_to_optional_str(getattr(trade_account, "last_short_market_value", None)),
		last_cash=_to_optional_str(getattr(trade_account, "last_cash", None)),
		last_initial_margin=_to_optional_str(getattr(trade_account, "last_initial_margin", None)),
		last_regt_buying_power=_to_optional_str(getattr(trade_account, "last_regt_buying_power", None)),
		last_daytrading_buying_power=_to_optional_str(getattr(trade_account, "last_daytrading_buying_power", None)),
		last_daytrade_count=_to_optional_str(getattr(trade_account, "last_daytrade_count", None)),
		last_buying_power=_to_optional_str(getattr(trade_account, "last_buying_power", None)),
		clearing_broker=_to_enum_name(trade_account.clearing_broker) if getattr(trade_account, "clearing_broker", None) else None,
	)


def _to_ach_relationship_response(alpaca_account_id: str, ach_relationship: ACHRelationship) -> BasktACHRelationshipResponse:
	"""
	Convert an Alpaca ACH relationship model into the API response schema.
	"""
	return BasktACHRelationshipResponse(
		relationship_id=str(ach_relationship.id),
		alpaca_account_id=alpaca_account_id,
		created_at=ach_relationship.created_at.isoformat(),
		updated_at=ach_relationship.updated_at.isoformat() if ach_relationship.updated_at else None,
		status=_to_enum_name(ach_relationship.status),
		account_owner_name=ach_relationship.account_owner_name,
		bank_account_type=_to_enum_name(ach_relationship.bank_account_type),
		bank_account_number=ach_relationship.bank_account_number,
		bank_routing_number=ach_relationship.bank_routing_number,
		nickname=getattr(ach_relationship, "nickname", None),
		processor_token=getattr(ach_relationship, "processor_token", None),
	)


def _to_bank_response(alpaca_account_id: str, bank: Bank) -> BasktBankResponse:
	"""
	Convert an Alpaca bank model into the API response schema.
	"""
	return BasktBankResponse(
		bank_id=str(bank.id),
		alpaca_account_id=alpaca_account_id,
		created_at=bank.created_at.isoformat(),
		updated_at=bank.updated_at.isoformat() if bank.updated_at else None,
		name=bank.name,
		status=_to_enum_name(bank.status),
		country=_to_optional_str(bank.country),
		state_province=_to_optional_str(bank.state_province),
		postal_code=_to_optional_str(bank.postal_code),
		city=_to_optional_str(bank.city),
		street_address=_to_optional_str(bank.street_address),
		alpaca_account_number=bank.account_number,
		bank_code=bank.bank_code,
		bank_code_type=_to_enum_name(bank.bank_code_type),
	)


def _to_transfer_response(alpaca_account_id: str, transfer: Transfer) -> BasktOneTransferResponse:
	"""
	Convert an Alpaca transfer model into the API response schema.
	"""
	return BasktOneTransferResponse(
		alpaca_account_id=alpaca_account_id,
		created_at=transfer.created_at.isoformat(),
		updated_at=transfer.updated_at.isoformat() if transfer.updated_at else None,
		expires_at=transfer.expires_at.isoformat() if transfer.expires_at else None,
		relationship_id=str(transfer.relationship_id) if transfer.relationship_id else None,
		bank_id=str(transfer.bank_id) if transfer.bank_id else None,
		amount=str(transfer.amount),
		type=_to_enum_name(transfer.type),
		status=_to_enum_name(transfer.status),
		direction=_to_enum_name(transfer.direction),
		reason=_to_optional_str(transfer.reason),
		requested_amount=_to_optional_str(transfer.requested_amount),
		fee=_to_optional_str(transfer.fee),
		fee_payment_method=_to_enum_name(transfer.fee_payment_method) if transfer.fee_payment_method else None,
		additional_information=_to_optional_str(getattr(transfer, "additional_information", None)),
	)


@router.post("/create-baskt-account", response_model=None, status_code=HTTP_201_CREATED)
def create_baskt_account(
	request: CreateBasktAccountLifecycleRequest,
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> None:
	"""
	Create an Alpaca account and matching Cognito user.
	"""
	try:
		payload = request.model_dump(exclude_none=True)
		password = payload.pop("password", None)
		service.create_baskt_account(account_data=payload, password=password)
		return 
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)

@router.get("/trade-account", response_model=BasktTradeAccountResponse, status_code=HTTP_200_OK)
def get_trade_account(
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service)
) -> BasktTradeAccountResponse:
	"""
	Get the authenticated user's Alpaca trade account details.
	"""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		trade_account = service.get_trade_account(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
		return _to_trade_account_response(trade_account)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.post("/ach-relationship", response_model=None, status_code=HTTP_201_CREATED)
def create_ach_relationship(
	request: CreateBasktACHRelationshipRequest | CreateBasktPlaidRelationshipRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> None:
	"""
	Create a direct or Plaid ACH relationship for the authenticated account.
	"""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		if isinstance(request, CreateBasktPlaidRelationshipRequest):
			service.create_plaid_ach_relationship(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				processor_token=request.processor_token,
			)
			return
		
		service.create_direct_ach_relationship(
			alpaca_account_id=alpaca_account_id,
			cognito_user_id=cognito_user_id,
			account_owner_name=request.account_owner_name,
			bank_account_type=request.bank_account_type,
			bank_account_number=request.bank_account_number,
			bank_routing_number=request.bank_routing_number,
			nickname=request.nickname,
		)
		return
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.put("/ach-relationship", response_model=None, status_code=HTTP_201_CREATED)
def update_ach_relationship(
	request: CreateBasktACHRelationshipRequest | CreateBasktPlaidRelationshipRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> None:
	"""
	Replace the authenticated account's current ACH relationship.
	"""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		ach_relationships = service.get_ach_relationships(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
		service.delete_ach_relationship(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, ach_relationship_id=str(ach_relationships[0].id))

		if isinstance(request, CreateBasktPlaidRelationshipRequest):
			service.create_plaid_ach_relationship(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				processor_token=request.processor_token,
			)
			return 
		
		service.create_direct_ach_relationship(
			alpaca_account_id=alpaca_account_id,
			cognito_user_id=cognito_user_id,
			account_owner_name=request.account_owner_name,
			bank_account_type=request.bank_account_type,
			bank_account_number=request.bank_account_number,
			bank_routing_number=request.bank_routing_number,
			nickname=request.nickname,
		)
		return

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/ach-relationships", response_model=BasktListACHRelationshipResponse, status_code=HTTP_200_OK)
def get_ach_relationships(
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> BasktListACHRelationshipResponse:
	"""
	List ACH relationships for the authenticated account.
	"""
	try:
		cognito_user_id: str = user["sub"]
		alpaca_account_id: str = user["custom:alpaca_acct_id"]
		ach_relationships = service.get_ach_relationships(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
		)

		return BasktListACHRelationshipResponse(
			list_ach_relationship=[
				_to_ach_relationship_response(alpaca_account_id, ach_relationship)
				for ach_relationship in ach_relationships
			]
		)

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)



@router.post("/bank", response_model=None, status_code=HTTP_201_CREATED)
def create_bank(
	request: CreateBasktBankRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> None:
	"""
	Create a bank relationship for the authenticated account.
	"""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		service.create_bank(
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
		return
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.put("/bank", response_model=None, status_code=HTTP_201_CREATED)
def update_bank(
	request: CreateBasktBankRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> None:
	"""
	Replace the authenticated account's current bank relationship.
	"""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		banks = service.get_banks(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
		service.delete_bank(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, bank_id=str(banks[0].id))
		service.create_bank(
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
		return 
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/banks", response_model=BasktListBankResponse, status_code=HTTP_200_OK)
def get_banks(
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> BasktListBankResponse:
	"""
	List bank relationships for the authenticated account.
	"""
	try:
		cognito_user_id: str = user["sub"]
		alpaca_account_id: str = user["custom:alpaca_acct_id"]
		banks = service.get_banks(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
		)

		return BasktListBankResponse(
			list_banks=[_to_bank_response(alpaca_account_id, bank) for bank in banks]
		)

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)


@router.get("/transfers", response_model=BasktTransferResponse, status_code=HTTP_200_OK)
def get_transfers(
	limit: int = Query(default=10, ge=1, le=100),
	offset: int = Query(default=0, ge=0),
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> BasktTransferResponse:
	"""
	List transfers for the authenticated account with pagination metadata.
	"""
	try:
		cognito_user_id = user["sub"]
		alpaca_account_id = user["custom:alpaca_acct_id"]
		transfers = service.get_transfers(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			limit=limit,
			offset=offset,
		)
		transfer_items = [_to_transfer_response(alpaca_account_id, transfer) for transfer in transfers]
		return BasktTransferResponse(
			items=transfer_items,
			limit=limit,
			offset=offset,
			has_next=len(transfer_items) == limit,
			has_previous=offset > 0,
		)

	except Exception as err:
		_raise_account_lifecycle_http_exception(err)



@router.post("/transfer", response_model=None, status_code=HTTP_201_CREATED)
def create_transfer(
	request: CreateBasktTransferRequest,
	user: Dict[str, Any] = Depends(get_current_user),
	alpaca_account: Any = Depends(get_current_active_alpaca_account),
	service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> None:
	"""
	Create an ACH or bank transfer for the authenticated account.
	"""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		if request.funding_source_type.upper() == "ACH":
			service.create_ach_transfer(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				amount=request.amount,
				direction=request.direction,
				timing=request.timing,
				relationship_id=request.relationship_id,
				fee_payment_method=request.fee_payment_method,
			)
			return

		if request.funding_source_type.upper() == "BANK":
			service.create_bank_transfer(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				amount=request.amount,
				direction=request.direction,
				timing=request.timing,
				bank_id=request.bank_id,
				fee_payment_method=request.fee_payment_method,
				additional_information=request.additional_information,
			)
			return

		raise AccountLifecycleServiceError(
			message=f"Unsupported funding source type '{request.funding_source_type}'",
			code="ACCOUNT_LIFECYCLE_UNSUPPORTED_TRANSFER_SOURCE",
		)
	except Exception as err:
		_raise_account_lifecycle_http_exception(err)
