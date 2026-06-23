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
from backend.domain.baskt_domain import BasktAccount
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
        assert create_account_response is not None
        assert create_account_response["email_address"] == account_data["contact"]["email_address"]
        baskt_account_by_email = self.account_lifecycle_service.get_baskt_account_by_email_address(email_address=create_account_response["email_address"])
        baskt_account_by_cognito_user_id = self.account_lifecycle_service.get_baskt_account_by_cognito_user_id(cognito_user_id=create_account_response["cognito_user_id"])
        assert asdict(baskt_account_by_email) == asdict(baskt_account_by_cognito_user_id)
        assert baskt_account_by_email.alpaca_account_status.name in ["ACTIVE", "SUBMITTED", "APPROVED"]
        assert baskt_account_by_email.cognito_enabled_status is True
        return baskt_account_by_email
    
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
    
    def test_create_plaid_ach_relationship(
        self, 
        alpaca_account_id: str, 
        cognito_user_id: str,
        processor_token: str
    ):

        plaid_ach_relationship = self.account_lifecycle_service.create_plaid_ach_relationship(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            processor_token=processor_token
        )

        assert str(plaid_ach_relationship.account_id) == alpaca_account_id
        assert str(plaid_ach_relationship.processor_token)==processor_token

        return str(plaid_ach_relationship.id)

    
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
        assert transfer.amount == amount
        assert transfer.type.name.upper() == "ACH"
        assert transfer.direction.name.upper() == direction.upper()
        assert transfer.fee_payment_method.name.upper() == fee_payment_method.upper()

        return transfer
    
    def test_create_bank(
        self, 
        alpaca_account_id: str, 
        cognito_user_id: str,
        name: str,
        bank_code_type: str,
        bank_code: str,
        account_number: str
    ):

        bank = self.account_lifecycle_service.create_bank(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            name=name,
            bank_code_type=bank_code_type,
            bank_code=bank_code,
            account_number=account_number,
        )


        assert bank is not None
        assert bank.status.name.upper() in ["QUEUED", "APPROVED"]
        assert str(bank.account_id) == alpaca_account_id
        assert bank.name.upper() == name.upper()
        assert bank.bank_code == bank_code
        assert bank.account_number == account_number
        assert bank.bank_code_type.name.upper() == bank_code_type

        return bank
    
    def test_get_banks(self, alpaca_account_id: str, cognito_user_id: str):
        banks = self.account_lifecycle_service.get_banks(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
        return banks
    
    def test_delete_bank(
        self,
        alpaca_account_id: str,
        cognito_user_id: str,
        bank_id: str
    ):
        self.account_lifecycle_service.delete_bank(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            bank_id=bank_id
        )
    
    def test_create_bank_transfer(
        self, alpaca_account_id: str, 
        cognito_user_id: str, 
        amount: str,
        direction: str,
        timing: str,
        fee_payment_method: str,
        bank_id: str
    ):

        transfer = self.account_lifecycle_service.create_bank_transfer(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            amount=amount,
            direction=direction,
            timing=timing,
            fee_payment_method=fee_payment_method,
            bank_id=bank_id
        )

        assert str(transfer.account_id) == alpaca_account_id
        assert str(transfer.relationship_id).upper() == bank_id.upper()
        assert transfer.amount == amount
        assert transfer.type.name.upper() == "WIRE"
        assert transfer.direction.name.upper() == direction.upper()
        assert transfer.fee_payment_method.name.upper() == fee_payment_method.upper()

        return transfer


    def _clean_up_achs_banks(
        self,
        alpaca_account_id: str,
        cognito_user_id: str
    ):
        try:
            ach_relationships = self.test_get_ach_relationships(
                alpaca_account_id=alpaca_account_id, 
                cognito_user_id=cognito_user_id
            )
            self.test_delete_ach_relationship(
                alpaca_account_id=alpaca_account_id, 
                cognito_user_id=cognito_user_id, 
                ach_relationship_id=str(ach_relationships[0].id)
            )
        except Exception as e:
            pass

        try:
            banks = self.test_get_banks(
                alpaca_account_id=alpaca_account_id, 
                cognito_user_id=cognito_user_id
            )
            self.test_delete_bank(
                alpaca_account_id=alpaca_account_id, 
                cognito_user_id=cognito_user_id, 
                ach_relationship_id=str(banks[0].id)
            )
        except Exception as e:
            pass







    

    
    
    
    
@pytest.fixture(scope="session")
def test_engine(
    account_lifecycle_service: AccountLifecycleService,
    alpaca_broker_client: AlpacaBrokerClient,
) -> TestEngine:
    return TestEngine(
        account_lifecycle_service=account_lifecycle_service,
        alpaca_broker_client=alpaca_broker_client,
    )
