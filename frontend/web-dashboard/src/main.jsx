import React from 'react'
import { createRoot } from 'react-dom/client'
import { GoogleOAuthProvider } from '@react-oauth/google'
import App from './App'
import './styles.css'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

const tree = GOOGLE_CLIENT_ID
  ? <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}><App /></GoogleOAuthProvider>
  : <App />

createRoot(document.getElementById('root')).render(
  <React.StrictMode>{tree}</React.StrictMode>
)
