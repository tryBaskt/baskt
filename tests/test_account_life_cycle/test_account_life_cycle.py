from datetime import datetime, timezone
import uuid
from time import sleep
from backend.services.account_lifecycle_service import AccountLifecycleService
import pytest

def test_create_deactivate_account(account_lifecycle_service: AccountLifecycleService):
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
			"tax_id_type": "USA_SSN",
			"country_of_citizenship": "USA",
			"country_of_birth": "USA",
			"country_of_tax_residence": "USA",
			"funding_source": ["employment_income"],
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
		},
		"agreements": [
			{
				"agreement": "customer_agreement",
				"signed_at": signed_at,
				"ip_address": "127.0.0.1",
			}
		],
	}

	password = uuid.uuid4().hex[:15]
	password = "TEST_"+ password

	create_account_response = account_lifecycle_service.create_baskt_account(account_data=account_data, password=password)

	assert create_account_response is not None
	assert create_account_response["email_address"] == account_data["contact"]["email_address"]
	baskt_account = account_lifecycle_service.get_baskt_account(email_address=create_account_response["email_address"])

	assert baskt_account.alpaca_account_status.name == "SUBMITTED"
	assert baskt_account.cognito_enabled_status == True

	sleep(120)

	is_deactivated = account_lifecycle_service.deactivate_baskt_account(email_address=create_account_response["email_address"])
	assert is_deactivated == True
	with pytest.raises(Exception):
		account_lifecycle_service.get_baskt_account(email_address=create_account_response["email_address"])




