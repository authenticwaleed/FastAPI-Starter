/**
 * Rendering money without ever making it a number.
 *
 * The API sends every amount as a decimal *string* -- `"19.99"` -- and it
 * does that on purpose: a price parsed into a float is 19.989999999999998,
 * and a total built from three of those is wrong in a way nobody can find
 * afterwards. So nothing here calls `Number`, `parseFloat`, or arithmetic
 * of any kind.
 *
 * `Intl.NumberFormat` accepts a string directly, which is exactly the
 * problem that addition to the spec was made for: the digits are formatted
 * as given, with no intermediate binary float. Where it is unavailable the
 * fallback below groups the integer part by hand, still without parsing.
 *
 * Pure, so a client component can import it.
 */

/** Thousands separators, applied to a run of digits. */
function grouped(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function byHand(amount: string, currency: string | null): string {
  const negative = amount.startsWith("-");
  const bare = negative ? amount.slice(1) : amount;
  const [whole, fraction] = bare.split(".");

  const body = fraction ? `${grouped(whole)}.${fraction}` : grouped(whole);
  const signed = negative ? `-${body}` : body;

  return currency ? `${signed} ${currency}` : signed;
}

/**
 * An amount, as somebody would read it.
 *
 * `null` for an amount the API did not send, which is not the same as
 * zero: a product with no price of its own takes its variant's, and a
 * screen printing "0.00" there would be quoting a customer a free item.
 */
export function formatMoney(
  amount: string | null | undefined,
  currency: string | null | undefined,
): string | null {
  if (amount === null || amount === undefined || amount === "") return null;

  // A guard, not a parse. Anything unexpected is shown as it arrived
  // rather than mangled into something plausible.
  if (!/^-?\d+(\.\d+)?$/.test(amount)) return amount;

  if (!currency) return byHand(amount, null);

  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      // The API stores two decimal places. Saying so stops a currency
      // whose convention is three from silently gaining a digit the
      // business never entered.
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      // The string overload. Passing `amount` unparsed is the whole point.
    }).format(amount as unknown as number);
  } catch {
    // An unknown currency code, or a runtime without the string overload.
    return byHand(amount, currency);
  }
}

/** The same, with a dash where there is no amount, for a table cell. */
export function money(
  amount: string | null | undefined,
  currency: string | null | undefined,
): string {
  return formatMoney(amount, currency) ?? "—";
}
