export function formatMoney(value) {
  if (value === null || value === undefined) return '--';
  const sign = value < 0 ? '-' : '';
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined) return '--';
  return value.toFixed(digits);
}
