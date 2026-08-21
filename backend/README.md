uvicorn main:app --reload
npm run dev:dev
pytest backend/tests_v2 --mock_alpaca

Things to be aware of:
1. Email verified is set to true in CognitoClient.create_cognito_user()
2. Need to create authorization for a non active alpaca account
3. Fix the calendar hours thing in deployables
4. Baskt ACcount email index











Frontend Prompt:

Recreate the full Baskt frontend as a React/Vite application. This specification covers behavior, data, navigation, validation, and backend integration.

## 1. Sources of truth and implementation boundaries

- Treat `backend/routes/` as the source of truth for HTTP methods, paths, query parameters, authentication dependencies, and status codes.
- Treat `backend/schema/` as the source of truth for request and response fields and their types.
- If a contract is unclear, trace the backend workflow through `routes -> services -> repositories/clients` and inspect any relevant `alpaca-py` model.
- Do not add or change backend behavior unless an obvious backend defect makes an existing route unusable.
- Keep request field names and enum values exactly aligned with the backend. Friendly display labels may differ from submitted enum values.
- The API base URL comes from `VITE_API_BASE_URL` and defaults to `http://localhost:8000`.
- Authenticated API requests send the Cognito ID token as `Authorization: Bearer <id-token>`.
- Configure Cognito with `VITE_COGNITO_REGION`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_REDIRECT_SIGN_IN`, and `VITE_COGNITO_REDIRECT_SIGN_OUT`.
- Define `global` as `globalThis` before loading `amazon-cognito-identity-js` if the selected Vite setup does not provide that shim.
- Parse successful empty responses without assuming a JSON body. The account-creation, relationship, bank, transfer, and model-portfolio mutation routes may return no content body.
- Every asynchronous operation needs a loading state, a disabled/submitting state where duplicate submission is possible, an empty-data state, and error handling.
- Any error shown to an end user must contain exactly `Error`. Do not expose backend messages, codes, stack traces, infrastructure details, account identifiers, or broker responses in the browser UI. The backend is responsible for logging the complete exception and stack trace to its terminal or runtime logs.

## 2. Authentication, session, and routing

Authenticate directly against AWS Cognito with `amazon-cognito-identity-js`.

### Session behavior

- Store the Cognito ID token, access token, and refresh token after successful authentication.
- Use the ID token for backend authorization.
- Remember the last successfully used email separately so it can prepopulate the next login attempt.
- Consider the user authenticated when a stored ID token is present.
- Signing out clears all stored tokens and always redirects to the login route.
- The first authenticated route is Home.

### Persistent routes

Use URL-backed routes so refreshing the browser preserves the current page instead of returning to Home. Support at least these routes:

- `/login`
- `/signup`
- `/home`
- `/make`
- `/make/{portfolio_id}` for update mode
- `/my-baskts`
- `/explore`
- `/transfer`
- `/baskts/{portfolio_id}`
- `/stocks/{stock_id}`

Hash routing is acceptable. Detail routes must contain only the stable backend identifier. Do not pass a stock object, model-portfolio object, analytics object, or allocation object from one page to another as the detail page's data source. A refreshed detail route must be able to hydrate itself completely from backend calls.

Authenticated primary navigation includes Home, Make a Baskt, My Baskts, Explore Baskts & Stocks, Transfer, and Sign out. Detail pages also provide a way to return to the page from which they were opened. Browser back/forward navigation must remain functional.

## 3. Login and password challenge

### Standard login

- Ask for email and password.
- Authenticate with Cognito `authenticateUser`.
- Save the returned ID/access/refresh tokens.
- Remember the email after success.
- Navigate to Home after success.
- Provide a path to Signup.
- Build the forgot-password link from the configured Cognito domain, app client ID, redirect URI, `response_type=code`, and `scope=openid email profile`.

### `NEW_PASSWORD_REQUIRED`

- Handle Cognito's `newPasswordRequired` callback without discarding the pending `CognitoUser` instance.
- Replace or advance the login form with a permanent-new-password form.
- Before calling `completeNewPasswordChallenge`, remove immutable attributes such as `email`, `email_verified`, `phone_number`, and `phone_number_verified` from the attributes sent back to Cognito.
- Save the new session tokens and navigate to Home after success.

## 4. Signup and account onboarding

Implement a multi-step flow with Contact, Identity, Disclosures, and Agreements. Preserve all values when moving backward or forward. Validate required fields before advancing or submitting. Submit the final `CreateBasktAccountLifecycleRequest` to:

`POST /accounts/create-baskt-account`

### Contact

Collect:

- `email_address`
- `phone_number`
- street address
- optional unit
- `city`
- `state`
- `postal_code`
- `country`

Submit the primary street address as the `street_address` list expected by the backend. Omit the optional unit when empty. Use supported country values and use a state selector when the selected country is the United States.

### Identity

Collect:

- `given_name`, optional `middle_name`, and `family_name`
- `date_of_birth`
- `tax_id` and `tax_id_type`
- `country_of_citizenship`
- `country_of_birth`
- `country_of_tax_residence`
- permanent-resident/green-card status
- `funding_source`
- `annual_income_min` and `annual_income_max`
- `liquid_net_worth_min` and `liquid_net_worth_max`
- `total_net_worth_min` and `total_net_worth_max`

Submit funding sources as a list, even when only one source is selected. Use the backend/Alpaca enum values for tax ID type, funding source, and related option fields.

Ask for `visa_type`, `visa_expiration_date`, and `date_of_departure_from_usa` only when the user is neither a US citizen nor a permanent resident. Completely omit those keys otherwise.

### Disclosures

Collect:

- `is_control_person`
- `is_affiliated_exchange_or_finra`
- `is_politically_exposed`
- `immediate_family_exposed`
- `employment_status`

Collect `employer_name`, `employer_address`, and `employment_position` only when employment status requires employer information. Submit the four disclosure flags as booleans, not the strings used by HTML controls.

### Agreements and password

- Require `account_agreement`, `customer_agreement`, and `margin_agreement`.
- Provide links to the corresponding Alpaca agreement documents.
- Include `crypto_agreement` only when the contact country is `USA` and the state is one of: `AZ`, `CA`, `CT`, `GA`, `ID`, `IL`, `IN`, `IA`, `KS`, `KY`, `ME`, `MD`, `MA`, `MI`, `MS`, `MO`, `MT`, `NE`, `NC`, `ND`, `OH`, `RI`, `SC`, `SD`, `UT`, `VT`, `WA`, or `WV`.
- Require every agreement currently shown to be accepted.
- Submit each accepted agreement with `agreement`, an ISO-8601 `signed_at`, and `ip_address`.
- Ask for a password and confirmation; do not submit if they differ.
- Send the password in the top-level request so the backend can create the Cognito user.
- After successful account creation, automatically return to Login.

## 5. Home

Hydrate Home with one authenticated call:

`GET /allocation_analytics`

The `AllAllocationAnalyticsResponse` supplies `cash`, `equity`, `equity_graph`, and `allocations`.

### Account summary

- Show current cash.
- Show current account equity.
- Show one-day profit/loss in dollars and percent when the `1D` equity series has at least two finite values and its first value is nonzero.
- Calculate one-day dollar P/L as `last 1D equity - first 1D equity`.
- Calculate one-day P/L percent as `dollar P/L / abs(first 1D equity) * 100`.
- If the calculation cannot be made, show it as unavailable. This frontend calculation does not adjust for intraday deposits or withdrawals.

### Account equity history

- Default the selected period to `1D`.
- Support `1D`, `1W`, `1M`, `3M`, `1A`, and `ALL` when present in `equity_graph`.
- Each period contains parallel `equity` and `timestamp` arrays.
- Plot equity in USD against the supplied timestamps.
- Display x-axis and y-axis values.
- Format y-axis currency values to two decimal places.
- Use the selected series minimum and maximum as y-axis bounds. If all values are equal, create a small nonzero fallback range so the graph remains valid.
- Use time labels for intraday data and date labels for longer periods.

### Invested allocations

Convert the `allocations` mapping into rows. Each entry is keyed by its portfolio/asset identifier and includes the fields needed to show:

- `allocation_name`
- `allocation_type`
- `allocation_equity`
- `allocation_equity_percent`

Map `MODEL_PORTFOLIO` to a user-facing Baskt type and `STOCK` to a Stock type. Show the sum of allocation equities as invested value. Do not display the raw portfolio/asset identifier. Rows must be keyboard operable and selectable:

- A model-portfolio row opens `/baskts/{portfolio_id}`.
- A stock row opens `/stocks/{stock_id}`; the mapping key is the Alpaca stock/asset ID.

The destination page must then fetch its own data from the backend.

## 6. Make or update a Baskt

### Asset universe and search

Load the available assets from:

`GET /backtest/tradeable-fractionable-us-baskt-assets`

Use the returned `StockResponse` records as the source of symbol and capability data. Search the loaded assets locally by symbol, return every matching asset that has not already been selected, and do not clear the search query when a result is selected.

### Position editor

Each selected position has:

- `symbol`
- `target_weight`
- `direction`, where `1` is long and `-1` is short
- `leverage`, currently fixed at `1.0`

Users may add and remove positions and edit weights and direction. Allow Short only when that asset's `shortable` field is true. If a saved position is short but its current asset metadata is no longer shortable, prevent submitting an invalid short selection.

Users edit weights as percentages, but all backend requests send decimal weights between `0` and `1`. For example, display `25%` and send `0.25`. A portfolio is fully allocated when its weights sum to `1.0`, allowing a small floating-point tolerance.

### Backtest

Allow an inclusive start date and end date. Request:

`POST /backtest`

```json
{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "positions": []
}
```

The positions must use the backtest request contract. Debounce requests while the user edits. Do not call the backend unless:

- at least one valid position exists;
- every symbol, weight, direction, and leverage is valid;
- weights sum to `1.0`; and
- the date range is valid.

Display the returned cumulative-return series and all available metrics:

- `final_cumulative_return`
- `cagr`
- `annualized_volatility`
- `leverage_adjusted_direction`
- `alpha`
- `beta`
- `sharpe_ratio`
- `maximum_drawdown`
- `maximum_drawdown_duration`

Unavailable optional metrics must not break the page.

### Create mode

Create with:

`POST /model-portfolios`

using `CreateModelPortfolioRequest` with `name`, optional `description`, and decimal-weight `positions`. Navigate to My Baskts after success.

### Update mode

When routed to `/make/{portfolio_id}`:

- Hydrate the portfolio from `GET /model-portfolios/{portfolio_id}`.
- Use the latest item in `position_history` to populate the editor.
- Reconcile saved symbols with current asset metadata.
- Keep the existing portfolio name unchanged and non-editable.
- Allow the description and positions to change.
- Rerun the backtest as valid changes are made.
- Save with `PUT /model-portfolios/{portfolio_id}` using `UpdateModelPortfolioRequest`.
- Navigate to My Baskts after success.

## 7. My Baskts

Load the authenticated user's portfolios with:

`GET /model-portfolios`

For each item, show `portfolio_name`, optional `description`, `created_at`, and `updated_at`, and allow it to open `/baskts/{portfolio_id}`. If the list endpoint does not contain every desired detail, request `GET /model-portfolios/{portfolio_id}` for items in parallel and fall back to the metadata item when an individual detail request fails. Include a Create Baskt action and an empty state when no portfolios exist.

## 8. Explore Baskts & Stocks

Provide one search input for model-portfolio name/description and exact stock symbol. Do not search when the trimmed query is empty. Request:

`GET /search?query={query}&limit={limit}&offset={offset}`

The combined response contains:

- `stocks`: zero or more exact stock-symbol results with `stock_id`, `symbol`, `tradable`, `fractionable`, `shortable`, `marginable`, and `stock_class`.
- `model_portfolios`: a paginated object containing `model_portfolios`, `total`, `limit`, and `offset`.

Show all returned stock matches and all returned model-portfolio matches. Stock results expose all four capability flags when true. Model-portfolio results show name, description, created time, and updated time.

Pagination applies to model-portfolio results. Previous and Next update `offset` while preserving the current query. Use the response's `total`, `limit`, and `offset` to determine bounds. Opening a result routes only by stable ID:

- Stock: `/stocks/{stock_id}`
- Model portfolio: `/baskts/{portfolio_id}`

Do not use the search result object as the detail page's canonical data.

## 9. Baskt detail

The Baskt detail page must hydrate all data from backend calls whenever it opens, regardless of whether it was reached from Home, My Baskts, Explore, a copied URL, browser history, or a refresh.

Start the independent detail and model-performance requests without unnecessarily waiting for one another:

- `GET /model-portfolios/{portfolio_id}`
- `GET /model-portfolios/{portfolio_id}/analytics`

Request the user's investment allocation for the portfolio:

`GET /allocation_analytics/portfolios/{portfolio_id}/analytics`

### Portfolio detail and snapshots

Display:

- `portfolio_name`
- optional `description`
- `created_at`
- `updated_at`
- the number of snapshots
- the latest position snapshot
- all previous snapshots, newest first, with a way to expand each snapshot

For latest positions, display symbol, target weight, current weight from `positions_current_weight`, direction, and leverage. Position weights are decimals in the response and must be displayed as percentages. Historical snapshots include `snapshot_id`, timestamp, and positions.

Decode the Cognito ID token to get the current `sub`. Provide Update only when it matches `portfolio_owner_cognito_user_id`; Update opens `/make/{portfolio_id}`.

### Model-portfolio performance

Support `1D`, `1W`, `1M`, `3M`, `1A`, and `all` keys returned by `ModelPortfolioAnalyticsResponse`. Default to an available period, preferring `1D`. For the selected period, plot `cumulative_returns` against `timestamp` and show:

- `final_cumulative_return`
- `cagr`
- `annualized_volatility`
- `leverage_adjusted_direction`
- `alpha`
- `beta`
- `sharpe_ratio`
- `maximum_drawdown`
- `maximum_drawdown_duration`

Handle optional metrics as unavailable rather than failing the entire page.

### User allocation and transaction history

The allocation response may contain only `portfolio_id` when the current user has never invested. Show allocation metrics only when values are present:

- `total_cost_basis`
- `equity`
- `profit_loss`
- `profit_loss_percent`

Render each transaction with:

- `created_at`
- optional `filled_at`, labeled `Filled at`
- `transaction_type`
- optional `requested_amount`
- optional `cost_basis`, presented as the transaction's filled amount/value
- optional `order_fill_percent`
- `status`

Interpret a null `requested_amount` by transaction type: `WITHDRAW_ALL` means Withdraw all, while `UPDATE` has no requested amount and should display an unavailable marker rather than Withdraw all. Transaction statuses can include `QUEUED`, `PROCESSING`, `ORDERED`, `PARTIALLY_FILLED`, `FULLY_FILLED`, `CANCELLED`, and `FAILED`.

### Baskt trading actions

Use these queued trade routes:

- `POST /trade-execution/portfolios/{portfolio_id}/deposit`
- `POST /trade-execution/portfolios/{portfolio_id}/withdrawal`
- `POST /trade-execution/portfolios/{portfolio_id}/withdraw-all`

Deposit and withdrawal require a positive numeric `amount` and `portfolio_owner_cognito_user_id`. Withdraw-all requires `portfolio_owner_cognito_user_id`. Treat HTTP `202 Accepted` as successful queue submission, not as proof that broker orders have filled. Refresh allocation analytics after submission so the new transaction and its latest status can appear.

## 10. Stock detail

The stock detail route is `/stocks/{stock_id}`, where `stock_id` is Alpaca's stable stock/asset ID. Never use a symbol as the route identifier and never depend on a stock object passed from Home or Explore.

On every open, request metadata and allocation independently:

- `GET /stocks/{stock_id}`
- `GET /allocation_analytics/stocks/{stock_id}/analytics`

After metadata supplies the symbol, request:

`GET /stock-analytics/{symbol}`

### Metadata and performance

Display backend-hydrated `symbol`, `stock_class`, `tradable`, `fractionable`, `shortable`, and `marginable`. Support `1D`, `1W`, `1M`, `3M`, `1A`, and `all` analytics periods, preferring `1D`. Plot `prices` against `timestamp` and show:

- `final_cumulative_return`
- `cagr`
- `annualized_volatility`
- `leverage_adjusted_direction`
- `alpha`
- `beta`
- `sharpe_ratio`
- `maximum_drawdown`
- `maximum_drawdown_duration`

### User allocation and transactions

When allocation values are present, display `total_cost_basis`, `equity`, `profit_loss`, and `profit_loss_percent`. If the user has never traded the stock, show the no-position state and do not invent zero-valued transaction rows.

Render transaction history using `created_at`, optional `filled_at` labeled `Filled at`, `transaction_type`, optional `requested_amount`, optional `cost_basis` as filled amount/value, optional `order_fill_percent`, and `status`. For stock transactions, a null requested amount represents `CLOSE`.

### Stock trading actions

Use:

- `POST /trade-execution/stocks/{asset_id}/buy` with `symbol` and positive `amount`.
- `POST /trade-execution/stocks/{asset_id}/sell` with `symbol` and positive `amount`.
- `POST /trade-execution/stocks/{asset_id}/close` with `symbol`.

For these trade routes, `asset_id` is the same Alpaca identifier represented as `stock_id` elsewhere in the frontend workflow.

Buy is available only when the stock is tradable. Sell may open or increase a short position only when `shortable` is true. For a non-shortable stock, prevent selling more than the user's current position. Close is available only when an allocation exists. Treat `202 Accepted` as queued and refresh allocation analytics after submission.

## 11. Transfers and funding relationships

On page load, start these requests concurrently and allow their results to populate independently:

- `GET /accounts/ach-relationships`
- `GET /accounts/banks`
- `GET /accounts/transfers?limit={limit}&offset={offset}`

The application supports at most one active ACH relationship and one bank relationship at a time.

### ACH relationship

- Create with `POST /accounts/ach-relationship`.
- Replace/change with `PUT /accounts/ach-relationship`.
- Submit `account_owner_name`, `bank_account_type`, `bank_account_number`, `bank_routing_number`, and optional `nickname`.
- `bank_account_type` supports `CHECKING` and `SAVINGS`.
- When present, display status and the saved owner, nickname, routing number, and account number.
- Allow the user to enter change mode, prepopulate the form from the backend response, save, or cancel.

### Bank relationship

- Create with `POST /accounts/bank`.
- Replace/change with `PUT /accounts/bank`.
- Submit `name`, `bank_code_type`, `bank_code`, `account_number`, and the optional country, state/province, postal code, city, and street-address fields from `CreateBasktBankRequest`.
- When present, display status, name, bank code, and Alpaca account number.
- Allow the user to enter change mode, prepopulate the form from the backend response, save, or cancel.

After changing one relationship, refresh at least that relationship without discarding the other relationship or transfer history already loaded.

### Account deposits and withdrawals

Submit account transfers to:

`POST /accounts/transfer`

using `CreateBasktTransferRequest`:

- Convert `amount` to a string.
- Use `INCOMING` for deposit and `OUTGOING` for withdrawal.
- Select `ACH` or `BANK` as `funding_source_type`.
- Include `relationship_id` only for ACH.
- Include `bank_id` only for bank.
- Include the backend-supported `timing` value, currently `IMMEDIATE` in the frontend workflow.
- Disable source choices that are not connected and prevent submission when neither source exists.

After submission, clear the amount and refresh transfer history.

### Transfer history

Read `BasktTransfersResponse.items` and display each transfer's direction, amount, status, source (derived from `relationship_id` versus `bank_id`), and creation time. Respect `limit`, `offset`, `has_next`, and `has_previous` when implementing pagination.

## 12. Shared behavior and data formatting

- Centralize API calls so authorization, base URL selection, content type, empty responses, and JSON errors are handled consistently.
- Centralize Cognito authentication and token persistence.
- Centralize date/time, currency, percentage, signed-number, and unavailable-value formatting.
- Use reusable chart logic for account equity, model-portfolio returns, stock prices, and backtest returns.
- Display monetary values as USD with two decimal places unless the backend contract calls for another representation.
- Display decimal weights and decimal return metrics as percentages where appropriate, but do not multiply values that the backend already returns in percentage units. Confirm each schema/service contract before formatting.
- Display timestamps in the user's local timezone while preserving their actual instant.
- Treat `null`, missing optional fields, empty arrays, and empty mappings as valid states.
- Ignore or filter non-finite chart values rather than allowing one bad point to make the graph blank.
- Keep form state while moving between signup steps and while editing a Baskt.
- Use backend capability flags and ownership fields to enable or disable actions; do not infer permissions from the page the user came from.
- Never display internal IDs unless they are explicitly meaningful to the user. IDs remain available internally for routing and API calls.
