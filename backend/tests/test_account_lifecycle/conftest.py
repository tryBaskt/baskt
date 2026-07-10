import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv
from decimal import Decimal, InvalidOperation
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping, List
repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.repository.baskt_account_repository import BasktAccountRepository
from backend.clients.dynamodb_client import DynamoDBClient
from backend.domain.baskt_account_domain import (
    ContactData,
    DisclosuresData,
    IdentityData,
)

FUNDED_ALPACA_ACCOUNT_ID = "0bc4fb65-515c-41f7-a2ea-392ba5626c1e"
FUNDED_COGNITO_USER_ID = "f408a4e8-60f1-70d0-4c17-2377bf12babf"

load_dotenv()
os.environ["ENV"] = "dev"
get_settings.cache_clear()


def _assert_expected_fields(
    expected: Mapping[str, Any],
    actual: Any,
    *,
    path: str,
) -> None:
    """Assert that every submitted field has the same persisted value."""
    if is_dataclass(actual) and not isinstance(actual, type):
        actual_data = asdict(actual)
    elif hasattr(actual, "model_dump"):
        actual_data = actual.model_dump()
    elif hasattr(actual, "dict"):
        actual_data = actual.dict()
    else:
        actual_data = actual
    assert isinstance(actual_data, Mapping), f"{path} is not an object"

    for key, expected_value in expected.items():
        field_path = f"{path}.{key}"
        assert key in actual_data, f"Missing {field_path}"
        actual_value = actual_data[key]
        if isinstance(expected_value, Mapping):
            _assert_expected_fields(
                expected_value,
                actual_value,
                path=field_path,
            )
        elif isinstance(expected_value, (list, tuple)):
            expected_items = list(expected_value)
            actual_items = list(actual_value)
            assert isinstance(actual_items, list), f"{field_path} is not a list"
            assert len(actual_items) == len(expected_items), (
                f"{field_path} length differs: expected {len(expected_items)}, "
                f"received {len(actual_items)}"
            )
            for index, (expected_item, actual_item) in enumerate(
                zip(expected_items, actual_items)
            ):
                item_path = f"{field_path}[{index}]"
                if isinstance(expected_item, Mapping):
                    _assert_expected_fields(
                        expected_item,
                        actual_item,
                        path=item_path,
                    )
                else:
                    if isinstance(expected_item, Enum):
                        expected_item = expected_item.value
                    if isinstance(actual_item, Enum):
                        actual_item = actual_item.value
                    if isinstance(expected_item, (datetime, date)):
                        expected_item = expected_item.isoformat()
                    if isinstance(actual_item, (datetime, date)):
                        actual_item = actual_item.isoformat()
                    assert str(expected_item) == str(actual_item), (
                        f"{item_path} differs: expected {expected_item!r}, "
                        f"received {actual_item!r}"
                    )
        else:
            if isinstance(expected_value, Enum):
                expected_value = expected_value.value
            if isinstance(actual_value, Enum):
                actual_value = actual_value.value
            if isinstance(expected_value, (datetime, date)):
                expected_value = expected_value.isoformat()
            if isinstance(actual_value, (datetime, date)):
                actual_value = actual_value.isoformat()
            values_match = expected_value == actual_value
            if not values_match and not isinstance(
                expected_value,
                bool,
            ) and not isinstance(actual_value, bool):
                try:
                    values_match = Decimal(str(expected_value)) == Decimal(
                        str(actual_value)
                    )
                except (InvalidOperation, ValueError):
                    if isinstance(expected_value, str) and isinstance(
                        actual_value,
                        str,
                    ):
                        try:
                            expected_datetime = datetime.fromisoformat(
                                expected_value.replace("Z", "+00:00")
                            )
                            actual_datetime = datetime.fromisoformat(
                                actual_value.replace("Z", "+00:00")
                            )
                            values_match = expected_datetime == actual_datetime
                        except ValueError:
                            values_match = expected_value == actual_value
                    else:
                        values_match = str(expected_value) == str(actual_value)
            assert values_match, (
                f"{field_path} differs: expected {expected_value!r}, "
                f"received {actual_value!r}"
            )




#######################################
############### CLIENTS ###############
#######################################
@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()

@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

@pytest.fixture(scope="session")
def baskt_account_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_baskt_account_dynamodb_client()


#######################################
############# REPOSITORY ##############
#######################################
@pytest.fixture(scope="session")
def baskt_account_repository(
    baskt_account_dynamodb_client: DynamoDBClient,
) -> BasktAccountRepository:
    app_deps.get_baskt_account_dynamodb_client.cache_clear()
    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=baskt_account_dynamodb_client
    )


#######################################
############## SERVICES ###############
#######################################
    
@pytest.fixture(scope="session")
def account_lifecycle_service() -> AccountLifecycleService:
    app_deps.get_cognito_client.cache_clear()
    app_deps.get_alpaca_broker_client.cache_clear()

    cognito_client = app_deps.get_cognito_client()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    baskt_account_dynamodb_client = app_deps.get_baskt_account_dynamodb_client()
    baskt_account_repository = app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=baskt_account_dynamodb_client,
    )

    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        baskt_account_repository=baskt_account_repository,
    )

###########################################
############### TEST ENGINE ###############
###########################################

class TestEngine:
    def __init__(
        self,
        account_lifecycle_service: AccountLifecycleService,
        alpaca_broker_client: AlpacaBrokerClient,
        baskt_account_repository: BasktAccountRepository
    ):
        self.account_lifecycle_service = account_lifecycle_service
        self.alpaca_broker_client = alpaca_broker_client
        self.baskt_account_repository = baskt_account_repository

    def test_create_baskt_account(
        self,
        test_account_data,
        password
        ):
        create_account_response = (
            self.account_lifecycle_service.create_baskt_account(
                account_data=test_account_data,
                password=password,
            )
        )

        alpaca_account_id = create_account_response["alpaca_account_id"]
        cognito_user_id = create_account_response["cognito_user_id"]

        alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        assert str(alpaca_account.id) == str(alpaca_account_id)
        assert str(alpaca_account.account_number) == str(
            create_account_response["alpaca_account_number"]
        )
        _assert_expected_fields(
            test_account_data["contact"],
            alpaca_account.contact,
            path="alpaca.contact",
        )
        _assert_expected_fields(
            {
                key: value
                for key, value in test_account_data["identity"].items()
                if key != "tax_id"
            },
            alpaca_account.identity,
            path="alpaca.identity",
        )
        _assert_expected_fields(
            test_account_data["disclosures"],
            alpaca_account.disclosures,
            path="alpaca.disclosures",
        )
        _assert_expected_fields(
            {"agreements": test_account_data["agreements"]},
            {"agreements": alpaca_account.agreements},
            path="alpaca",
        )

        baskt_account = self.baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id
        )
        assert baskt_account.cognito_user_id == cognito_user_id
        assert baskt_account.alpaca_account_id == alpaca_account_id
        assert baskt_account.alpaca_account_number == create_account_response[
            "alpaca_account_number"
        ]
        assert baskt_account.display_name == test_account_data["display_name"]
        _assert_expected_fields(
            test_account_data["contact"],
            baskt_account.contact_data,
            path="dynamodb.contact_data",
        )
        _assert_expected_fields(
            {
                key: value
                for key, value in test_account_data["identity"].items()
                if key != "tax_id"
            },
            baskt_account.identity_data,
            path="dynamodb.identity_data",
        )
        raw_baskt_account = self.baskt_account_repository.dynamodb.get_item(
            key={"cognito_user_id": cognito_user_id}
        )
        assert "tax_id" not in raw_baskt_account["identity_data"]
        _assert_expected_fields(
            test_account_data["disclosures"],
            baskt_account.disclosures_data,
            path="dynamodb.disclosures_data",
        )
        _assert_expected_fields(
            {"agreements": test_account_data["agreements"]},
            {"agreements": baskt_account.agreements_data},
            path="dynamodb",
        )

        return create_account_response

    def test_update_identity_data(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        identity_data: IdentityData,
    ) -> None:
        """Update identity data and verify Alpaca and DynamoDB."""
        self.account_lifecycle_service.update_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            updated_data=identity_data,
        )

        alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        _assert_expected_fields(
            asdict(identity_data),
            alpaca_account.identity,
            path="alpaca.identity",
        )

        baskt_account = self.baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id
        )
        _assert_expected_fields(
            asdict(identity_data),
            baskt_account.identity_data,
            path="dynamodb.identity_data",
        )

    def test_update_contact_data(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        contact_data: ContactData,
    ) -> None:
        """Update contact data and verify Alpaca and DynamoDB."""
        self.account_lifecycle_service.update_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            updated_data=contact_data,
        )

        alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        _assert_expected_fields(
            asdict(contact_data),
            alpaca_account.contact,
            path="alpaca.contact",
        )

        baskt_account = self.baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id
        )
        _assert_expected_fields(
            asdict(contact_data),
            baskt_account.contact_data,
            path="dynamodb.contact_data",
        )

    def test_update_disclosures_data(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        disclosures_data: DisclosuresData,
    ) -> None:
        """Update disclosures and verify Alpaca and DynamoDB."""
        self.account_lifecycle_service.update_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            updated_data=disclosures_data,
        )

        alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        _assert_expected_fields(
            asdict(disclosures_data),
            alpaca_account.disclosures,
            path="alpaca.disclosures",
        )

        baskt_account = self.baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id
        )
        _assert_expected_fields(
            asdict(disclosures_data),
            baskt_account.disclosures_data,
            path="dynamodb.disclosures_data",
        )

    
    def test_create_direct_ach_relationship(
        self, 
        alpaca_account_id: str, 
        cognito_user_id: str,
        account_owner_name: str,
        bank_account_type: str,
        bank_account_number: str,
        bank_routing_number: str,
        nickname: str
    ):

        ach_relationship = self.account_lifecycle_service.create_direct_ach_relationship(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            account_owner_name=account_owner_name,
            bank_account_type=bank_account_type,
            bank_account_number=bank_account_number,
            bank_routing_number=bank_routing_number,
            nickname=nickname
        )

        assert ach_relationship is not None
        assert ach_relationship.status.name.upper() in ["QUEUED", "APPROVED"]
        assert str(ach_relationship.account_id) == alpaca_account_id
        assert ach_relationship.account_owner_name.upper() == account_owner_name.upper()
        assert ach_relationship.bank_account_type.name.upper() == "checking".upper()
        assert ach_relationship.bank_account_number == bank_account_number
        assert ach_relationship.bank_routing_number == bank_routing_number

        return ach_relationship
    

    
    def test_get_ach_relationships(self, alpaca_account_id: str, cognito_user_id: str):
        ach_relationships = self.account_lifecycle_service.get_ach_relationships(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
        return ach_relationships
    
    def test_delete_ach_relationship(
        self,
        alpaca_account_id: str,
        cognito_user_id: str,
        ach_relationship_id: str
    ):
        self.account_lifecycle_service.delete_ach_relationship(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            ach_relationship_id=ach_relationship_id
        )
        relationships_after_delete = self.account_lifecycle_service.get_ach_relationships(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        )
        assert all(
            str(relationship.id) != ach_relationship_id
            for relationship in relationships_after_delete
        )
    
    def test_create_ach_transfer(
        self, 
        alpaca_account_id: str, 
        cognito_user_id: str, 
        amount: str,
        direction: str,
        timing: str,
        fee_payment_method: str,
        relationship_id: str
    ):

        transfer = self.account_lifecycle_service.create_ach_transfer(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            amount=amount,
            direction=direction,
            timing=timing,
            fee_payment_method=fee_payment_method,
            relationship_id=relationship_id
        )

        assert str(transfer.account_id) == alpaca_account_id
        assert str(transfer.relationship_id).upper() == relationship_id.upper()
        assert Decimal(str(transfer.amount)) == Decimal(str(amount))
        assert transfer.type.name.upper() == "ACH"
        assert transfer.direction.name.upper() == direction.upper()
        assert transfer.fee_payment_method.name.upper() == fee_payment_method.upper()

        return transfer
    
    def _clean_up_baskt_account(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str
    ):
        try:
            self.account_lifecycle_service.permanently_close_baskt_account(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id
            )
        except Exception as err:
            print(err)
        


    def _clean_up_achs_banks_baskt_account(
        self,
        alpaca_account_id: str,
        cognito_user_id: str,
    ):
        try:
            transfers = self.account_lifecycle_service.get_transfers(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            )
            cancelable_statuses = {"QUEUED", "APPROVAL_PENDING", "PENDING"}
            for transfer in transfers:
                status = str(getattr(transfer.status, "name", transfer.status)).upper()
                if status in cancelable_statuses:
                    self.account_lifecycle_service.cancel_transfer(
                        cognito_user_id=cognito_user_id,
                        alpaca_account_id=alpaca_account_id,
                        transfer_id=str(transfer.id),
                    )
        except Exception as err:
            print(err)

        try:
            ach_relationships = self.account_lifecycle_service.get_ach_relationships(
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            )
        except Exception as err:
            print(err)

        try:
            for ach_relationship in ach_relationships:
                self.account_lifecycle_service.delete_ach_relationship(
                    alpaca_account_id=alpaca_account_id,
                    cognito_user_id=cognito_user_id,
                    ach_relationship_id=str(ach_relationship.id),
                )
        except Exception as err:
            print(err)

        self._clean_up_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id
        )

   





    

    
    
    
    
@pytest.fixture(scope="session")
def test_engine(
    account_lifecycle_service: AccountLifecycleService,
    alpaca_broker_client: AlpacaBrokerClient,
    baskt_account_repository: BasktAccountRepository,
) -> TestEngine:
    return TestEngine(
        account_lifecycle_service=account_lifecycle_service,
        alpaca_broker_client=alpaca_broker_client,
        baskt_account_repository=baskt_account_repository,
    )
