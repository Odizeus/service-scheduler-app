const CUSTOMER_PALETTE = [
  { bg: "rgba(59, 130, 246, 0.18)", border: "rgba(96, 165, 250, 0.62)", text: "#bfdbfe", dot: "#60a5fa" },
  { bg: "rgba(16, 185, 129, 0.18)", border: "rgba(52, 211, 153, 0.62)", text: "#bbf7d0", dot: "#34d399" },
  { bg: "rgba(245, 158, 11, 0.18)", border: "rgba(251, 191, 36, 0.62)", text: "#fde68a", dot: "#fbbf24" },
  { bg: "rgba(168, 85, 247, 0.18)", border: "rgba(192, 132, 252, 0.62)", text: "#e9d5ff", dot: "#c084fc" },
  { bg: "rgba(236, 72, 153, 0.18)", border: "rgba(244, 114, 182, 0.62)", text: "#fbcfe8", dot: "#f472b6" },
  { bg: "rgba(20, 184, 166, 0.18)", border: "rgba(45, 212, 191, 0.62)", text: "#ccfbf1", dot: "#2dd4bf" },
  { bg: "rgba(249, 115, 22, 0.18)", border: "rgba(251, 146, 60, 0.62)", text: "#fed7aa", dot: "#fb923c" },
  { bg: "rgba(99, 102, 241, 0.18)", border: "rgba(129, 140, 248, 0.62)", text: "#c7d2fe", dot: "#818cf8" },
  { bg: "rgba(34, 197, 94, 0.18)", border: "rgba(74, 222, 128, 0.62)", text: "#dcfce7", dot: "#4ade80" },
  { bg: "rgba(244, 63, 94, 0.18)", border: "rgba(251, 113, 133, 0.62)", text: "#ffe4e6", dot: "#fb7185" },
  { bg: "rgba(6, 182, 212, 0.18)", border: "rgba(34, 211, 238, 0.62)", text: "#cffafe", dot: "#22d3ee" },
  { bg: "rgba(217, 70, 239, 0.18)", border: "rgba(232, 121, 249, 0.62)", text: "#fae8ff", dot: "#e879f9" },
];

const normalize = (value = "") =>
  String(value)
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");

export function customerColorKey(customer = {}) {
  return [
    normalize(customer.full_name),
    normalize(customer.address),
    normalize(customer.city),
    normalize(customer.zip),
  ]
    .filter(Boolean)
    .join("|");
}

export function getCustomerColor(customer = {}) {
  const key = customerColorKey(customer) || normalize(customer.email) || normalize(customer.phone) || "unknown-customer";
  let hash = 0;

  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }

  return CUSTOMER_PALETTE[hash % CUSTOMER_PALETTE.length];
}

export function customerColorStyle(customer = {}) {
  const color = getCustomerColor(customer);
  return {
    backgroundColor: color.bg,
    borderColor: color.border,
    color: color.text,
    "--customer-color": color.dot,
  };
}

export function customerDotStyle(customer = {}) {
  const color = getCustomerColor(customer);
  return {
    backgroundColor: color.dot,
    boxShadow: `0 0 12px ${color.dot}66`,
  };
}
