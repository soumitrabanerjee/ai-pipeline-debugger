import { useState } from 'react'

const API = 'http://localhost:8001'

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

function CardIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1" y="4" width="22" height="16" rx="2"/>
      <line x1="1" y1="10" x2="23" y2="10"/>
    </svg>
  )
}

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
  const [step, setStep]                 = useState('plan')   // 'plan' | 'card'
  const [loading, setLoading]           = useState(false)
  const [cardNumber, setCardNumber]     = useState('')
  const [expiry, setExpiry]             = useState('')
  const [cvc, setCvc]                   = useState('')
  const [cardName, setCardName]         = useState('')
  const [error, setError]               = useState(null)

  const plan = PLANS.find(p => p.id === selectedPlan)

  const formatCardNumber = (v) =>
    v.replace(/\D/g, '').slice(0, 16).replace(/(.{4})/g, '$1 ').trim()

  const formatExpiry = (v) => {
    const d = v.replace(/\D/g, '').slice(0, 4)
    return d.length > 2 ? `${d.slice(0, 2)} / ${d.slice(2)}` : d
  }

  const handlePayment = async (e) => {
    e.preventDefault()
    setError(null)
    if (!cardName)   { setError('Name on card is required.'); return }
    if (cardNumber.replace(/\s/g, '').length < 16) { setError('Enter a valid 16-digit card number.'); return }
    if (expiry.replace(/\s\/\s/g, '').length < 4)  { setError('Enter a valid expiry date.'); return }
    if (cvc.length < 3) { setError('Enter a valid CVC.'); return }

    setLoading(true)
    try {
      const token = localStorage.getItem('apd_token')
      const res = await fetch(`${API}/auth/payment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-session-token': token },
        body: JSON.stringify({ plan: selectedPlan }),
      })
      const updatedUser = await res.json()
      if (!res.ok) { setError(updatedUser.detail || 'Payment failed.'); return }
      onPaymentComplete(updatedUser)
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (selectedPlan === 'enterprise' && step === 'card') {
    return (
      <div className="auth-shell">
        <div className="auth-glow auth-glow-left" />
        <div className="auth-glow auth-glow-right" />
        <nav className="lp-nav">
          <div className="lp-nav-inner">
            <div className="lp-logo"><div className="lp-logo-img-wrap"><img src="/pipelex.png" alt="PipeLex" className="lp-logo-img" /></div></div>
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
              <img src="/pipelex.png" alt="PipeLex" className="lp-logo-img" />
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
              onClick={() => setStep('card')}
            >
              Continue with {plan.name} {plan.price}{plan.period} →
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
              <h2 className="auth-title">Payment details</h2>
              <div className="pay-order-summary">
                <span>{plan.name} plan</span>
                <span className="pay-order-price">{plan.price}{plan.period}</span>
              </div>
            </div>

            <form className="auth-form" onSubmit={handlePayment}>
              <div className="auth-field">
                <label className="auth-label">Name on card</label>
                <input
                  className="auth-input"
                  placeholder="Ada Lovelace"
                  value={cardName}
                  onChange={e => setCardName(e.target.value)}
                />
              </div>
              <div className="auth-field">
                <label className="auth-label">Card number</label>
                <div className="auth-input-icon-wrap">
                  <input
                    className="auth-input auth-input-icon"
                    placeholder="1234 5678 9012 3456"
                    value={cardNumber}
                    onChange={e => setCardNumber(formatCardNumber(e.target.value))}
                    inputMode="numeric"
                  />
                  <span className="auth-input-icon-el"><CardIcon /></span>
                </div>
              </div>
              <div className="auth-row">
                <div className="auth-field">
                  <label className="auth-label">Expiry</label>
                  <input
                    className="auth-input"
                    placeholder="MM / YY"
                    value={expiry}
                    onChange={e => setExpiry(formatExpiry(e.target.value))}
                    inputMode="numeric"
                  />
                </div>
                <div className="auth-field">
                  <label className="auth-label">CVC</label>
                  <input
                    className="auth-input"
                    placeholder="123"
                    value={cvc}
                    onChange={e => setCvc(e.target.value.replace(/\D/g, '').slice(0, 4))}
                    inputMode="numeric"
                  />
                </div>
              </div>

              {error && <p className="auth-error">{error}</p>}

              <button className="lp-btn-primary auth-submit" type="submit" disabled={loading}>
                {loading
                  ? <span className="auth-spinner" />
                  : `Pay ${plan.price}${plan.period} and activate`}
              </button>
            </form>

            <p className="pay-secure-note">
              <LockIcon /> Payments are encrypted and secure. This is a demo — no real charge is made.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
