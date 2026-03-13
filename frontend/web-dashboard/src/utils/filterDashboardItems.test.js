import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

// Import the function under test via a relative path from utils/ to components/
import { filterDashboardItems } from '../components/dashboardData.js'

const makePipeline = (name, status) => ({ name, status, lastRun: '1m ago' })
const makeError    = (pipeline, error = 'SomeError') => ({
  pipeline, error, rootCause: 'some cause', fix: 'some fix', detectedAt: null,
})

// ── Active-failure filter ──────────────────────────────────────────────────────

describe('filterDashboardItems — suppresses errors for fixed pipelines', () => {

  test('errors for a Failed pipeline are shown', () => {
    const pipelines = [makePipeline('pipe-a', 'Failed')]
    const errors    = [makeError('pipe-a')]
    const { errors: result } = filterDashboardItems('', pipelines, errors)
    assert.equal(result.length, 1)
    assert.equal(result[0].pipeline, 'pipe-a')
  })

  test('errors for a Success pipeline are hidden', () => {
    const pipelines = [makePipeline('pipe-a', 'Success')]
    const errors    = [makeError('pipe-a')]
    const { errors: result } = filterDashboardItems('', pipelines, errors)
    assert.equal(result.length, 0)
  })

  test('only errors for Failed pipelines survive when mixed', () => {
    const pipelines = [
      makePipeline('pipe-fail',    'Failed'),
      makePipeline('pipe-success', 'Success'),
    ]
    const errors = [
      makeError('pipe-fail'),
      makeError('pipe-success'),
    ]
    const { errors: result } = filterDashboardItems('', pipelines, errors)
    assert.equal(result.length, 1)
    assert.equal(result[0].pipeline, 'pipe-fail')
  })

  test('returns empty errors when all pipelines are Success', () => {
    const pipelines = [makePipeline('a', 'Success'), makePipeline('b', 'Success')]
    const errors    = [makeError('a'), makeError('b')]
    const { errors: result } = filterDashboardItems('', pipelines, errors)
    assert.equal(result.length, 0)
  })

  test('errors with no matching pipeline entry are hidden', () => {
    const pipelines = [makePipeline('pipe-a', 'Failed')]
    const errors    = [makeError('pipe-orphan')]
    const { errors: result } = filterDashboardItems('', pipelines, errors)
    assert.equal(result.length, 0)
  })

})

// ── Search + active-failure filter combined ────────────────────────────────────

describe('filterDashboardItems — search respects active-failure filter', () => {

  test('search does not resurface errors from a fixed pipeline', () => {
    const pipelines = [makePipeline('billing', 'Success')]
    const errors    = [makeError('billing', 'OutOfMemory')]
    // searching for "billing" should NOT bring back its errors
    const { errors: result } = filterDashboardItems('billing', pipelines, errors)
    assert.equal(result.length, 0)
  })

  test('search returns matching errors only for Failed pipelines', () => {
    const pipelines = [
      makePipeline('billing',   'Success'),
      makePipeline('analytics', 'Failed'),
    ]
    const errors = [
      makeError('billing',   'OutOfMemory'),
      makeError('analytics', 'OutOfMemory'),
    ]
    const { errors: result } = filterDashboardItems('OutOfMemory', pipelines, errors)
    assert.equal(result.length, 1)
    assert.equal(result[0].pipeline, 'analytics')
  })

})

// ── Pipeline list is unaffected by the error filter ───────────────────────────

describe('filterDashboardItems — pipeline list unchanged by error filter', () => {

  test('Success pipelines still appear in the pipeline list', () => {
    const pipelines = [makePipeline('pipe-a', 'Success'), makePipeline('pipe-b', 'Failed')]
    const { pipelines: result } = filterDashboardItems('', pipelines, [])
    assert.equal(result.length, 2)
  })

})
