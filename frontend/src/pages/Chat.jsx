import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api, streamSSE } from '../api'
import { useToast } from '../components/Toast'

export default function Chat() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const [ex, setEx] = useState(null)
  const [history, setHistory] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const stopStreamRef = useRef(null)

  useEffect(() => {
    api.getEx(slug)
      .then(setEx)
      .catch(err => { toast(err.message, 'error'); navigate('/') })

    api.getHistory(slug)
      .then(setHistory)
      .catch(console.error)
  }, [slug])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, streamingText])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function handleSend() {
    const msg = input.trim()
    if (!msg || streaming) return
    setInput('')
    setStreaming(true)
    setStreamingText('')

    const optimisticHistory = [...history, { role: 'user', content: msg, ts: new Date().toISOString() }]
    setHistory(optimisticHistory)

    let full = ''
    const stop = streamSSE(
      `/api/exes/${slug}/chat`,
      { message: msg },
      (data) => {
        if (data.error) {
          toast(`出错了：${data.error}`, 'error')
          setStreaming(false)
          setStreamingText('')
          return
        }
        if (data.token) {
          full += data.token
          setStreamingText(full)
        }
        if (data.done) {
          setHistory(h => [...h, { role: 'assistant', content: full, ts: new Date().toISOString() }])
          setStreamingText('')
          setStreaming(false)
        }
      },
      (err) => {
        toast(err.message, 'error')
        setStreaming(false)
        setStreamingText('')
      }
    )
    stopStreamRef.current = stop
  }

  async function handleClearHistory() {
    if (!confirm('确认清空聊天记录？')) return
    try {
      await api.clearHistory(slug)
      setHistory([])
      toast('已清空', 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const name = ex?.meta?.name || slug

  return (
    <div className="chat-screen">
      {/* Header */}
      <div className="chat-header wechat-header">
        <div className="chat-header-main wechat-header-main">
          <button className="wechat-nav-btn" onClick={() => navigate('/')} title="返回">
            ‹
          </button>
          <div className="wechat-title-wrap">
            <div className="chat-header-name wechat-title">{name}</div>
            {ex?.meta?.tags?.mbti && (
              <div className="wechat-subtitle">{ex.meta.tags.mbti}</div>
            )}
          </div>
        </div>
        <div className="chat-header-actions wechat-header-actions">
          <button className="wechat-action-btn" title="管理"
            onClick={() => navigate(`/ex/${slug}`)}>
            管
          </button>
          <button className="wechat-action-btn" title="清空记录"
            onClick={handleClearHistory}>
            清
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages wechat-messages">
        {history.length === 0 && !streaming && (
          <div className="wechat-empty">
            发送第一条消息，开始对话
          </div>
        )}

        {history.map((msg, i) => (
          <MessageBubble key={i} msg={msg} name={name} />
        ))}

        {streaming && streamingText && (
          <div className="chat-bubble-wrap assistant">
            <div className="chat-avatar wechat-avatar">{name[0]}</div>
            <div className={`chat-bubble streaming`}>{streamingText}</div>
          </div>
        )}

        {streaming && !streamingText && (
          <div className="chat-bubble-wrap assistant">
            <div className="chat-avatar wechat-avatar">{name[0]}</div>
            <div className="chat-bubble" style={{ color: 'var(--text2)', fontStyle: 'italic' }}>
              ...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="chat-input-area wechat-input-area">
        <button className="wechat-plus-btn" type="button" title="更多">
          +
        </button>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={`给 ${name} 发消息...`}
          disabled={streaming}
          rows={1}
          style={{ resize: 'none' }}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!input.trim() || streaming}
        >
          发送
        </button>
      </div>
    </div>
  )
}

function MessageBubble({ msg, name }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`chat-bubble-wrap ${isUser ? 'user' : 'assistant'}`}>
      {!isUser && <div className="chat-avatar wechat-avatar">{name[0]}</div>}
      <div className="chat-bubble">{msg.content}</div>
      {isUser && <div className="chat-avatar wechat-avatar">我</div>}
    </div>
  )
}
