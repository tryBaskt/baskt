import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv
from decimal import Decimal
from dataclasses import asdict
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.domain.baskt import BasktAccount
from alpaca.broker.enums import (
    AgreementType,
    BankAccountType,
    EmploymentStatus,
    FundingSource,
    TaxIdType,
    TransferDirection,
    TransferTiming,
)
from time import sleep
import uuid
from datetime import datetime, timezone

load_dotenv()
os.environ["ENV"] = "dev"
get_settings.cache_clear()


def _response_value(response, key: str):
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)

#######################################
############### CLIENTS ###############
#######################################
@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()

@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

#######################################
############## SERVICES ###############
#######################################
    
@pytest.fixture(scope="session")
def account_lifecycle_service() -> AccountLifecycleService:
    app_deps.get_cognito_client.cache_clear()
    app_deps.get_alpaca_broker_client.cache_clear()

    cognito_client = app_deps.get_cognito_client()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()

    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
    )

###########################################
############### TEST ENGINE ###############
###########################################

class TestEngine:
    def __init__(
        self,
        account_lifecycle_service: AccountLifecycleService,
        alpaca_broker_client: AlpacaBrokerClient,
    ):
        self.account_lifecycle_service = account_lifecycle_service
        self.alpaca_broker_client = alpaca_broker_client

    def test_create_baskt_account(self):
        unique_suffix = uuid.uuid4().hex[:8]
        signed_at = datetime.now(timezone.utc).isoformat()

        account_data = {
            "contact": {
                "email_address": f"baskt_testuser_{unique_suffix}@example.com",
                "phone_number": "+15555551234",
                "street_address": ["123 Market St"],
                "unit": "9A",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "country": "USA",
            },
            "identity": {
                "given_name": "Jane",
                "middle_name": "Q",
                "family_name": "Tester",
                "date_of_birth": "1990-01-01",
                "tax_id": "999-99-1234",
                "tax_id_type": TaxIdType.USA_SSN,
                "country_of_citizenship": "USA",
                "country_of_birth": "USA",
                "country_of_tax_residence": "USA",
                "funding_source": [FundingSource.EMPLOYMENT_INCOME, FundingSource.SAVINGS],
                "annual_income_min": 50000,
                "annual_income_max": 120000,
                "liquid_net_worth_min": 10000,
                "liquid_net_worth_max": 50000,
                "total_net_worth_min": 50000,
                "total_net_worth_max": 200000,
            },
            "disclosures": {
                "is_control_person": False,
                "is_affiliated_exchange_or_finra": False,
                "is_politically_exposed": False,
                "immediate_family_exposed": False,
                "employment_status": EmploymentStatus.EMPLOYED,
                "employer_name": "JPMorgan Chase & Co.",
                "employer_address": "880 Powder Mill Rd, Wilmington, DE 19803",
                "employment_position": "Software Engineer"

            },
            "agreements": [
                {
                    "agreement": AgreementType.ACCOUNT,
                    "signed_at": signed_at,
                    "ip_address": "127.0.0.1",
                },
                {
                    "agreement": AgreementType.CUSTOMER,
                    "signed_at": signed_at,
                    "ip_address": "127.0.0.1",
                },
                {
                    "agreement": AgreementType.MARGIN,
                    "signed_at": signed_at,
                    "ip_address": "127.0.0.1",
                },
                {
                    "agreement": AgreementType.CRYPTO,
                    "signed_at": signed_at,
                    "ip_address": "127.0.0.1",
                }
            ],
        }

        password = uuid.uuid4().hex[:15]
        password = "TEST_"+ password

        create_account_response = self.account_lifecycle_service.create_baskt_account(account_data=account_data, password=password)
        sleep(120)

        assert create_account_response is not None
        assert create_account_response["email_address"] == account_data["contact"]["email_address"]
        baskt_account_by_email = self.account_lifecycle_service.get_baskt_account_by_email_address(email_address=create_account_response["email_address"])
        baskt_account_by_cognito_user_id = self.account_lifecycle_service.get_baskt_account_by_cognito_user_id(cognito_user_id=create_account_response["cognito_user_id"])
        assert asdict(baskt_account_by_email) == asdict(baskt_account_by_cognito_user_id)
        assert baskt_account_by_email.alpaca_account_status.name == "ACTIVE"
        assert baskt_account_by_email.cognito_enabled_status is True
        return baskt_account_by_email
    
    def test_create_ach_relationship(self, alpaca_account_id: str, cognito_user_id: str, ):
        ach_relationship_data = {
            "account_owner_name": "baskt_testuser_46ec47e2",
            "bank_account_type": "checking",
            "bank_account_number": "123456789",
            "bank_routing_number": "121000358",
            "nickname": "Sandbox Checking"
        }
        ach_relationship = self.account_lifecycle_service.create_ach_relationship(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            ach_relationship_data=ach_relationship_data,
            is_plaid=False
        )

        assert ach_relationship.status.name.upper() == "QUEUED"
        assert str(ach_relationship.account_id) == alpaca_account_id
        assert ach_relationship.account_owner_name == ach_relationship_data["account_owner_name"]
        assert ach_relationship.bank_account_type.name.upper() == ach_relationship_data["bank_account_type"].upper()
        assert ach_relationship.bank_account_number == ach_relationship_data["bank_account_number"]
        assert ach_relationship.bank_routing_number == ach_relationship_data["bank_routing_number"]

        return str(ach_relationship.id)

    def test_get_ach_relationships(self, alpaca_account_id: str, cognito_user_id: str):
        return self.account_lifecycle_service.get_ach_relationships(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)



    def fund_baskt_account(
        self,
        baskt_account: BasktAccount,
        funding_amount: Decimal = Decimal("50000.00"),
    ):
        ach_relationship = self.account_lifecycle_service.create_ach_relationship(
            alpaca_account_id=baskt_account.alpaca_account_id,
            cognito_user_id=baskt_account.cognito_user_id,
            account_owner_name="Jane Q Tester",
            bank_account_type=BankAccountType.CHECKING,
            bank_account_number="123456789",
            bank_routing_number="121000358",
            nickname="Sandbox Checking",
        )
        ach_relationship_id = _response_value(ach_relationship, "id")
        assert ach_relationship_id is not None

        transfer = self.account_lifecycle_service.create_ach_transfer_request(
            alpaca_account_id=baskt_account.alpaca_account_id,
            cognito_user_id=baskt_account.cognito_user_id,
            relationship_id=ach_relationship_id,
            amount=str(funding_amount),
            direction=TransferDirection.INCOMING,
            timing=TransferTiming.IMMEDIATE,
        )

        assert Decimal(str(_response_value(transfer, "amount"))) == funding_amount
        assert _response_value(transfer, "relationship_id") is not None
    
    
    
@pytest.fixture(scope="session")
def test_engine(
    account_lifecycle_service: AccountLifecycleService,
    alpaca_broker_client: AlpacaBrokerClient,
) -> TestEngine:
    return TestEngine(
        account_lifecycle_service=account_lifecycle_service,
        alpaca_broker_client=alpaca_broker_client,
    )
