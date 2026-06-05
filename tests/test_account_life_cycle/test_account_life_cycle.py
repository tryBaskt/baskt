import pytest
from conftest import TestEngine
from time import sleep

@pytest.mark.integration
def test_create_account_ach_relationship(test_engine: TestEngine):
    baskt_account = test_engine.test_create_baskt_account()
    ach_relationship = test_engine.test_create_ach_relationship(alpaca_account_id=baskt_account.alpaca_account_id, cognito_user_id=baskt_account.cognito_user_id)
    sleep(120)
    ach_relationships = test_engine.test_get_ach_relationships(alpaca_account_id=baskt_account.alpaca_account_id, cognito_user_id=baskt_account.cognito_user_id)
    assert len(ach_relationships)==1
    assert ach_relationships[0].status.name.upper() == "APPROVED"