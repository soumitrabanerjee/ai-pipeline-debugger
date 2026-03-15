// Auto-detects the host so the same build works locally and on the server.
// On piplex.in, API calls go through Nginx (/api/) — no port needed.
const HOST   = window.location.hostname
const isProd = HOST === 'piplex.in' || HOST === 'www.piplex.in'

export const API_URL     = isProd ? 'https://piplex.in/api'              : `http://${HOST}:8001`
export const INGEST_URL  = isProd ? `http://${HOST}:8000/ingest`          : `http://${HOST}:8000/ingest`
export const WEBHOOK_URL = isProd ? `http://${HOST}:8003/webhook`         : `http://${HOST}:8003/webhook`
export const AI_URL      = isProd ? `http://${HOST}:8002`                 : `http://${HOST}:8002`
