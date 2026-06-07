import pytest
from conftest import TestEngine
from time import sleep

ALPACA_ACCOUNT_ID = "0405894a-09b4-4c4f-9076-871170a64ddc"
COGNITO_USER_ID = "74989408-5081-7013-7d57-f447fe1abfd"

@pytest.mark.integration
def test_create_account_ach_relationship_transfer(test_engine: TestEngine):
    # baskt_account = test_engine.test_create_baskt_account()
    # ach_relationship_id = test_engine.test_create_ach_relationship(alpaca_account_id=baskt_account.alpaca_account_id, cognito_user_id=baskt_account.cognito_user_id)
    ach_relationships = test_engine.test_get_all_ach_relationships(alpaca_account_id=ALPACA_ACCOUNT_ID, cognito_user_id=COGNITO_USER_ID)
    assert len(ach_relationships)==1
    test_engine.test_create_direct_ach_transfer(
        alpaca_account_id=ALPACA_ACCOUNT_ID,
        cognito_user_id=COGNITO_USER_ID,
        relationship_id=ach_relationships[0].id
    )

