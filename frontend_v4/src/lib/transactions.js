function transactionTime(transaction) {
  const timestamp = new Date(transaction?.created_at || "").getTime();
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY;
}

export function sortTransactionsNewestFirst(transactions = []) {
  return [...transactions].sort(
    (left, right) => transactionTime(right) - transactionTime(left)
  );
}
