// Auto-detects the host so the same build works locally and on the server
const HOST = window.location.hostname

export const API_URL     = `http://${HOST}:8001`
export const INGEST_URL  = `http://${HOST}:8000/ingest`
export const WEBHOOK_URL = `http://${HOST}:8003/webhook`
export const AI_URL      = `http://${HOST}:8002`
