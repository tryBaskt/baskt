import { apiRequest } from "./api";
import { currency } from "./format";

export const TRADE_AMOUNT_MIN = 10;

function getDecimalPlaces(value) {
  const [, fraction = ""] = String(value).trim().split(".");
  return fraction.length;
}

export function showTradeValidationError(setError, message) {
  setError(message);
  window.alert(message);
}

export async function validateTradeAmount({ amount, validateCash = false }) {
  const amountText = String(amount).trim();
  const numericAmount = Number(amountText);

  if (!amountText || !Number.isFinite(numericAmount) || numericAmount <= 0) {
    throw new Error("Enter an amount greater than zero.");
  }

  if (getDecimalPlaces(amountText) > 2) {
    throw new Error("Trade amount must have at most two decimal places.");
  }

  const normalizedAmount = Number(numericAmount.toFixed(2));
  if (normalizedAmount < TRADE_AMOUNT_MIN) {
    throw new Error(`Trade amount must be at least ${currency(TRADE_AMOUNT_MIN)}.`);
  }

  if (validateCash) {
    const availableCash = Number(await apiRequest("/allocation_analytics/cash"));
    if (!Number.isFinite(availableCash)) {
      throw new Error("Could not validate available cash.");
    }
    if (normalizedAmount > availableCash) {
      throw new Error(
        `Trade amount ${currency(normalizedAmount)} exceeds available cash ${currency(availableCash)}.`
      );
    }
  }

  return normalizedAmount;
}
