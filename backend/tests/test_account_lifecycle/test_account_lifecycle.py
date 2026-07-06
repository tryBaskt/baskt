"""Integration tests for the account lifecycle flow."""

from datetime import datetime, timezone
import uuid

import pytest

from .conftest import TestEngine
from backend.domain.baskt_account_domain import (
    ContactData,
    DisclosuresData,
    IdentityData,
)


# @pytest.fixture(scope="module")
# def created_baskt_account(test_engine: TestEngine):
#     """Create one account shared by the independent section-update tests."""
#     unique_suffix = uuid.uuid4().hex
#     test_account_data = {
#         "display_name": f"Lifecycle Test {unique_suffix[:8]}",
#         "contact": {
#             "email_address": f"baskt_test_{unique_suffix}@example.com",
#             "phone_number": "+15555551234",
#             "street_address": ["123 Market St"],
#             "unit": "9A",
#             "city": "San Francisco",
#             "state": "CA",
#             "postal_code": "94105",
#             "country": "USA",
#         },
#         "identity": {
#             "given_name": "Jane",
#             "middle_name": "Q",
#             "family_name": "Tester",
#             "date_of_birth": "1990-01-01",
#             "tax_id": "999-99-1234",
#             "tax_id_type": "USA_SSN",
#             "country_of_citizenship": "USA",
#             "country_of_birth": "USA",
#             "country_of_tax_residence": "USA",
#             "funding_source": ["employment_income", "savings"],
#             "annual_income_min": 50000,
#             "annual_income_max": 120000,
#             "liquid_net_worth_min": 10000,
#             "liquid_net_worth_max": 50000,
#             "total_net_worth_min": 50000,
#             "total_net_worth_max": 200000,
#         },
#         "disclosures": {
#             "is_control_person": False,
#             "is_affiliated_exchange_or_finra": False,
#             "is_politically_exposed": False,
#             "immediate_family_exposed": False,
#             "employment_status": "EMPLOYED",
#             "employer_name": "Baskt Test Employer",
#             "employer_address": "123 Market St, San Francisco, CA 94105",
#             "employment_position": "Software Engineer",
#         },
#         "agreements": [
#             {
#                 "agreement": agreement,
#                 "signed_at": datetime.now(timezone.utc).isoformat(),
#                 "ip_address": "127.0.0.1",
#             }
#             for agreement in (
#                 "account_agreement",
#                 "customer_agreement",
#                 "margin_agreement",
#                 "crypto_agreement"
#             )
#         ],
#     }
#     response = test_engine.test_create_baskt_account(
#         test_account_data=test_account_data,
#         password=f"Test_9aA{unique_suffix[:16]}",
#     )
#     yield {
#         "response": response,
#         "account_data": test_account_data,
#     }

#     test_engine._clean_up_achs_banks_baskt_account(
#         cognito_user_id=response["cognito_user_id"],
#         alpaca_account_id=response["alpaca_account_id"],
#     )


# def test_create_baskt_account(created_baskt_account):
#     """Create an account and verify its Alpaca and DynamoDB representations."""
#     response = created_baskt_account["response"]
#     account_data = created_baskt_account["account_data"]

#     assert response["cognito_user_id"]
#     assert response["alpaca_account_id"]
#     assert response["alpaca_account_number"]
#     assert response["email_address"] == account_data["contact"]["email_address"]



# def test_update_identity_data(
#     test_engine: TestEngine,
#     created_baskt_account,
# ):
#     """Update identity data and verify the change in Alpaca and DynamoDB."""
#     response = created_baskt_account["response"]
#     identity_data = IdentityData(
#         given_name="Jane",
#         middle_name="Q",
#         family_name="Tester",
#         date_of_birth="1990-01-01",
#         tax_id_type="USA_SSN",
#         country_of_citizenship="USA",
#         country_of_birth="USA",
#         country_of_tax_residence="USA",
#         funding_source=["employment_income", "savings"],
#         annual_income_min=60000,
#         annual_income_max=130000,
#         liquid_net_worth_min=20000,
#         liquid_net_worth_max=60000,
#         total_net_worth_min=60000,
#         total_net_worth_max=210000,
#     )

#     test_engine.test_update_identity_data(
#         cognito_user_id=response["cognito_user_id"],
#         alpaca_account_id=response["alpaca_account_id"],
#         identity_data=identity_data,
#     )


# def test_update_contact_data(
#     test_engine: TestEngine,
#     created_baskt_account,
# ):
#     """Update contact data and verify the change in Alpaca and DynamoDB."""
#     response = created_baskt_account["response"]
#     original_contact = created_baskt_account["account_data"]["contact"]
#     contact_data = ContactData(
#         email_address=original_contact["email_address"],
#         phone_number="+15555559876",
#         street_address=["456 Mission St"],
#         unit="12B",
#         city="San Francisco",
#         state="CA",
#         postal_code="94105",
#         country="USA",
#     )

#     test_engine.test_update_contact_data(
#         cognito_user_id=response["cognito_user_id"],
#         alpaca_account_id=response["alpaca_account_id"],
#         contact_data=contact_data,
#     )


# def test_update_disclosures_data(
#     test_engine: TestEngine,
#     created_baskt_account,
# ):
#     """Update disclosures and verify the change in Alpaca and DynamoDB."""
#     response = created_baskt_account["response"]
#     disclosures_data = DisclosuresData(
#         immediate_family_exposed=False,
#         is_control_person=False,
#         is_affiliated_exchange_or_finra=False,
#         is_politically_exposed=False,
#         employment_status="EMPLOYED",
#         employer_name="Updated Baskt Test Employer",
#         employer_address="456 Mission St, San Francisco, CA 94105",
#         employment_position="Senior Software Engineer",
#     )

#     test_engine.test_update_disclosures_data(
#         cognito_user_id=response["cognito_user_id"],
#         alpaca_account_id=response["alpaca_account_id"],
#         disclosures_data=disclosures_data,
#     )


# @pytest.mark.integration
# def test_identity_progresses_from_h1b_to_permanent_resident_to_citizen(
#     test_engine: TestEngine,
# ):
#     """Verify immigration-status identity updates across the account lifecycle."""
#     unique_suffix = uuid.uuid4().hex
#     account_data = {
#         "display_name": f"Immigration Test {unique_suffix[:8]}",
#         "contact": {
#             "email_address": f"immigration_test_{unique_suffix}@example.com",
#             "phone_number": "+15555551234",
#             "street_address": ["123 Market St"],
#             "unit": "9A",
#             "city": "San Francisco",
#             "state": "CA",
#             "postal_code": "94105",
#             "country": "USA",
#         },
#         "identity": {
#             "given_name": "Asha",
#             "family_name": "Tester",
#             "date_of_birth": "1990-01-01",
#             "tax_id": "999-99-1234",
#             "tax_id_type": "USA_SSN",
#             "country_of_citizenship": "IND",
#             "country_of_birth": "IND",
#             "country_of_tax_residence": "USA",
#             "visa_type": "H1B",
#             "visa_expiration_date": "2030-12-31",
#             "date_of_departure_from_usa": "2030-12-31",
#             "permanent_resident": False,
#             "funding_source": ["employment_income", "savings"],
#             "annual_income_min": 50000,
#             "annual_income_max": 120000,
#             "liquid_net_worth_min": 10000,
#             "liquid_net_worth_max": 50000,
#             "total_net_worth_min": 50000,
#             "total_net_worth_max": 200000,
#         },
#         "disclosures": {
#             "is_control_person": False,
#             "is_affiliated_exchange_or_finra": False,
#             "is_politically_exposed": False,
#             "immediate_family_exposed": False,
#             "employment_status": "EMPLOYED",
#             "employer_name": "Baskt Test Employer",
#             "employer_address": "123 Market St, San Francisco, CA 94105",
#             "employment_position": "Software Engineer",
#         },
#         "agreements": [
#             {
#                 "agreement": agreement,
#                 "signed_at": datetime.now(timezone.utc).isoformat(),
#                 "ip_address": "127.0.0.1",
#             }
#             for agreement in (
#                 "account_agreement",
#                 "customer_agreement",
#                 "margin_agreement",
#             )
#         ],
#     }

#     response = None
#     try:
#         response = test_engine.test_create_baskt_account(
#             test_account_data=account_data,
#             password=f"Test_9aA{unique_suffix[:16]}",
#         )
#         identifiers = {
#             "cognito_user_id": response["cognito_user_id"],
#             "alpaca_account_id": response["alpaca_account_id"],
#         }

#         # permanent_resident_identity = IdentityData(
#         #     given_name="Asha",
#         #     family_name="Tester",
#         #     date_of_birth="1990-01-01",
#         #     country_of_citizenship="IND",
#         #     country_of_birth="IND",
#         #     country_of_tax_residence="USA",
#         #     permanent_resident=True,
#         #     funding_source=["employment_income", "savings"],
#         #     annual_income_min=50000,
#         #     annual_income_max=120000,
#         #     liquid_net_worth_min=10000,
#         #     liquid_net_worth_max=50000,
#         #     total_net_worth_min=50000,
#         #     total_net_worth_max=200000,
#         # )
#         # test_engine.test_update_identity_data(
#         #     **identifiers,
#         #     identity_data=permanent_resident_identity,
#         # )

#         citizen_identity = IdentityData(
#             given_name="Asha",
#             family_name="Tester",
#             date_of_birth="1990-01-01",
#             country_of_citizenship="USA",
#             country_of_tax_residence="USA",
#             tax_id_type="USA_SSN",
#             permanent_resident=None,
#             funding_source=["employment_income", "savings"],
#             annual_income_min=50000,
#             annual_income_max=120000,
#             liquid_net_worth_min=10000,
#             liquid_net_worth_max=50000,
#             total_net_worth_min=50000,
#             total_net_worth_max=200000,
#         )
#         test_engine.test_update_identity_data(
#             **identifiers,
#             identity_data=citizen_identity,
#         )
#     finally:
#         if response is not None:
#             test_engine._clean_up_achs_banks_baskt_account(
#                 cognito_user_id=response["cognito_user_id"],
#                 alpaca_account_id=response["alpaca_account_id"],
#             )


# @pytest.mark.integration
# def test_create_and_delete_ach_relationship(
#     test_engine: TestEngine,
#     created_baskt_account,
# ):
#     """Create, retrieve, delete, and verify removal of an ACH relationship."""
#     response = created_baskt_account["response"]
#     alpaca_account_id = response["alpaca_account_id"]
#     cognito_user_id = response["cognito_user_id"]

#     created_relationship = test_engine.test_create_direct_ach_relationship(
#         alpaca_account_id=alpaca_account_id,
#         cognito_user_id=cognito_user_id,
#         account_owner_name="Jane Q Tester",
#         bank_account_type="CHECKING",
#         bank_account_number="123456789",
#         bank_routing_number="011000015",
#         nickname=f"Lifecycle Test {uuid.uuid4().hex[:8]}",
#     )
#     relationship_id = str(created_relationship.id)

#     relationships = test_engine.test_get_ach_relationships(
#         alpaca_account_id=alpaca_account_id,
#         cognito_user_id=cognito_user_id,
#     )
#     assert any(str(relationship.id) == relationship_id for relationship in relationships)

#     test_engine.test_delete_ach_relationship(
#         alpaca_account_id=alpaca_account_id,
#         cognito_user_id=cognito_user_id,
#         ach_relationship_id=relationship_id,
#     )
