import { useState } from 'react'
import { useGoogleLogin } from '@react-oauth/google'
import PiPlexLogo from './PiPlexLogo'
import { API_URL as API } from '../config'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

function GoogleLoginButton({ onSuccess, onError, disabled }) {
  const googleLogin = useGoogleLogin({ onSuccess, onError })
  return (
    <button className="auth-oauth-btn" onClick={() => googleLogin()} disabled={disabled}>
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
        <path d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
        <path d="M3.964 10.707A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z" fill="#FBBC05"/>
        <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
      </svg>
      Continue with Google
    </button>
  )
}

export default function LoginPage({ onLogin, onBack }) {
  const [tab, setTab]                       = useState('signin')
  const [email, setEmail]                   = useState('')
  const [password, setPassword]             = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [name, setName]                     = useState('')
  const [error, setError]                   = useState(null)
  const [loading, setLoading]               = useState(false)
  const [apiKey, setApiKey]                 = useState(null)
  const [needsOtp, setNeedsOtp]             = useState(false)
  const [pendingEmail, setPendingEmail]     = useState('')
  const [otp, setOtp]                       = useState('')
  const [resendCooldown, setResendCooldown] = useState(0)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    if (!email || !password) { setError('Email and password are required.'); return }
    if (tab === 'signup' && !name) { setError('Name is required.'); return }

    if (tab === 'signup' && password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (tab === 'signup' && password !== confirmPassword) { setError('Passwords do not match.'); return }

    setLoading(true)
    try {
      const endpoint = tab === 'signup' ? '/auth/register' : '/auth/login'
      const body     = tab === 'signup'
        ? { email, name, password }
        : { email, password }

      const res = await fetch(`${API}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || 'Something went wrong. Please try again.')
        return
      }

      if (tab === 'signup' && data.needs_verification) {
        setPendingEmail(email)
        setNeedsOtp(true)
        return
      }
      if (tab === 'signup' && data.api_key) {
        setApiKey(data.api_key)
        localStorage.setItem('apd_pending_token', data.token)
        localStorage.setItem('apd_pending_user', JSON.stringify(data.user))
        return
      }
      onLogin(data.token, data.user)
    } catch (err) {
      console.error('[login] handleSubmit error:', err)
      setError('Could not reach the server. Make sure the API is running.')
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSuccess = async (tokenResponse) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ access_token: tokenResponse.access_token }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Google sign-in failed.'); return }
      if (data.api_key) {
        setApiKey(data.api_key)
        localStorage.setItem('apd_pending_token', data.token)
        localStorage.setItem('apd_pending_user', JSON.stringify(data.user))
        return
      }
      onLogin(data.token, data.user)
    } catch {
      setError('Could not reach the server.')
    } finally {
      setLoading(false)
    }
  }

  const handleVerifyOtp = async (e) => {
    e.preventDefault()
    setError(null)
    if (otp.length !== 6) { setError('Enter the 6-digit code sent to your email.'); return }
    setLoading(true)
    try {
      const res = await fetch(`${API}/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingEmail, otp }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Verification failed.'); return }
      if (data.api_key) {
        setApiKey(data.api_key)
        localStorage.setItem('apd_pending_token', data.token)
        localStorage.setItem('apd_pending_user', JSON.stringify(data.user))
        setNeedsOtp(false)
        return
      }
      onLogin(data.token, data.user)
    } catch {
      setError('Could not reach the server.')
    } finally {
      setLoading(false)
    }
  }

  const handleResendOtp = async () => {
    if (resendCooldown > 0) return
    try {
      await fetch(`${API}/auth/resend-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingEmail }),
      })
    } catch { /* silent */ }
    setResendCooldown(60)
    const iv = setInterval(() => setResendCooldown(c => { if (c <= 1) { clearInterval(iv); return 0 } return c - 1 }), 1000)
  }

  if (needsOtp) {
    return (
      <div className="auth-shell">
        <div className="auth-glow auth-glow-left" />
        <div className="auth-glow auth-glow-right" />
        <nav className="lp-nav">
          <div className="lp-nav-inner">
            <div className="lp-logo"><div className="lp-logo-img-wrap"><PiPlexLogo height={36} /></div></div>
            <button className="lp-btn-ghost" onClick={() => { setNeedsOtp(false); setOtp(''); setError(null) }}>← Back</button>
          </div>
        </nav>
        <div className="auth-center">
          <div className="auth-card" style={{ maxWidth: 420 }}>
            <div style={{ fontSize: '2rem', textAlign: 'center' }}>📬</div>
            <h2 className="auth-title" style={{ textAlign: 'center' }}>Check your email</h2>
            <p className="auth-sub" style={{ textAlign: 'center' }}>
              We sent a 6-digit code to <strong style={{ color: '#e2e8f0' }}>{pendingEmail}</strong>
            </p>
            <form className="auth-form" onSubmit={handleVerifyOtp}>
              <div className="auth-field">
                <label className="auth-label">Verification code</label>
                <input
                  className="auth-input"
                  placeholder="123456"
                  value={otp}
                  onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  inputMode="numeric"
                  autoFocus
                  style={{ fontFamily: 'monospace', fontSize: '1.4rem', letterSpacing: '0.5em', textAlign: 'center' }}
                />
              </div>
              {error && <p className="auth-error">{error}</p>}
              <button className="lp-btn-primary auth-submit" type="submit" disabled={loading}>
                {loading ? <span className="auth-spinner" /> : 'Verify →'}
              </button>
            </form>
            <p style={{ textAlign: 'center', fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.75rem' }}>
              Didn't receive it?{' '}
              <button
                className="auth-link"
                onClick={handleResendOtp}
                disabled={resendCooldown > 0}
                style={{ opacity: resendCooldown > 0 ? 0.5 : 1 }}
              >
                {resendCooldown > 0 ? `Resend in ${resendCooldown}s` : 'Resend code'}
              </button>
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (apiKey) {
    return (
      <div className="auth-shell">
        <div className="auth-glow auth-glow-left" />
        <div className="auth-glow auth-glow-right" />
        <nav className="lp-nav">
          <div className="lp-nav-inner">
            <div className="lp-logo"><div className="lp-logo-img-wrap"><PiPlexLogo height={36} /></div></div>
          </div>
        </nav>
        <div className="auth-center">
          <div className="auth-card" style={{ maxWidth: 520 }}>
            <div style={{ fontSize: '2rem', textAlign: 'center' }}>🔑</div>
            <h2 className="auth-title" style={{ textAlign: 'center' }}>Your API Key</h2>
            <p className="auth-sub" style={{ textAlign: 'center' }}>
              Copy this key now — it will <strong>never be shown again</strong>.
              Use it as the <code style={{ color: 'var(--accent)' }}>x-api-key</code> header when sending events.
            </p>
            <div style={{
              background: 'var(--bg-input)', border: '1px solid var(--border)',
              borderRadius: '10px', padding: '1rem', fontFamily: 'monospace',
              fontSize: '0.82rem', wordBreak: 'break-all', color: 'var(--accent)',
              marginBottom: '1rem', userSelect: 'all',
            }}>
              {apiKey}
            </div>
            <button
              className="lp-btn-primary auth-submit"
              onClick={() => {
                navigator.clipboard.writeText(apiKey).catch(() => {})
                const tok = localStorage.getItem('apd_pending_token')
                const usr = JSON.parse(localStorage.getItem('apd_pending_user') || '{}')
                localStorage.removeItem('apd_pending_token')
                localStorage.removeItem('apd_pending_user')
                onLogin(tok, usr)
              }}
            >
              Copy &amp; Continue →
            </button>
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
          <button className="lp-btn-ghost" onClick={onBack}>← Back</button>
        </div>
      </nav>

      <div className="auth-center">
        <div className="auth-card">
          <div className="auth-card-header">
            <h2 className="auth-title">
              {tab === 'signin' ? 'Welcome back' : 'Create your account'}
            </h2>
            <p className="auth-sub">
              {tab === 'signin'
                ? 'Sign in to access your pipeline dashboard'
                : 'Start debugging pipelines in minutes'}
            </p>
          </div>

          <div className="auth-tabs">
            <button
              className={tab === 'signin' ? 'auth-tab auth-tab-active' : 'auth-tab'}
              onClick={() => { setTab('signin'); setError(null); setConfirmPassword('') }}
            >Sign In</button>
            <button
              className={tab === 'signup' ? 'auth-tab auth-tab-active' : 'auth-tab'}
              onClick={() => { setTab('signup'); setError(null); setConfirmPassword('') }}
            >Sign Up</button>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {tab === 'signup' && (
              <div className="auth-field">
                <label className="auth-label">Full Name</label>
                <input
                  className="auth-input"
                  type="text"
                  placeholder="Ada Lovelace"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  autoComplete="name"
                />
              </div>
            )}
            <div className="auth-field">
              <label className="auth-label">Email</label>
              <input
                className="auth-input"
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="email"
              />
            </div>
            <div className="auth-field">
              <label className="auth-label">Password</label>
              <input
                className="auth-input"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete={tab === 'signin' ? 'current-password' : 'new-password'}
              />
            </div>
            {tab === 'signup' && (
              <div className="auth-field">
                <label className="auth-label">Confirm Password</label>
                <input
                  className="auth-input"
                  type="password"
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            )}

            {error && <p className="auth-error">{error}</p>}

            <button className="lp-btn-primary auth-submit" type="submit" disabled={loading}>
              {loading
                ? <span className="auth-spinner" />
                : tab === 'signin' ? 'Sign In →' : 'Create Account →'}
            </button>
          </form>

          {GOOGLE_CLIENT_ID && (
            <>
              <div className="auth-divider"><span>or</span></div>
              <GoogleLoginButton
                onSuccess={handleGoogleSuccess}
                onError={() => setError('Google sign-in was cancelled or failed.')}
                disabled={loading}
              />
            </>
          )}

          {tab === 'signin' && (
            <p className="auth-footer-note">
              Don't have an account?{' '}
              <button className="auth-link" onClick={() => { setTab('signup'); setError(null) }}>
                Sign up free
              </button>
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
