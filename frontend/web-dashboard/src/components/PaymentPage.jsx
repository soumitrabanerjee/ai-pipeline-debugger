import { useState } from 'react'
import PiPlexLogo from './PiPlexLogo'
import { API_URL as API } from '../config'

const PLANS = [
  {
    id: 'starter',
    name: 'Starter',
    price: '₹2,499',
    period: '/mo',
    desc: 'For individual engineers and small teams.',
    features: ['Up to 5 pipelines', 'AI root cause analysis', 'Slack alerts', '7-day run history', 'Email support'],
    highlight: false,
  },
  {
    id: 'pro',
    name: 'Pro',
    price: '₹6,499',
    period: '/mo',
    desc: 'For growing data teams who ship fast.',
    features: ['Unlimited pipelines', 'AI root cause analysis', 'Slack + PagerDuty alerts', '90-day run history', 'Priority support', 'Custom webhooks'],
    highlight: true,
    badge: 'Most Popular',
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    desc: 'For large organisations with compliance needs.',
    features: ['Unlimited pipelines', 'Dedicated AI instance', 'SSO / SAML', 'Audit logs', 'SLA guarantee', 'Dedicated CSM'],
    highlight: false,
  },
]

function LockIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="11" width="18" height="11" rx="2"/>
      <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
    </svg>
  )
}

export default function PaymentPage({ user, onPaymentComplete, onSignOut }) {
  const [selectedPlan, setSelectedPlan] = useState('pro')
  const [step, setStep]                 = useState('plan')   // 'plan' | 'promo'
  const [loading, setLoading]           = useState(false)
  const [promoCode, setPromoCode]       = useState('WELCOMETOPIPLEX')
  const [error, setError]               = useState(null)

  const plan = PLANS.find(p => p.id === selectedPlan)

  const handleApplyPromo = async (e) => {
    e.preventDefault()
    setError(null)
    if (!promoCode.trim()) { setError('Please enter a promo code.'); return }

    setLoading(true)
    try {
      const token = localStorage.getItem('apd_token')
      const res = await fetch(`${API}/auth/apply-promo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-session-token': token },
        body: JSON.stringify({ code: promoCode.trim(), plan: selectedPlan }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Failed to apply promo code.'); return }
      onPaymentComplete(data)
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (selectedPlan === 'enterprise' && step === 'promo') {
    return (
      <div className="auth-shell">
        <div className="auth-glow auth-glow-left" />
        <div className="auth-glow auth-glow-right" />
        <nav className="lp-nav">
          <div className="lp-nav-inner">
            <div className="lp-logo"><div className="lp-logo-img-wrap"><PiPlexLogo height={36} /></div></div>
            <button className="lp-btn-ghost" onClick={onSignOut}>Sign out</button>
          </div>
        </nav>
        <div className="auth-center">
          <div className="auth-card" style={{ textAlign: 'center', gap: '1.5rem' }}>
            <div style={{ fontSize: '2.5rem' }}>🤝</div>
            <h2 className="auth-title">Let's talk</h2>
            <p className="auth-sub">Enterprise plans are custom-quoted. Our team will reach out to <strong style={{ color: '#e2e8f0' }}>{user.email}</strong> within 24 hours.</p>
            <button className="lp-btn-primary auth-submit" onClick={() => setStep('plan')}>← Choose a different plan</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-shell">
      <div className="auth-glow auth-glow-left" />
      <div className="auth-glow auth-glow-right" />

      <nav className="lp-nav">
        <div className="lp-nav-inner">
          <div className="lp-logo">
            <div className="lp-logo-img-wrap">
              <PiPlexLogo height={36} />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <span style={{ fontSize: '0.875rem', fontWeight: 500, color: '#94a3b8' }}>{user.name || user.email}</span>
            <button className="lp-btn-ghost" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </nav>

      {step === 'plan' ? (
        <div className="pay-shell">
          <div className="pay-header">
            <p className="lp-eyebrow">Subscription</p>
            <h2 className="auth-title" style={{ marginBottom: '0.5rem' }}>Choose your plan</h2>
            <p className="auth-sub">Cancel anytime. No hidden fees.</p>
          </div>

          <div className="pay-plans">
            {PLANS.map(p => (
              <div
                key={p.id}
                className={`pay-plan-card${p.highlight ? ' pay-plan-highlight' : ''}${selectedPlan === p.id ? ' pay-plan-selected' : ''}`}
                onClick={() => setSelectedPlan(p.id)}
              >
                {p.badge && <span className="pay-badge">{p.badge}</span>}
                <div className="pay-plan-top">
                  <h3 className="pay-plan-name">{p.name}</h3>
                  <div className="pay-plan-price">
                    <span className="pay-price-amount">{p.price}</span>
                    <span className="pay-price-period">{p.period}</span>
                  </div>
                  <p className="pay-plan-desc">{p.desc}</p>
                </div>
                <ul className="pay-features">
                  {p.features.map(f => (
                    <li key={f} className="pay-feature"><span className="pay-check">✓</span>{f}</li>
                  ))}
                </ul>
                <div className={`pay-select-indicator${selectedPlan === p.id ? ' pay-select-indicator-active' : ''}`}>
                  {selectedPlan === p.id ? '● Selected' : '○ Select'}
                </div>
              </div>
            ))}
          </div>

          <div style={{ textAlign: 'center', marginTop: '2rem' }}>
            <button
              className="lp-btn-primary lp-btn-lg"
              onClick={() => setStep('promo')}
            >
              Continue with {plan.name} →
            </button>
          </div>
        </div>
      ) : (
        <div className="auth-center">
          <div className="auth-card" style={{ maxWidth: '480px' }}>
            <button className="auth-link" style={{ alignSelf: 'flex-start', marginBottom: '0.5rem' }} onClick={() => setStep('plan')}>
              ← Back to plans
            </button>

            <div className="auth-card-header">
              <h2 className="auth-title">Apply promo code</h2>
              <div className="pay-order-summary">
                <span>{plan.name} plan</span>
                <span className="pay-order-price" style={{ color: 'var(--success-text)', textDecoration: 'line-through var(--text-muted)' }}>
                  {plan.price !== 'Custom' ? <><s style={{ color: 'var(--text-muted)', fontWeight: 400 }}>{plan.price}{plan.period}</s> Free</> : plan.price}
                </span>
              </div>
            </div>

            <div style={{
              background: 'var(--accent-subtle)',
              border: '1px solid rgba(99,102,241,0.3)',
              borderRadius: '10px',
              padding: '0.875rem 1rem',
              fontSize: '0.82rem',
              color: 'var(--text-secondary)',
              marginBottom: '1.25rem',
            }}>
              <strong style={{ color: 'var(--text)' }}>🎉 100% off — all plans are free during beta.</strong>
              <span style={{ display: 'block', marginTop: '0.25rem', color: 'var(--text-muted)' }}>
                The promo code below is pre-filled for you. Just click Activate.
              </span>
            </div>

            <form className="auth-form" onSubmit={handleApplyPromo}>
              <div className="auth-field">
                <label className="auth-label">Promo code</label>
                <input
                  className="auth-input"
                  placeholder="WELCOMETOPIPLEX"
                  value={promoCode}
                  onChange={e => setPromoCode(e.target.value.toUpperCase())}
                  style={{ fontFamily: 'monospace', letterSpacing: '0.08em', fontWeight: 600 }}
                />
              </div>

              {error && <p className="auth-error">{error}</p>}

              <button className="lp-btn-primary auth-submit" type="submit" disabled={loading}>
                {loading ? <span className="auth-spinner" /> : `Activate ${plan.name} for free →`}
              </button>
            </form>

            <p className="pay-secure-note">
              <LockIcon /> No credit card required. Upgrade options will be available later.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
