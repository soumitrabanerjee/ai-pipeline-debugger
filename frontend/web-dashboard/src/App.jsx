import { useState } from 'react'
import Dashboard from './components/Dashboard'
import LandingPage from './components/LandingPage'

export default function App() {
  const [showDashboard, setShowDashboard] = useState(false)

  if (showDashboard) {
    return <Dashboard onBack={() => setShowDashboard(false)} />
  }

  return <LandingPage onEnterDashboard={() => setShowDashboard(true)} />
}
