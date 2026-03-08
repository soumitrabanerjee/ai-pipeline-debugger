export const pipelines = [
  { name: 'customer_etl', status: 'Failed', lastRun: '2 min ago' },
  { name: 'billing_pipeline', status: 'Success', lastRun: '10 min ago' },
  { name: 'analytics_daily', status: 'Failed', lastRun: '30 min ago' }
]

export const errors = [
  {
    pipeline: 'customer_etl',
    error: 'ExecutorLostFailure',
    rootCause: 'Spark executor memory exceeded',
    fix: 'Increase spark.executor.memory to 8g'
  },
  {
    pipeline: 'analytics_daily',
    error: 'SchemaMismatch',
    rootCause: 'Column type mismatch in parquet',
    fix: 'Update schema or cast column types'
  }
]

export function filterDashboardItems(query, currentPipelines = pipelines, currentErrors = errors) {
  const normalizedQuery = query.trim().toLowerCase()

  if (!normalizedQuery) {
    return { pipelines: currentPipelines, errors: currentErrors }
  }

  const filteredPipelines = currentPipelines.filter((pipeline) => {
    return (
      pipeline.name.toLowerCase().includes(normalizedQuery) ||
      pipeline.status.toLowerCase().includes(normalizedQuery) ||
      pipeline.lastRun.toLowerCase().includes(normalizedQuery)
    )
  })

  const filteredErrors = currentErrors.filter((item) => {
    return (
      item.pipeline.toLowerCase().includes(normalizedQuery) ||
      item.error.toLowerCase().includes(normalizedQuery) ||
      item.rootCause.toLowerCase().includes(normalizedQuery) ||
      item.fix.toLowerCase().includes(normalizedQuery)
    )
  })

  return { pipelines: filteredPipelines, errors: filteredErrors }
}
