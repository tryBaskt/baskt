ENV=dev ALPACA_ENV=sandbox uvicorn main:app --reload
npm run dev

Things to be aware of:
1. Email verified is set to true in CognitoClient.create_cognito_user()
2. Only Dev environment for creating cognito user
3. The realize filled orders only fills orders of latest transaction
    so if an order fails from a transaction A, then transaction B happens, then the orders from transaction A is filled, the system will not register because we will not look at transaction A anymore. So before each new transaction, we need to cancel failed orders from previous transactions
4. Need to do tests for backtest_model_portfolio_analytics_service
5. Should add a model_portfolio_snapshot_id to get exact latest model portfolio snapshot

Trade Execution Race Conditions:
1.
                                portfolio owner makes a change
| read in model portfolio ------------------------------------------- add user to model_portfolio_follower list  -change is lost for follower, follower is on outdated model portfolio snapshot

2. Two withdrawals can both validate against the same allocation equity before either
   request acquires the queue lock. Both transactions can then be queued, and their
   combined withdrawal can exceed the available portfolio equity. - handled by lock around queuing logic

3. `realize_filled_orders` can read an allocation while a trade execution or another
   reconciliation is updating it. Because `set_portfolio_allocation` replaces the whole
   DynamoDB item, the last writer can erase transaction-status, position-history, or
   cost-basis changes made by the other operation. - handled by lock around `realize_filled_orders`

4. The user trade lock has a 30-second lease and execution does not renew it. If broker
   calls or order submission take longer than the lease, another worker can acquire the
   expired lock and calculate orders from partially updated state while the first worker
   is still running.

5. A worker can set a transaction to `PROCESSING` and then crash before saving its broker
   orders or final `ORDERED` state. SQS redelivery will skip the message because the
   transaction is no longer `QUEUED`, leaving the transaction permanently stuck and its
   intended trade unexecuted.

6. A broker order can be submitted successfully but the worker can crash before the order
   record is written to DynamoDB. A retry cannot safely know whether to resubmit, so it can
   either duplicate the broker trade or leave an untracked order that reconciliation never
   applies to the allocation.

7. A model portfolio can be updated again while follower rebalance jobs from the previous
   update are still executing. Since the rebalance code reads the latest two snapshots at
   execution time instead of snapshots identified by the queued event, a delayed job can
   rebalance against the wrong pair of versions or apply the same latest change twice.

8. A withdraw-all can remove the follower after submitting liquidation orders while a
   portfolio-update flow is reading the follower list. The update flow can still enqueue or
   execute a rebalance for that former follower, reopening positions during liquidation.

9. The queuing service can persist a transaction as `QUEUED` and then crash before sending
   its SQS message. No worker will receive the transaction, so it remains queued indefinitely
   unless a separate recovery process republishes it.

10. Reconciliation can mark an order as filled in the order table and then crash before
    updating the allocation. On retry, that order is no longer returned as unfilled, so its
    fill may never be applied to position history or total cost basis.

11. Two reconciliation requests can read the same order as unfilled before either one saves
    it as filled. Both can then apply the fill to their in-memory allocation state; depending
    on write order, the result can contain a duplicated fill or discard other concurrent
    allocation changes.

12. When an execution worker cannot acquire the user trade lock, its exception handler can
    still call `_mark_transaction_failed`. That unlocked read-modify-write can mark a valid
    queued transaction as failed or overwrite allocation changes being made by the worker
    that currently owns the lock.

13. SQS can accept a message even if the sender times out or receives an ambiguous transport
    error. The queuing service can then mark the transaction `FAILED` while the message is
    delivered; the worker will skip it because it is no longer `QUEUED`.

14. Broker orders can partially fill while an execution worker is reading broker positions
    and calculating its deltas. The worker can submit orders based on the earlier quantities,
    causing an unintended over-trade, under-trade, or direction reversal.

15. Multiple portfolio updates can create several queued `UPDATE` transactions for the same
    follower. The update executor selects the latest queued transaction instead of receiving
    a specific transaction ID, so an older job can consume the newer transaction and leave
    its own transaction queued or apply updates out of order.


Frontend Prompt:
Recreate the current Baskt frontend as a React/Vite application in `frontend_v3/` at the repository root. The finished application must preserve the features and API behavior described below while presenting them as a professional, modern, intuitive investment product. Do not copy the visual design of an older frontend. Use `frontend_v3/public/BasktLogo.png` as the logo and use purple as Baskt's recognizable accent in the way Robinhood uses green, without making every surface purple.

## Source of truth

- Treat `backend/routes/` as the source of truth for HTTP methods and URLs.
- Treat `backend/schema/` as the source of truth for request and response bodies.
- When behavior is unclear, trace `routes -> services -> repositories/clients` and inspect the relevant `alpaca-py` models.
- Avoid backend changes unless a route or schema contains an obvious defect that prevents the frontend from working.
- The API base URL must come from `VITE_API_BASE_URL`, defaulting to `http://localhost:8000`.
- Send the Cognito ID token as `Authorization: Bearer <token>` on authenticated API requests.
- Configure Cognito through `VITE_COGNITO_REGION`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_REDIRECT_SIGN_IN`, and `VITE_COGNITO_REDIRECT_SIGN_OUT`.
- Define the browser `global` shim as `globalThis` if a dependency requires it; otherwise `amazon-cognito-identity-js` can throw `ReferenceError: global is not defined`.
- Do not run `npm install` or `npm run build`; I will do that.

## Application structure and navigation

Build authenticated pages for Home, Make a Baskt, My Baskts, Baskt Detail, and Transfers. Use a persistent application shell with the Baskt logo, sidebar navigation, current-page heading, and sign-out control. Signing out must clear all locally stored tokens and always return to the login screen. The Home page is the first page after authentication.

Create reusable components for:

- The application shell and navigation.
- Responsive equity/return charts.
- Position tables.
- Metric displays.
- Loading, empty, success, and error states.
- Shared API, authentication, session, date, currency, and percentage utilities.

Every request should have a useful loading state and a concise user-facing error. Empty lists and unavailable analytics should have deliberate empty states instead of blank or broken panels. The interface must work on desktop and mobile without clipped tables, controls, labels, or charts.

## Authentication and account creation

### Login

Authenticate directly with AWS Cognito using `amazon-cognito-identity-js`. Ask for email and password, save the ID/access/refresh tokens after success, and remember the last-used email. Support Cognito's `NEW_PASSWORD_REQUIRED` challenge in the same login flow by asking for a new permanent password and calling `completeNewPasswordChallenge`. Provide a link to Cognito's hosted forgot-password page and a button to begin signup.

### Signup

Implement signup as a clear multi-step flow: Contact, Identity, Disclosures, and Agreements. Submit the completed payload to `POST /accounts/create-baskt-account` using `CreateBasktAccountLifecycleRequest`.

- Contact includes email, phone, street address, optional unit, city, state, postal code, and country.
- Identity includes name, date of birth, tax ID/type, citizenship, birth country, tax residence, permanent-resident status, one or more funding sources, income ranges, liquid-net-worth ranges, and total-net-worth ranges.
- Ask for visa type, visa expiration, and departure date only when the user is neither a US citizen nor a permanent resident/green-card holder. Omit those keys otherwise.
- Funding sources must be represented in the submitted identity payload as a list.
- Disclosures include control-person, FINRA/exchange affiliation, politically exposed person, immediate-family exposure, employment status, and conditional employer details. Add small accessible explanation tooltips to unfamiliar disclosure terms.
- Require the account, customer, and margin agreements. Show links to the Alpaca agreement documents and submit each accepted agreement with `agreement`, an ISO `signed_at`, and `ip_address`.
- Ask for and confirm the Cognito password before final submission.
- Preserve entered values when moving backward and forward through the steps.
- After successful account creation, return automatically to login.

Use the enum values accepted by the backend/Alpaca models rather than friendly labels in request bodies. Display friendly labels in the UI.

## Home and account analytics

Fetch `GET /account-analytics` after login. Show current available cash/buying power and equity prominently. Display the account equity history for `1D`, `1W`, `1M`, `3M`, `1A`, and `ALL` when those periods are present in `equity_graph`.

The shared chart must:

- Show readable x-axis timestamps and y-axis values.
- Format account equity as USD with two decimal places.
- Use the minimum and maximum values in the selected series as the y-axis bounds; add a small fallback range only when every value is identical.
- Show intraday time labels for short periods and sensible date labels for longer periods.
- Resize without making the plot or labels unreadable.

## Make or update a Baskt

Load searchable assets from `GET /backtest/tradeable-fractionable-us-baskt-assets`. Search locally across all returned symbols, display every matching unselected result, and keep the query after an asset is selected. Users can add and remove positions, set a target percentage, and choose Long (`direction: 1`) or Short (`direction: -1`). Leverage is displayed as `1x` and cannot currently be edited.

Important weight contract: users edit weights as percentages, but every API request must send `target_weight` as a decimal fraction from `0` to `1`. For example, display `25%` and send `0.25`. The portfolio is fully allocated when decimal weights sum to `1.0`.

Let the user choose inclusive backtest start and end dates. Debounce backtests and call:

`GET /backtest?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&positions=<JSON>`

Only run the backtest when there is at least one valid position, the dates are valid, and target weights sum to `1.0`. Otherwise leave the result empty. Display the cumulative-return graph with visible axes and the returned final cumulative return, CAGR, annualized volatility, and leverage-adjusted direction tilt.

Create a portfolio with `POST /model-portfolios` and `CreateModelPortfolioRequest`. In update mode, prepopulate the latest saved positions and description, keep the portfolio name read-only, rerun the backtest as positions change, and save with `PUT /model-portfolios/{portfolio_id}` using `UpdateModelPortfolioRequest`.

## My Baskts

Fetch `GET /model-portfolios` and display the authenticated user's saved portfolios as a clean, scannable collection. Each item shows name and description and opens its detail page. The list response contains metadata; if created/updated dates are desired, fetch `GET /model-portfolios/{portfolio_id}` for each item in parallel and degrade gracefully to metadata if one detail request fails. Include a clear Create Baskt action and a useful empty state.

## Baskt detail

Load `GET /model-portfolios/{portfolio_id}` and show:

- Name, description, created date, updated date, and snapshot count.
- Latest positions with target weight, current weight, direction, and leverage. Convert decimal weights to percentages for display.
- Previous position snapshots in collapsible rows, newest first.
- An Update button only when the current Cognito `sub` equals `portfolio_owner_cognito_user_id`. It opens Make a Baskt in update mode.

Also load `GET /model-portfolios/{portfolio_id}/analytics`. Provide period controls for `1D`, `1W`, `1M`, `3M`, `1A`, and `all`. For the selected period, display the cumulative-return series and its final cumulative return, CAGR, annualized volatility, and leverage-adjusted direction tilt. Put the graph on the left and a compact, polished metric column on the right. Format return-series values according to the response contract and format decimal metrics such as CAGR and volatility as percentages.

Load allocation analytics from:

`GET /account-analytics/portfolios/{portfolio_id}/analytics?portfolio_owner_cognito_user_id=<owner_id>`

This request also realizes newly filled orders. When the response contains allocation values, show equity, profit/loss, and profit/loss percent together in one compact analytics bar. If the user has never invested and those values are null, hide the bar. Display transaction history with created time, filled time, transaction type, requested amount, filled amount, order-fill percent, and status. A null requested amount means Withdraw All.

Allow the user to fund the selected Baskt through:

- `POST /trade-execution/portfolios/{portfolio_id}/deposit`
- `POST /trade-execution/portfolios/{portfolio_id}/withdrawal`
- `POST /trade-execution/portfolios/{portfolio_id}/withdraw-all`

Deposit and withdrawal bodies include `portfolio_owner_cognito_user_id` and a positive numeric `amount`; withdraw-all includes only `portfolio_owner_cognito_user_id`. Refresh the portfolio and allocation analytics after a successful action.

## Transfers and funding relationships

The Transfers page manages at most one direct ACH relationship and one bank relationship. On initial load, request ACH relationships, banks, and transfer history in parallel, and render each section as soon as practical.

### ACH

- Load with `GET /accounts/ach-relationships`.
- Create with `POST /accounts/ach-relationship`.
- Replace with `PUT /accounts/ach-relationship`.
- Collect account owner name, account type (`CHECKING` or `SAVINGS`), account number, routing number, and optional nickname.
- When connected, show status and the saved details with a Change action. When absent, show a Connect ACH action/form.

### Bank

- Load with `GET /accounts/banks`.
- Create with `POST /accounts/bank`.
- Replace with `PUT /accounts/bank`.
- Collect name, bank code type, bank code, account number, and optional address fields defined by `CreateBasktBankRequest`.
- When connected, show status and the saved details with a Change action. When absent, show a Connect Bank action/form.

After an ACH or bank change, refresh only the relationship that changed when feasible. Do not display temporary success/failure banners inside the relationship cards or beneath the Deposit/Withdraw controls.

### Deposits, withdrawals, and history

Create account transfers with `POST /accounts/transfer` using `CreateBasktTransferRequest`. Ask for amount, direction (`INCOMING` for deposit or `OUTGOING` for withdrawal), and a connected source (`ACH` or `BANK`). Include `relationship_id` for ACH or `bank_id` for bank, and use the timing value accepted by the backend. Disable unavailable source options. For withdrawals, fetch/use the trade-account data needed to show the withdrawable amount and prevent submission above that amount.

Fetch paginated history with `GET /accounts/transfers?limit=<limit>&offset=<offset>`. Render direction, amount, status, source, and creation time. Use the response's `has_next` and `has_previous` fields for Previous/Next controls. Keep records inside the history panel at all viewport sizes.

## Visual and interaction direction

- Build the actual product interface, not a marketing landing page.
- Use a restrained purple accent alongside white, neutral gray, green for gains/success, and red for losses/errors.
- Favor clear full-width sections, compact metric bands, readable tables, segmented period controls, and purposeful whitespace.
- Avoid decorative gradient blobs, oversized marketing copy, excessive cards, nested cards, and pill-shaped text controls where standard controls are clearer.
- Keep card corner radii at 8px or less.
- Make charts large enough to inspect and keep their axes visible.
- Use consistent loading, disabled, error, success, and empty states. Prevent duplicate submissions.
- Preserve form state during multi-step and back/forward workflows.
- Keep all API payload names and enum values exactly aligned with the backend schemas.

