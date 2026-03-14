import { useState, useEffect } from 'react'
import LandingPage  from './components/LandingPage'
import HomePage     from './components/HomePage'
import LoginPage    from './components/LoginPage'
import PaymentPage  from './components/PaymentPage'
import Dashboard    from './components/Dashboard'
import { API_URL as API } from './config'

export default function App() {
  const [page, setPage]       = useState(null)   // null = loading
  const [user, setUser]       = useState(null)
  const [theme, setTheme]     = useState(() => localStorage.getItem('apd_theme') || 'dark')

  // Pages that require a paid account — restored on refresh only if user is paid
  const AUTHED_PAGES = new Set(['home', 'dashboard'])

  const navigate = (p) => {
    setPage(p)
    localStorage.setItem('apd_page', p)
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('apd_theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  // Restore session and last page on mount
  useEffect(() => {
    const token     = localStorage.getItem('apd_token')
    const savedPage = localStorage.getItem('apd_page')

    if (!token) { setPage('landing'); return }

    fetch(`${API}/auth/me`, { headers: { 'x-session-token': token } })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(u => {
        setUser(u)
        if (!u.paid) { setPage('payment'); return }
        // Restore last page if it's a valid authed page, otherwise default to home
        setPage(AUTHED_PAGES.has(savedPage) ? savedPage : 'home')
      })
      .catch(() => { localStorage.removeItem('apd_token'); localStorage.removeItem('apd_page'); setPage('landing') })
  }, [])

  const handleLogin = (token, u) => {
    localStorage.setItem('apd_token', token)
    setUser(u)
    navigate(u.paid ? 'home' : 'payment')
  }

  const handlePaymentComplete = (u) => {
    setUser(u)
    navigate('home')
  }

  const handleSignOut = () => {
    const token = localStorage.getItem('apd_token')
    if (token) {
      fetch(`${API}/auth/session`, { method: 'DELETE', headers: { 'x-session-token': token } })
        .catch(() => {})
    }
    localStorage.removeItem('apd_token')
    localStorage.removeItem('apd_page')
    setUser(null)
    setPage('landing')
  }

  if (page === null)        return <div style={{ minHeight: '100vh', background: '#0a0f1e' }} />
  if (page === 'landing')   return <LandingPage  onEnterDashboard={() => navigate(user ? (user.paid ? 'home' : 'payment') : 'login')} onLogin={() => navigate('login')} onSignOut={handleSignOut} user={user} />
  if (page === 'home')      return <HomePage     user={user} onOpenDashboard={() => navigate('dashboard')} onSignOut={handleSignOut} theme={theme} toggleTheme={toggleTheme} />
  if (page === 'login')     return <LoginPage    onLogin={handleLogin} onBack={() => navigate('landing')} />
  if (page === 'payment')   return <PaymentPage  user={user} onPaymentComplete={handlePaymentComplete} onSignOut={handleSignOut} />
  if (page === 'dashboard') return <Dashboard    onBack={() => navigate('home')} user={user} onSignOut={handleSignOut} theme={theme} toggleTheme={toggleTheme} />
}
