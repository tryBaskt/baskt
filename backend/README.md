ENV=dev ALPACA_ENV=sandbox uvicorn main:app --reload
npm run dev

Things to be aware of:
1. Email verified is set to true in CognitoClient.create_cognito_user()
2. Only Dev environment for creating cognito user