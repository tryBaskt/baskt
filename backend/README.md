ENV=dev ALPACA_ENV=sandbox uvicorn main:app --reload
npm run dev

Things to be aware of:
1. Email verified is set to true in CognitoClient.create_cognito_user()
2. Only Dev environment for creating cognito user
3. The realize filled orders only fills orders of latest transaction
    so if an order fails from a transaction A, then transaction B happens, then the orders from transaction A is filled, the system will not register because we will not look at transaction A anymore. So before each new transaction, we need to cancel failed orders from previous transactions


Frontend Prompt:
I want to build a new frontend for my app called frontend_v3 in the baskt/ root directory. I do not want this new frontend to look like frontendV2, as frontendV2 look amateurish. I want the new frontend to look professional, but also intuitive, modern, and easy to use. You can pull from existing popular websites as inspiration. I would like the new frontend to have a purple motif, similar to how Robinhood has a green motif. 

I will outline the different functionalities and you can decide how to organize the functionalities to their pages and/or folders. Generally, avoid making changes to the backend unless it is absolutely necessary / an obvious error.
You can see all the exposed routes in routes/, the request/response objects in schema. The workflow starts at routes -> services -> repositories / clients. Feel free to read the backend and the alpaca-py library as needed. Last, makes sure to define global as "globalThis" otherwise we will get this error: ReferenceError: global is not defined. Do not do npm install or npm build. I will do that.

1. Signing up-The user will onboard to the website. Read alpaca_broker_client.create_alpaca_account() and cognito_client.create_cognito_user(). NOTE: Only ask the user for visa information if the user is not a US citizen or a greencard holder
2. Logging in- The user will login in. The authorization is handled through AWS cognito. You can look at frontendV2 to see how to do the login and authorization.
3. Making a Baskt- The user can look up stocks, add them to a Baskt, and have the backtest run whenever updates to the Baskt are made. In the Baskt, users can set the weight of the stock, long or short, and leverage (but this is set to 1 and not changeable for now). You can get the list of stocks from GET "/backtest/tradeable-fractionable-us-baskt-assets". You can get backtest results from GET "/backtest". You can save the Baskt through POST "/model-portfolios". This functionality can probably be its own page called MakeABaskt.jsx.
4. Seeing User's Baskts- The user can see the baskts they have made and saved. You can get this from GET "/model-portfolios". The user should be able to the Baskt's name, description, created date, and last updated date. This functionality can be its own page called MyBaskts.jsx.
5. Seeing Baskt's Details- The user can see a baskt's specific details. This functionality will be complex. First, the user will be able to see the Baskt's name, description, created date, updated date, and latest positions. Display the previous snapshots of positions on the page but in the form of a dropdown, where the user can click a dropdown and can see that snapshot of positions. You can get all this data from from GET "/model-portfolios/{portfolio_id}". The user can also deposit, withdraw, and withdraw-all from the portfolio by making calls found in trade_execution_route.py. Last, the user should see all their transactions for this Baskt, which is from GET "/account-analytics/portfolios/{portfolio_id}/transactions". Last, if the user is the creator / portfolio owner of this baskt, there should be a button that says "Update", which takes you to the functionality of making a baskt. This time, the positions of the baskt are already prepopulated with the baskts latest positions, and the user can update the baskt as he wants. To update the baskt you do PUT "model-portfolios/{portfolio_id}". This functionality can be in a page called BasktPage.jsx.
6. Account Analytics- The user can see his current buying power, his equity value, a equity graph with periods of 1D, 1W, 1M, 3M, 1A. You can get this info from GET "/account-analytics". This functionality can be in a page called HomePage.jsx. When the user logs in, this is what they see first.
7. Transfering money between bank <-> account- The user can connect a ACH relationship and bank. They can connect at most one ACH and bank. For ACH, we can see the account number, account owner name, nickname, and bank_routing_number. For bank, the user should see name, bank_code, and account_number. Then, the user can deposit and withdraw money. Last, the user can see past transfers. The necessary methods should be available in account_lifecycle_route.py. This functionality can also be its own page called Transfer.jsx.





