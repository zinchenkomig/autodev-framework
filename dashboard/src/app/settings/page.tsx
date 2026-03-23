'use client'

import { useState, useEffect } from 'react'
import { Save, TestTube, Webhook, Eye, EyeOff, CheckCircle, XCircle, Loader2 } from 'lucide-react'

interface TelegramSettings {
  bot_token: string
  owner_chat_id: string
  webhook_secret: string
  webhook_url: string
}

interface TestResult {
  success: boolean
  message: string
  bot_username?: string
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || ''

export default function SettingsPage() {
  const [telegram, setTelegram] = useState<TelegramSettings>({
    bot_token: '',
    owner_chat_id: '',
    webhook_secret: '',
    webhook_url: ''
  })
  const [showToken, setShowToken] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [settingWebhook, setSettingWebhook] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [saveMessage, setSaveMessage] = useState('')
  const [hasToken, setHasToken] = useState(false)

  useEffect(() => {
    loadSettings()
  }, [])

  async function loadSettings() {
    try {
      const res = await fetch(`${API_URL}/api/settings/telegram`)
      if (res.ok) {
        const data = await res.json()
        // Check if token is saved (masked)
        setHasToken(data.bot_token.startsWith('*'))
        // Don't show masked token - show empty for new input
        setTelegram({
          ...data,
          bot_token: '' // Always start with empty token field
        })
      }
    } catch (e) {
      console.error('Failed to load settings', e)
    }
  }

  async function handleSave() {
    setSaving(true)
    setSaveMessage('')
    try {
      const res = await fetch(`${API_URL}/api/settings/telegram`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(telegram)
      })
      if (res.ok) {
        setSaveMessage('✓ Сохранено')
        if (telegram.bot_token) {
          setHasToken(true)
          setTelegram(prev => ({ ...prev, bot_token: '' }))
        }
      } else {
        setSaveMessage('✗ Ошибка')
      }
    } catch (e) {
      setSaveMessage('✗ Ошибка')
    }
    setSaving(false)
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetch(`${API_URL}/api/settings/telegram/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bot_token: telegram.bot_token || null,
          owner_chat_id: telegram.owner_chat_id || null
        })
      })
      const result = await res.json()
      setTestResult(result)
    } catch (e) {
      setTestResult({ success: false, message: String(e) })
    }
    setTesting(false)
  }

  async function handleSetWebhook() {
    setSettingWebhook(true)
    setTestResult(null)
    try {
      const res = await fetch(`${API_URL}/api/settings/telegram/webhook`, {
        method: 'POST'
      })
      if (res.ok) {
        const data = await res.json()
        setTestResult({ success: true, message: `Webhook установлен` })
      } else {
        const error = await res.json()
        setTestResult({ success: false, message: error.detail || 'Ошибка' })
      }
    } catch (e) {
      setTestResult({ success: false, message: String(e) })
    }
    setSettingWebhook(false)
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-xl font-semibold text-white mb-6">Настройки</h1>

      {/* Telegram Section */}
      <div className="rounded-lg p-6 mb-6" style={{ background: '#3C3F41', border: '1px solid #515151' }}>
        <h2 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
          </svg>
          Telegram
        </h2>

        <div className="space-y-4">
          {/* Bot Token */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Bot Token
              {hasToken && <span className="text-green-400 ml-2">✓ сохранён</span>}
            </label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showToken ? 'text' : 'password'}
                  value={telegram.bot_token}
                  onChange={e => setTelegram({ ...telegram, bot_token: e.target.value })}
                  placeholder={hasToken ? "Оставьте пустым или введите новый" : "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"}
                  className="w-full px-3 py-2 rounded text-sm outline-none"
                  style={{ background: '#2B2B2B', border: '1px solid #515151', color: '#BABABA' }}
                />
                <button
                  onClick={() => setShowToken(!showToken)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1"
                  style={{ color: '#808080' }}
                >
                  {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">Получить у @BotFather</p>
          </div>

          {/* Owner Chat ID */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Owner Chat ID</label>
            <input
              type="text"
              value={telegram.owner_chat_id}
              onChange={e => setTelegram({ ...telegram, owner_chat_id: e.target.value })}
              placeholder="123456789"
              className="w-full px-3 py-2 rounded text-sm outline-none"
              style={{ background: '#2B2B2B', border: '1px solid #515151', color: '#BABABA' }}
            />
            <p className="text-xs text-gray-500 mt-1">Ваш Telegram ID (получить у @userinfobot)</p>
          </div>

          {/* Webhook Secret */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Webhook Secret (опционально)</label>
            <input
              type="text"
              value={telegram.webhook_secret}
              onChange={e => setTelegram({ ...telegram, webhook_secret: e.target.value })}
              placeholder="random-secret-string"
              className="w-full px-3 py-2 rounded text-sm outline-none"
              style={{ background: '#2B2B2B', border: '1px solid #515151', color: '#BABABA' }}
            />
          </div>

          {/* Webhook URL (readonly) */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Webhook URL</label>
            <input
              type="text"
              value={telegram.webhook_url}
              readOnly
              className="w-full px-3 py-2 rounded text-sm"
              style={{ background: '#2B2B2B', border: '1px solid #515151', color: '#606060' }}
            />
          </div>

          {/* Buttons */}
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              onClick={handleTest}
              disabled={testing || (!telegram.bot_token && !hasToken)}
              className="flex items-center gap-2 px-4 py-2 rounded text-sm disabled:opacity-50"
              style={{ background: '#214283', color: '#FFF' }}
            >
              {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <TestTube className="w-4 h-4" />}
              Тест
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 rounded text-sm disabled:opacity-50"
              style={{ background: '#6A8759', color: '#FFF' }}
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Сохранить
            </button>
            <button
              onClick={handleSetWebhook}
              disabled={settingWebhook || !hasToken}
              className="flex items-center gap-2 px-4 py-2 rounded text-sm disabled:opacity-50"
              style={{ background: '#4A4A4A', color: '#FFF' }}
            >
              {settingWebhook ? <Loader2 className="w-4 h-4 animate-spin" /> : <Webhook className="w-4 h-4" />}
              Установить Webhook
            </button>
          </div>

          {/* Save message */}
          {saveMessage && (
            <p className={`text-sm ${saveMessage.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>
              {saveMessage}
            </p>
          )}

          {/* Test result */}
          {testResult && (
            <div 
              className="flex items-start gap-2 p-3 rounded text-sm"
              style={{ 
                background: testResult.success ? 'rgba(106, 135, 89, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                border: `1px solid ${testResult.success ? '#6A8759' : '#EF4444'}`
              }}
            >
              {testResult.success ? (
                <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
              ) : (
                <XCircle className="w-4 h-4 text-red-400 mt-0.5" />
              )}
              <div>
                <p style={{ color: testResult.success ? '#6A8759' : '#EF4444' }}>
                  {testResult.message}
                </p>
                {testResult.bot_username && (
                  <p className="text-gray-400 text-xs mt-1">Bot: @{testResult.bot_username}</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
