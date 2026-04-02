import { useState, useEffect } from 'react'
import { api } from '../api'
import { useToast } from '../components/Toast'

const PROVIDER_PRESETS = {
  claude: {
    label: 'Claude',
    subtitle: 'Anthropic Messages',
    defaultBaseUrl: 'https://api.anthropic.com',
    apiKeyPlaceholder: 'sk-ant-...',
    modelPlaceholder: 'claude-sonnet-4-6',
    models: [
      'claude-opus-4-6',
      'claude-sonnet-4-6',
      'claude-haiku-4-5-20251001',
      'claude-3-5-sonnet-20241022',
      'claude-3-5-haiku-20241022',
    ],
    baseUrlHint: 'Anthropic 官方地址或 Claude 代理地址',
    modelHint: '支持任意 Claude 模型 ID',
  },
  openai: {
    label: 'OpenAI',
    subtitle: 'Chat Completions',
    defaultBaseUrl: 'https://api.openai.com',
    apiKeyPlaceholder: 'sk-...',
    modelPlaceholder: 'gpt-4.1-mini',
    models: [
      'gpt-4.1',
      'gpt-4.1-mini',
      'gpt-4o',
      'gpt-4o-mini',
    ],
    baseUrlHint: 'OpenAI 官方地址或 OpenAI-compatible 代理地址',
    modelHint: '支持任意 OpenAI 兼容模型 ID',
  },
}

const PROVIDER_ORDER = ['claude', 'openai']

function getPreset(provider) {
  return PROVIDER_PRESETS[provider] || PROVIDER_PRESETS.claude
}

function inferProvider(baseUrl = '', model = '') {
  const text = `${baseUrl} ${model}`.toLowerCase()
  if (text.includes('claude') || text.includes('anthropic')) return 'claude'
  if (text.includes('openai') || text.includes('gpt') || text.includes('chat/completions') || text.includes('codex')) return 'openai'
  return 'claude'
}

export default function Settings() {
  const toast = useToast()
  const [form, setForm] = useState({ provider: 'claude', base_url: '', api_key: '', model: '' })
  const [loading, setLoading] = useState(true)
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    api.getSettings().then(s => {
      const provider = s.provider || inferProvider(s.base_url, s.model)
      setForm({
        provider,
        base_url: s.base_url || '',
        api_key: s.api_key || '',
        model: s.model || '',
      })
    }).catch(err => {
      toast(`读取设置失败：${err.message}`, 'error')
    }).finally(() => {
      setLoading(false)
    })
  }, [])

  function set(k, v) {
    setForm(f => ({ ...f, [k]: v }))
  }

  function handleProviderChange(nextProvider) {
    setForm(prev => {
      const prevPreset = getPreset(prev.provider)
      const nextPreset = getPreset(nextProvider)

      const next = { ...prev, provider: nextProvider }
      const baseUrl = (prev.base_url || '').trim()
      const model = (prev.model || '').trim()

      if (!baseUrl || baseUrl === prevPreset.defaultBaseUrl) {
        next.base_url = nextPreset.defaultBaseUrl
      }
      if (!model || prevPreset.models.includes(model)) {
        next.model = nextPreset.models[0]
      }
      return next
    })
  }

  function applyRecommended() {
    const preset = getPreset(form.provider)
    setForm(prev => ({
      ...prev,
      base_url: preset.defaultBaseUrl,
      model: preset.models[0],
    }))
  }

  async function handleSave() {
    setSaving(true)
    try {
      await api.saveSettings(form)
      toast('设置已保存', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    try {
      await api.testSettings(form)
      toast('连接成功 ✓', 'success')
    } catch (err) {
      toast(`连接失败：${err.message}`, 'error')
    } finally {
      setTesting(false)
    }
  }

  const preset = getPreset(form.provider)
  const maybeWrongKey = form.provider === 'openai' && (form.api_key || '').trim().startsWith('sk-ant')

  if (loading) {
    return (
      <div>
        <div className="page-header">
          <h1 className="page-title">设置</h1>
        </div>
        <div className="settings-form settings-shell">
          <div className="settings-card">
            <div style={{ color: 'var(--text2)' }}>读取设置中...</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">设置</h1>
      </div>
      <div className="settings-form settings-shell">
        <div className="settings-card">
          <div className="field">
            <label>接口规范</label>
            <div className="provider-switch">
              {PROVIDER_ORDER.map(provider => (
                <button
                  key={provider}
                  type="button"
                  className={`provider-chip${form.provider === provider ? ' active' : ''}`}
                  onClick={() => handleProviderChange(provider)}
                >
                  <strong>{getPreset(provider).label}</strong>
                  <span>{getPreset(provider).subtitle}</span>
                </button>
              ))}
            </div>
            <div className="field-help">
              当前将按 <strong>{preset.label}</strong> 协议拼装请求。
            </div>
            <div className="field-help">
              切换协议后需要点击「保存设置」才会持久化。
            </div>
          </div>

          <div className="field">
            <label>API Base URL</label>
            <input
              value={form.base_url}
              onChange={e => set('base_url', e.target.value)}
              placeholder={preset.defaultBaseUrl}
            />
            <div className="field-help">
              {preset.baseUrlHint}
            </div>
          </div>

          <div className="field">
            <label>API Key</label>
            <div className="key-input-wrap">
              <input
                type={showKey ? 'text' : 'password'}
                value={form.api_key}
                onChange={e => set('api_key', e.target.value)}
                placeholder={preset.apiKeyPlaceholder}
                className="key-input"
              />
              <button
                type="button"
                onClick={() => setShowKey(s => !s)}
                className="key-toggle-btn"
              >
                {showKey ? '隐藏' : '显示'}
              </button>
            </div>
            {maybeWrongKey && (
              <div className="field-help" style={{ color: 'var(--danger)' }}>
                当前 Key 看起来是 Claude/Anthropic Key（`sk-ant...`），OpenAI 协议通常需要 OpenAI 或 OpenAI-compatible 平台专用 Key。
              </div>
            )}
          </div>

          <div className="field">
            <label>模型</label>
            <input
              value={form.model}
              onChange={e => set('model', e.target.value)}
              placeholder={preset.modelPlaceholder}
              list="model-list"
            />
            <datalist id="model-list">
              {preset.models.map(m => <option key={m} value={m} />)}
            </datalist>
            <div className="field-help">
              {preset.modelHint}，可直接输入模型 ID
            </div>
          </div>

          <div className="settings-actions">
            <button className="btn-secondary" onClick={applyRecommended} type="button">
              填充推荐地址/模型
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存设置'}
            </button>
            <button className="btn-secondary" onClick={handleTest} disabled={testing || !form.api_key}>
              {testing ? '测试中...' : '测试连接'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
