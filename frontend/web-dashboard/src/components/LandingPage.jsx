import { useEffect, useRef, useState } from 'react'
import PiPlexLogo from './PiPlexLogo'

// ── Terminal animation lines ────────────────────────────────────────────────
const TERMINAL_LINES = [
  { delay: 0,    type: 'cmd',     text: '$ bash services/spark-jobs/run_student_analytics.sh' },
  { delay: 800,  type: 'info',    text: '[runner] Starting log agent watching /tmp/spark-logs...' },
  { delay: 1400, type: 'info',    text: '[analytics] Stage 1 — loading student enrollment records' },
  { delay: 2000, type: 'info',    text: '[analytics] Stage 2 — loading course grade records' },
  { delay: 2600, type: 'info',    text: '[analytics] Stage 3 — joining datasets' },
  { delay: 3200, type: 'info',    text: '[analytics] Stage 4 — applying letter grade UDF (lazy)' },
  { delay: 3800, type: 'info',    text: '[analytics] Stage 5 — collecting results to driver...' },
  { delay: 4400, type: 'error',   text: 'ERROR TaskSetManager: Task 0 in stage 19.0 failed 1 times' },
  { delay: 4800, type: 'error',   text: "PythonException: ValueError: could not convert string to float: 'N/A'" },
  { delay: 5400, type: 'divider', text: '' },
  { delay: 5600, type: 'ai',      text: '🤖  AI Engine analysing failure...' },
  { delay: 7200, type: 'fix',     text: '✓  Root cause: UDF score_to_letter receives corrupt values' },
  { delay: 7800, type: 'fix',     text: '✓  Fix: filter nulls before collect() or add try/except in UDF' },
  { delay: 8400, type: 'fix',     text: '✓  Slack alert sent · Dashboard updated · Run logged' },
]

function TerminalWindow() {
  const [visibleCount, setVisibleCount] = useState(0)
  const [tick, setTick] = useState(0)
  const containerRef = useRef(null)

  useEffect(() => {
    setVisibleCount(0)
    const timers = TERMINAL_LINES.map((line, i) =>
      setTimeout(() => setVisibleCount(i + 1), line.delay)
    )
    const loop = setTimeout(() => setTick(t => t + 1), 11000)
    return () => { timers.forEach(clearTimeout); clearTimeout(loop) }
  }, [tick])

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [visibleCount])

  const colorMap = {
    cmd: '#94a3b8', info: '#64748b', error: '#f87171',
    divider: '#1e293b', ai: '#818cf8', fix: '#34d399',
  }

  return (
    <div className="lp-terminal">
      <div className="lp-terminal-bar">
        <span className="lp-dot lp-dot-red" />
        <span className="lp-dot lp-dot-yellow" />
        <span className="lp-dot lp-dot-green" />
        <span className="lp-terminal-title">spark-student-analytics — PiPlex</span>
      </div>
      <div className="lp-terminal-body" ref={containerRef}>
        {TERMINAL_LINES.slice(0, visibleCount).map((line, i) =>
          line.type === 'divider' ? (
            <div key={i} className="lp-terminal-divider" />
          ) : (
            <div key={i} className="lp-terminal-line" style={{ color: colorMap[line.type] }}>
              {line.type === 'cmd' && <span className="lp-prompt">❯ </span>}
              {line.text}
              {i === visibleCount - 1 && <span className="lp-cursor" />}
            </div>
          )
        )}
      </div>
    </div>
  )
}

const FEATURES = [
  { icon: '📡', title: 'Universal Log Collection',  desc: 'Captures failures from Airflow DAGs, PySpark jobs, and any HTTP source. Webhook collector translates every format into one standard event — containerised and always on.', tag: 'webhook_collector · agent.py · Docker' },
  { icon: '🤖', title: 'AI Root Cause Analysis',    desc: 'Every error is analysed by Claude (claude-haiku-4-5) via the Anthropic API. Gets a structured root cause, fix recommendation, and confidence score in seconds — no manual triage.', tag: 'Claude claude-haiku-4-5 · Anthropic API' },
  { icon: '⚡', title: 'Async Queue Processing',    desc: 'Ingestion returns 202 immediately. Redis Streams + consumer group handle AI analysis in the background. No pipeline blocked waiting for LLM inference.', tag: 'Redis Streams · FastAPI' },
  { icon: '🔔', title: 'Slack Alerting',             desc: 'Block Kit messages fire after every AI analysis. Includes the pipeline name, root cause, and suggested fix — right where your team already works.', tag: 'Slack Block Kit' },
  { icon: '📊', title: 'Live Dashboard',             desc: 'Auto-refreshing React UI shows all pipelines, latest errors, AI diagnoses, and per-pipeline run history. Polls every 5 seconds — always current.', tag: 'React · Vite · FastAPI' },
  { icon: '🗄️', title: 'Error Deduplication',       desc: "Upserts by (pipeline_name, error_type) so repeated flaps don't spam the DB. PostgreSQL stores metadata; run history gives a full audit trail.", tag: 'PostgreSQL · SQLAlchemy' },
]

const STEPS = [
  { num: '01', title: 'Pipeline emits a failure', desc: 'Airflow on_failure_callback or Spark job POSTs to the webhook collector (port 8003). It translates the payload and forwards it to the ingestion API.' },
  { num: '02', title: 'Event queued instantly',   desc: 'Ingestion API returns 202, saves the run to PostgreSQL, and publishes to Redis Streams. Your pipeline is never blocked.' },
  { num: '03', title: 'Claude analyses the error',desc: 'Queue worker consumes the event, parses the log, then sends a structured prompt to Claude (claude-haiku-4-5) for root cause + fix recommendation.' },
  { num: '04', title: 'Results everywhere',        desc: 'Dashboard updates in real time, Slack alert fires, PostgreSQL stores the analysis with full run history for every pipeline.' },
]

const INTEGRATIONS = [
  { name: 'Apache Airflow',    icon: '🌬️' },
  { name: 'PySpark',           icon: '⚡' },
  { name: 'Claude / Anthropic',icon: '🤖' },
  { name: 'Redis Streams',     icon: '🔴' },
  { name: 'PostgreSQL',        icon: '🐘' },
  { name: 'Slack',             icon: '💬' },
]

export default function LandingPage({ onEnterDashboard, onLogin, onSignOut, user }) {
  return (
    <div className="lp-root">

      <nav className="lp-nav">
        <div className="lp-nav-inner">
          <div className="lp-logo">
            <div className="lp-logo-img-wrap">
              <PiPlexLogo height={36} />
            </div>
          </div>
          <div className="lp-nav-links">
            <a href="#features" className="lp-nav-link">Features</a>
            <a href="#how-it-works" className="lp-nav-link">How it works</a>
            <a href="#integrations" className="lp-nav-link">Integrations</a>
            {user ? (
              <>
                <span className="lp-nav-user">{user.name || user.email}</span>
                <button className="lp-btn-ghost" onClick={onSignOut}>Log out</button>
                <button className="lp-btn-primary" onClick={onEnterDashboard}>Open Dashboard →</button>
              </>
            ) : (
              <>
                <button className="lp-btn-ghost" onClick={onLogin}>Log in</button>
                <button className="lp-btn-primary" onClick={onLogin}>Sign up free →</button>
              </>
            )}
          </div>
        </div>
      </nav>

      <section className="lp-hero">
        <div className="lp-glow lp-glow-left" />
        <div className="lp-glow lp-glow-right" />
        <div className="lp-hero-inner">
          <div className="lp-badge">
            <span className="lp-live-dot" />
            Live AI analysis · Airflow · PySpark · Any pipeline
          </div>
          <h1 className="lp-hero-title">
            Stop guessing why<br />
            your <span className="lp-gradient-text">pipelines fail</span>
          </h1>
          <p className="lp-hero-sub">
            PiPlex captures errors from Airflow, Spark, and any data
            pipeline — then uses Claude to diagnose the root cause and suggest
            a fix in seconds. 5 Docker services, one unified dashboard.
          </p>
          <div className="lp-hero-ctas">
            <button className="lp-btn-primary lp-btn-lg" onClick={onEnterDashboard}>Open Dashboard</button>
            <a href="#how-it-works" className="lp-btn-ghost lp-btn-lg">How it works ↓</a>
          </div>
          <div className="lp-hero-terminal">
            <TerminalWindow />
          </div>
        </div>
      </section>

      <section className="lp-stats-bar">
        <div className="lp-stats-inner">
          {[
            { value: '< 1s', label: 'Ingestion latency' },
            { value: '5',    label: 'Docker services' },
            { value: '8',    label: 'Live pipelines tracked' },
            { value: '5s',   label: 'Dashboard refresh interval' },
          ].map(s => (
            <div key={s.label} className="lp-stat">
              <div className="lp-stat-value">{s.value}</div>
              <div className="lp-stat-label">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-section" id="how-it-works">
        <div className="lp-section-inner">
          <p className="lp-eyebrow">How it works</p>
          <h2 className="lp-section-title">From failure to fix in four steps</h2>
          <div className="lp-steps">
            {STEPS.map(step => (
              <div key={step.num} className="lp-step">
                <div className="lp-step-num">{step.num}</div>
                <h3 className="lp-step-title">{step.title}</h3>
                <p className="lp-step-desc">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section lp-section-alt" id="features">
        <div className="lp-section-inner">
          <p className="lp-eyebrow">Features</p>
          <h2 className="lp-section-title">Everything you need to debug at speed</h2>
          <div className="lp-features-grid">
            {FEATURES.map(f => (
              <div key={f.title} className="lp-feature-card">
                <div className="lp-feature-icon">{f.icon}</div>
                <h3 className="lp-feature-title">{f.title}</h3>
                <p className="lp-feature-desc">{f.desc}</p>
                <div className="lp-feature-tag">{f.tag}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-section-inner">
          <p className="lp-eyebrow">Architecture</p>
          <h2 className="lp-section-title">Built for real data engineering stacks</h2>
          <div className="lp-arch-flow">
            {[
              { label: 'Airflow / Spark\n/ Any pipeline', icon: '🏭', sub: 'Your pipelines' },
              { label: 'Webhook\nCollector',               icon: '📡', sub: 'agent · webhook · API' },
              { label: 'Redis\nStreams',                   icon: '⚡', sub: 'Async queue' },
              { label: 'AI Debugging\nEngine',             icon: '🤖', sub: 'Claude haiku-4-5' },
              { label: 'Dashboard\n+ Slack',               icon: '📊', sub: 'React · Alerts' },
            ].map((node, i, arr) => (
              <div key={node.label} className="lp-arch-node-wrap">
                <div className="lp-arch-node">
                  <div className="lp-arch-icon">{node.icon}</div>
                  <div className="lp-arch-label">{node.label}</div>
                  <div className="lp-arch-sub">{node.sub}</div>
                </div>
                {i < arr.length - 1 && <div className="lp-arch-arrow">→</div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section lp-section-alt" id="integrations">
        <div className="lp-section-inner">
          <p className="lp-eyebrow">Integrations</p>
          <h2 className="lp-section-title">Works with your existing stack</h2>
          <p className="lp-section-sub">Connect via file watcher, webhook, or direct API — no SDK required.</p>
          <div className="lp-integrations-grid">
            {INTEGRATIONS.map(it => (
              <div key={it.name} className="lp-integration-chip">
                <span className="lp-integration-icon">{it.icon}</span>
                <span>{it.name}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-cta-section">
        <div className="lp-glow lp-glow-center" />
        <div className="lp-cta-inner">
          <h2 className="lp-cta-title">
            Your pipeline just failed.<br />
            <span className="lp-gradient-text">Know why in seconds.</span>
          </h2>
          <p className="lp-cta-sub">Open the live dashboard — all services running, real errors, real AI analysis.</p>
          <button className="lp-btn-primary lp-btn-lg lp-btn-xl" onClick={onEnterDashboard}>Open Dashboard →</button>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <p className="lp-footer-copy">Built with FastAPI · React · Claude API · Redis · PostgreSQL · Airflow · PySpark</p>
        </div>
      </footer>

    </div>
  )
}
