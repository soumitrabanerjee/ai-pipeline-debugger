/**
 * Timezone options shown in the dashboard selector.
 * 'local' is a sentinel that resolves to the browser's own timezone.
 */
export const TIMEZONE_OPTIONS = [
  { label: 'Local',          value: 'local' },
  { label: 'UTC',            value: 'UTC' },
  { label: 'IST (India)',    value: 'Asia/Kolkata' },
  { label: 'EST (New York)', value: 'America/New_York' },
  { label: 'PST (LA)',       value: 'America/Los_Angeles' },
  { label: 'GMT (London)',   value: 'Europe/London' },
  { label: 'JST (Tokyo)',    value: 'Asia/Tokyo' },
  { label: 'SGT (Singapore)',value: 'Asia/Singapore' },
]

/** Resolve 'local' sentinel to the browser's IANA timezone string. */
export function resolveTimezone(tz) {
  return (!tz || tz === 'local')
    ? Intl.DateTimeFormat().resolvedOptions().timeZone
    : tz
}

/**
 * Format an ISO-8601 timestamp for display in error cards.
 *
 * @param {string|null} iso      - ISO-8601 string or null
 * @param {string}      timezone - IANA timezone or 'local' (default)
 * @returns {string|null}
 *
 * Examples (in UTC+5:30 / IST):
 *   same day  → "02:34:51 PM IST"
 *   other day → "Mar 9 · 02:34:51 PM IST"
 */
export function formatTimestamp(iso, timezone = 'local') {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null

  const tz = resolveTimezone(timezone)

  // Compare calendar dates in the target timezone using ISO date strings (YYYY-MM-DD)
  const toDateStr = (dt) =>
    dt.toLocaleDateString('en-CA', { timeZone: tz }) // yields "2026-03-10"
  const sameDay = toDateStr(d) === toDateStr(new Date())

  // Get the timezone abbreviation (e.g. "IST", "UTC", "EST")
  const tzAbbr = new Intl.DateTimeFormat(undefined, { timeZone: tz, timeZoneName: 'short' })
    .formatToParts(d)
    .find(p => p.type === 'timeZoneName')?.value ?? tz

  const time = d.toLocaleTimeString(undefined, {
    timeZone: tz,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  if (sameDay) return `${time} ${tzAbbr}`
  const date = d.toLocaleDateString(undefined, { timeZone: tz, month: 'short', day: 'numeric' })
  return `${date} · ${time} ${tzAbbr}`
}

/**
 * Sort error items.
 * @param {Array}                   errors
 * @param {'timestamp'|'pipeline'}  sortKey
 */
export function sortErrors(errors, sortKey) {
  return [...errors].sort((a, b) => {
    if (sortKey === 'pipeline') return a.pipeline.localeCompare(b.pipeline)
    if (!a.detectedAt && !b.detectedAt) return 0
    if (!a.detectedAt) return 1
    if (!b.detectedAt) return -1
    return b.detectedAt.localeCompare(a.detectedAt)
  })
}

/**
 * Sort pipeline run items newest-first by createdAt.
 * Runs with no createdAt are pushed to the end.
 *
 * @param {Array} runs  - Array of { runId, status, createdAt }
 * @returns {Array}     - New sorted array (original is not mutated)
 */
export function sortRuns(runs) {
  return [...runs].sort((a, b) => {
    if (!a.createdAt && !b.createdAt) return 0
    if (!a.createdAt) return 1
    if (!b.createdAt) return -1
    return b.createdAt.localeCompare(a.createdAt)
  })
}

/**
 * Truncate a run ID for compact display.
 * Shows the first `maxLen` characters followed by '…' when longer.
 *
 * @param {string} runId
 * @param {number} maxLen  - default 20
 * @returns {string}
 */
export function truncateRunId(runId, maxLen = 20) {
  if (!runId) return ''
  return runId.length > maxLen ? `${runId.slice(0, maxLen)}…` : runId
}
