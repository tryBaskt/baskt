ENV=dev ALPACA_ENV=sandbox uvicorn main:app --reload
npm run dev

Things to be aware of:
1. Email verified is set to true in CognitoClient.create_cognito_user()
2. Only Dev environment for creating cognito user
3. The realize filled orders only fills orders of latest transaction
    so if an order fails from a transaction A, then transaction B happens, then the orders from transaction A is filled, the system will not register because we will not look at transaction A anymore. So before each new transaction, we need to cancel failed orders from previous transactions