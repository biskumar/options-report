export function filterNextTwoMonths(expiries) {
  const now = new Date();
  const cutoff = new Date(now);
  cutoff.setMonth(cutoff.getMonth() + 2);
  return expiries.filter((e) => {
    const year = parseInt(e.slice(0, 4), 10);
    const month = parseInt(e.slice(4, 6), 10) - 1;
    const day = parseInt(e.slice(6, 8), 10);
    const date = new Date(year, month, day);
    return date >= now && date <= cutoff;
  });
}
