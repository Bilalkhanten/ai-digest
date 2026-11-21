/**
 * Remove things that look like secrets from text before it is stored or shown.
 * Conservative on purpose: a false positive hides a word, a false negative leaks a credential.
 */
const RULES: Array<[RegExp, string]> = [
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, "[REDACTED:jwt]"],
  [/\bBearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, "Bearer [REDACTED]"],
  [/\b(AKIA|ASIA)[A-Z0-9]{16}\b/g, "[REDACTED:aws-key]"],
  [/\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, "[REDACTED:github-token]"],
  [/\b(sk|pk)-[A-Za-z0-9_-]{16,}\b/g, "[REDACTED:api-key]"],
  [
    /\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)(["']?\s*[:=]\s*["']?)([^\s"',;&]{3,})/gi,
    "$1$2[REDACTED]",
  ],
  [/(:\/\/[^\s/:@]+:)([^\s/@]{3,})(@)/g, "$1[REDACTED]$3"],
];

export function redact(text: string): string {
  return RULES.reduce((acc, [re, replacement]) => acc.replace(re, replacement), text);
}

/** Redact, collapse whitespace and cap the length, for one-line summaries. */
export function cleanLine(text: string, max = 240): string {
  const flat = redact(text).replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 3).trimEnd()}...` : flat;
}
