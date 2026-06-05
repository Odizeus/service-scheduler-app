// Lightweight date helpers (avoid date-fns timezone confusion)
export function ymd(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function monthLabel(y, m) {
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

export function isoWeekday(date) {
  // JS getDay: 0=Sun..6=Sat → ISO 1=Mon..7=Sun
  const d = date.getDay();
  return d === 0 ? 7 : d;
}

export function allowedMonths(today = new Date()) {
  const cur = { y: today.getFullYear(), m: today.getMonth() + 1 };
  const nxt =
    cur.m === 12 ? { y: cur.y + 1, m: 1 } : { y: cur.y, m: cur.m + 1 };
  return [cur, nxt];
}

export function fmtTimeBlock(tb) {
  // "10:00-12:00" → "10:00 AM – 12:00 PM" simple 12h
  if (!tb || !tb.includes("-")) return tb;
  const [a, b] = tb.split("-");
  return `${to12(a)} – ${to12(b)}`;
}
function to12(hhmm) {
  const [h, m] = hhmm.split(":").map((x) => parseInt(x, 10));
  const am = h < 12;
  const h12 = ((h + 11) % 12) + 1;
  return `${h12}:${String(m).padStart(2, "0")} ${am ? "AM" : "PM"}`;
}
