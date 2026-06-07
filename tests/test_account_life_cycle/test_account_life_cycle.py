import pytest
from conftest import TestEngine
from time import sleep

@pytest.mark.integration
def test_ach_create_transfer_delete(test_engine: TestEngine):

    baskt_account = test_engine.test_create_baskt_account()

    alpaca_account_id = baskt_account.alpaca_account_id
    cognito_user_id = baskt_account.cognito_user_id

    test_engine._clean_up_achs_banks(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
    )
    print("Creating Baskt Account")
    sleep(120)

    # ACH
    ach_relationship = test_engine.test_create_direct_ach_relationship(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        account_owner_name="acct_lifecycle_account",
        bank_account_type="checking",
        bank_account_number="123456789",
        bank_routing_number="121000358",
        nickname="Sandbox Checking"

    )
    print("\nWaiting 120 seconds for creating ach relationship...\n")
    sleep(120)
    ach_relationships = test_engine.test_get_ach_relationships(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
    assert len(ach_relationships) == 1
    assert str(ach_relationships[0].id) == str(ach_relationship.id)
    assert str(ach_relationships[0].account_id) == str(ach_relationship.account_id)
    assert ach_relationships[0].account_owner_name == ach_relationship.account_owner_name
    assert ach_relationships[0].bank_account_type == ach_relationship.bank_account_type
    assert ach_relationships[0].bank_account_number == ach_relationship.bank_account_number
    assert ach_relationships[0].bank_routing_number == ach_relationship.bank_routing_number
    assert ach_relationships[0].status.name.upper() == "APPROVED"
    ach_relationship_id = str(ach_relationships[0].id)

    # ACH TRANSFER
    transfer = test_engine.test_create_ach_transfer(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        amount="20000",
        direction="INCOMING",
        timing="IMMEDIATE",
        fee_payment_method="USER",
        relationship_id=ach_relationship_id
    )

    # DELETE ACH
    test_engine.test_delete_ach_relationship(alpaca_account_id=alpaca_account_id,cognito_user_id=cognito_user_id, ach_relationship_id=ach_relationship_id)
    ach_relationships = test_engine.test_get_ach_relationships(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
    assert len(ach_relationships) == 0


@pytest.mark.integration
def test_bank_create_delete(test_engine: TestEngine):

    baskt_account = test_engine.test_create_baskt_account()

    alpaca_account_id = baskt_account.alpaca_account_id
    cognito_user_id = baskt_account.cognito_user_id

    test_engine._clean_up_achs_banks(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
    )
    print("Creating Baskt Account")
    sleep(120)

    # BANK
    bank = test_engine.test_create_bank(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        name="Sandbox Bank",
        bank_code_type="ABA",
        bank_code="121000358",
        account_number="987654321"
    )
    print("\nWaiting 120 seconds for creating bank...\n")
    sleep(120)
    banks = test_engine.test_get_banks(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
    assert len(banks) == 1
    assert str(banks[0].id) == str(bank.id)
    assert str(banks[0].account_id) == str(bank.account_id)
    assert banks[0].name == bank.name
    assert banks[0].bank_code_type == bank.bank_code_type
    assert banks[0].bank_code == bank.bank_code
    assert banks[0].status.name.upper() == "APPROVED"
    bank_id = str(banks[0].id)

    test_engine.test_delete_bank(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        bank_id=bank_id
    )
    banks = test_engine.test_get_banks(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
    assert len(banks) == 0
    
