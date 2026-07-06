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