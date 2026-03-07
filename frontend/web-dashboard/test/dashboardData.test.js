import test from 'node:test'
import assert from 'node:assert/strict'
import { filterDashboardItems } from '../src/components/dashboardData.js'

test('returns all entries for empty query', () => {
  const result = filterDashboardItems('')

  assert.equal(result.pipelines.length, 3)
  assert.equal(result.errors.length, 2)
})

test('filters by schema query', () => {
  const result = filterDashboardItems('schema')

  assert.equal(result.pipelines.length, 0)
  assert.equal(result.errors.length, 1)
  assert.equal(result.errors[0].error, 'SchemaMismatch')
})

test('filters by pipeline name', () => {
  const result = filterDashboardItems('customer_etl')

  assert.equal(result.pipelines.length, 1)
  assert.equal(result.errors.length, 1)
  assert.equal(result.pipelines[0].name, 'customer_etl')
})

test('query is case-insensitive and trimmed', () => {
  const result = filterDashboardItems('   FAILED   ')

  assert.equal(result.pipelines.length, 2)
  assert.equal(result.errors.length, 0)
})
