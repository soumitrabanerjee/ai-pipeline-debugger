import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { formatTimestamp, sortErrors, sortRuns, truncateRunId, resolveTimezone, TIMEZONE_OPTIONS } from './dashboardUtils.js'

// ── resolveTimezone ────────────────────────────────────────────────────────────

describe('resolveTimezone', () => {
  test('returns the browser IANA timezone for "local"', () => {
    const result = resolveTimezone('local')
    const expected = Intl.DateTimeFormat().resolvedOptions().timeZone
    assert.equal(result, expected)
  })

  test('returns the browser IANA timezone for null', () => {
    const result = resolveTimezone(null)
    const expected = Intl.DateTimeFormat().resolvedOptions().timeZone
    assert.equal(result, expected)
  })

  test('passes through an explicit IANA timezone unchanged', () => {
    assert.equal(resolveTimezone('UTC'), 'UTC')
    assert.equal(resolveTimezone('Asia/Kolkata'), 'Asia/Kolkata')
    assert.equal(resolveTimezone('America/New_York'), 'America/New_York')
  })
})

// ── TIMEZONE_OPTIONS ───────────────────────────────────────────────────────────

describe('TIMEZONE_OPTIONS', () => {
  test('first option is "local"', () => {
    assert.equal(TIMEZONE_OPTIONS[0].value, 'local')
  })

  test('includes UTC', () => {
    assert.ok(TIMEZONE_OPTIONS.some(o => o.value === 'UTC'))
  })

  test('every option has a non-empty label and value', () => {
    for (const opt of TIMEZONE_OPTIONS) {
      assert.ok(opt.label.length > 0, `empty label: ${JSON.stringify(opt)}`)
      assert.ok(opt.value.length > 0, `empty value: ${JSON.stringify(opt)}`)
    }
  })
})

// ── formatTimestamp ────────────────────────────────────────────────────────────

describe('formatTimestamp — null / invalid inputs', () => {
  test('returns null for null', ()      => assert.equal(formatTimestamp(null), null))
  test('returns null for undefined', () => assert.equal(formatTimestamp(undefined), null))
  test('returns null for invalid date string', () =>
    assert.equal(formatTimestamp('not-a-date'), null))
})

describe('formatTimestamp — timezone abbreviation is appended', () => {
  test('UTC timestamps include "UTC" abbreviation', () => {
    const result = formatTimestamp('2026-03-09T10:00:00Z', 'UTC')
    assert.ok(result !== null)
    assert.ok(result.includes('UTC'), `expected "UTC" in "${result}"`)
  })

  test('IST timestamps include timezone info (IST or GMT+5:30)', () => {
    const result = formatTimestamp('2026-03-09T10:00:00Z', 'Asia/Kolkata')
    assert.ok(result !== null)
    // Browsers show "IST"; Node.js with limited ICU shows "GMT+5:30" — both are correct
    assert.ok(
      result.includes('IST') || result.includes('GMT+5:30'),
      `expected "IST" or "GMT+5:30" in "${result}"`
    )
  })

  test('America/New_York timestamps include EST or EDT', () => {
    const result = formatTimestamp('2026-01-15T10:00:00Z', 'America/New_York')
    assert.ok(result !== null)
    assert.ok(
      result.includes('EST') || result.includes('EDT'),
      `expected "EST" or "EDT" in "${result}"`
    )
  })
})

describe('formatTimestamp — same day vs different day (UTC)', () => {
  test('a timestamp from a past date shows date · time TZ', () => {
    const result = formatTimestamp('2026-01-01T00:00:00Z', 'UTC')
    assert.ok(result !== null)
    assert.ok(result.includes('·'), `expected "·" separator, got: "${result}"`)
    assert.ok(result.includes('UTC'), `expected "UTC" in "${result}"`)
  })

  test('time portion is present in the output', () => {
    const result = formatTimestamp('2026-01-01T14:30:00Z', 'UTC')
    assert.ok(result !== null)
    // Should contain a colon from the time part
    assert.ok(result.includes(':'), `expected colon in time, got: "${result}"`)
  })
})

describe('formatTimestamp — same date in different timezones', () => {
  test('2026-03-10T00:30:00Z is Mar 9 in UTC-5 (New York) but Mar 10 in UTC', () => {
    const utcResult = formatTimestamp('2026-03-10T00:30:00Z', 'UTC')
    const nyResult  = formatTimestamp('2026-03-10T00:30:00Z', 'America/New_York')
    // UTC: March 10, no "·" if today is March 10, but ISO date differs from NY
    // NY: 00:30 UTC = 19:30 Mar 9 EST → should show "Mar 9 · ..."
    assert.ok(nyResult !== null)
    assert.ok(nyResult.includes('Mar 9'), `NY result should show Mar 9, got: "${nyResult}"`)
    assert.ok(utcResult !== null)
    // UTC version should NOT show "Mar 9"
    assert.ok(!utcResult.includes('Mar 9'), `UTC result should not show Mar 9, got: "${utcResult}"`)
  })
})

// ── sortErrors ─────────────────────────────────────────────────────────────────

const makeError = (pipeline, detectedAt) => ({
  pipeline,
  error: 'SomeError',
  rootCause: 'cause',
  fix: 'fix',
  detectedAt,
})

describe('sortErrors — by timestamp (newest first)', () => {
  test('sorts newer timestamps before older ones', () => {
    const errors = [
      makeError('pipe-a', '2026-03-10T08:00:00Z'),
      makeError('pipe-b', '2026-03-10T12:00:00Z'),
      makeError('pipe-c', '2026-03-10T06:00:00Z'),
    ]
    const sorted = sortErrors(errors, 'timestamp')
    assert.equal(sorted[0].pipeline, 'pipe-b')
    assert.equal(sorted[1].pipeline, 'pipe-a')
    assert.equal(sorted[2].pipeline, 'pipe-c')
  })

  test('pushes null detectedAt to the end', () => {
    const errors = [
      makeError('pipe-a', null),
      makeError('pipe-b', '2026-03-10T10:00:00Z'),
    ]
    const sorted = sortErrors(errors, 'timestamp')
    assert.equal(sorted[0].pipeline, 'pipe-b')
    assert.equal(sorted[1].pipeline, 'pipe-a')
  })

  test('handles all null detectedAt without throwing', () => {
    const sorted = sortErrors([makeError('a', null), makeError('b', null)], 'timestamp')
    assert.equal(sorted.length, 2)
  })

  test('does not mutate the original array', () => {
    const errors = [
      makeError('pipe-a', '2026-03-10T08:00:00Z'),
      makeError('pipe-b', '2026-03-10T12:00:00Z'),
    ]
    const original = [...errors]
    sortErrors(errors, 'timestamp')
    assert.deepEqual(errors, original)
  })
})

describe('sortErrors — by pipeline name (A→Z)', () => {
  test('sorts alphabetically ascending', () => {
    const errors = [
      makeError('zebra-pipeline', '2026-03-10T10:00:00Z'),
      makeError('alpha-pipeline', '2026-03-10T08:00:00Z'),
      makeError('mango-pipeline', '2026-03-10T09:00:00Z'),
    ]
    const sorted = sortErrors(errors, 'pipeline')
    assert.equal(sorted[0].pipeline, 'alpha-pipeline')
    assert.equal(sorted[1].pipeline, 'mango-pipeline')
    assert.equal(sorted[2].pipeline, 'zebra-pipeline')
  })

  test('returns empty array for empty input', () => {
    assert.deepEqual(sortErrors([], 'pipeline'), [])
    assert.deepEqual(sortErrors([], 'timestamp'), [])
  })
})

// ── sortRuns ───────────────────────────────────────────────────────────────────

const makeRun = (runId, createdAt, status = 'Success') => ({ runId, createdAt, status })

describe('sortRuns — newest first', () => {
  test('sorts newer runs before older ones', () => {
    const runs = [
      makeRun('run-a', '2026-03-10T08:00:00Z'),
      makeRun('run-b', '2026-03-10T12:00:00Z'),
      makeRun('run-c', '2026-03-10T06:00:00Z'),
    ]
    const sorted = sortRuns(runs)
    assert.equal(sorted[0].runId, 'run-b')
    assert.equal(sorted[1].runId, 'run-a')
    assert.equal(sorted[2].runId, 'run-c')
  })

  test('pushes null createdAt to the end', () => {
    const runs = [
      makeRun('run-a', null),
      makeRun('run-b', '2026-03-10T10:00:00Z'),
    ]
    const sorted = sortRuns(runs)
    assert.equal(sorted[0].runId, 'run-b')
    assert.equal(sorted[1].runId, 'run-a')
  })

  test('handles all-null createdAt without throwing', () => {
    const sorted = sortRuns([makeRun('a', null), makeRun('b', null)])
    assert.equal(sorted.length, 2)
  })

  test('returns empty array for empty input', () => {
    assert.deepEqual(sortRuns([]), [])
  })

  test('does not mutate the original array', () => {
    const runs = [
      makeRun('run-a', '2026-03-10T08:00:00Z'),
      makeRun('run-b', '2026-03-10T12:00:00Z'),
    ]
    const original = [...runs]
    sortRuns(runs)
    assert.deepEqual(runs, original)
  })

  test('single run is returned unchanged', () => {
    const runs = [makeRun('only-run', '2026-03-10T10:00:00Z')]
    assert.deepEqual(sortRuns(runs), runs)
  })

  test('Failed runs sort correctly alongside Success runs', () => {
    const runs = [
      makeRun('run-fail', '2026-03-10T09:00:00Z', 'Failed'),
      makeRun('run-ok',   '2026-03-10T11:00:00Z', 'Success'),
    ]
    const sorted = sortRuns(runs)
    assert.equal(sorted[0].runId, 'run-ok')
    assert.equal(sorted[1].runId, 'run-fail')
  })
})

// ── truncateRunId ─────────────────────────────────────────────────────────────

describe('truncateRunId', () => {
  test('short id is returned unchanged', () => {
    assert.equal(truncateRunId('run-abc'), 'run-abc')
  })

  test('id exactly at maxLen is returned unchanged', () => {
    const id = 'a'.repeat(20)
    assert.equal(truncateRunId(id), id)
  })

  test('id longer than maxLen is truncated with ellipsis', () => {
    const id = 'a'.repeat(30)
    const result = truncateRunId(id)
    assert.ok(result.endsWith('…'), `expected ellipsis, got: "${result}"`)
    assert.equal(result.length, 21) // 20 chars + '…'
  })

  test('custom maxLen is respected', () => {
    const result = truncateRunId('abcdefghij', 5)
    assert.equal(result, 'abcde…')
  })

  test('empty string returns empty string', () => {
    assert.equal(truncateRunId(''), '')
  })

  test('null/undefined returns empty string', () => {
    assert.equal(truncateRunId(null), '')
    assert.equal(truncateRunId(undefined), '')
  })
})
