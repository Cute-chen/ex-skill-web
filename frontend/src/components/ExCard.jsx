import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useToast } from './Toast'

function fmtDate(s) {
  if (!s) return ''
  try {
    return new Date(s).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
  } catch { return s }
}

export default function ExCard({ ex, onDeleted }) {
  const navigate = useNavigate()
  const toast = useToast()

  const tags = [
    ex.tags?.mbti,
    ex.tags?.attachment,
    ...(ex.tags?.personality || []),
  ].filter(Boolean).slice(0, 4)

  const buildStatus = ex.build_status || 'ready'
  const isProcessing = buildStatus === 'processing'
  const isPreviewReady = buildStatus === 'preview_ready'
  const isFailed = buildStatus === 'failed'
  const isCancelled = buildStatus === 'cancelled'

  async function handleDelete(e) {
    e.stopPropagation()
    if (isProcessing) return
    if (!confirm(`确认删除「${ex.name}」？此操作不可撤销。`)) return
    try {
      await api.deleteEx(ex.slug)
      toast('已删除', 'success')
      onDeleted && onDeleted(ex.slug)
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  function openMain() {
    if (isProcessing) return
    if (isPreviewReady || isFailed || isCancelled) {
      navigate(`/ex/${ex.slug}`)
      return
    }
    navigate(`/chat/${ex.slug}`)
  }

  function statusLabel() {
    if (isProcessing) return `处理中 ${ex.build_progress || 0}%`
    if (isPreviewReady) return '待确认'
    if (isCancelled) return '已取消'
    if (isFailed) return '处理失败'
    return ''
  }

  return (
    <div className={`ex-card${isProcessing ? ' disabled' : ''}`} onClick={openMain}>
      <div className="ex-card-actions">
        <button
          className="icon-btn"
          title={isProcessing ? '处理中不可查看详情' : '管理'}
          disabled={isProcessing}
          onClick={e => { e.stopPropagation(); navigate(`/ex/${ex.slug}`) }}
        >
          ⚙
        </button>
        <button
          className="icon-btn"
          title={isProcessing ? '处理中不可删除' : '删除'}
          disabled={isProcessing}
          onClick={handleDelete}
        >
          ✕
        </button>
      </div>
      <div className="ex-card-name">{ex.name}</div>
      {(isProcessing || isPreviewReady || isFailed || isCancelled) && (
        <div className={`ex-card-status ${buildStatus}`}>
          {statusLabel()}
          {ex.build_stage ? ` · ${ex.build_stage}` : ''}
        </div>
      )}
      {ex.impression && (
        <div className="ex-card-impression">{ex.impression}</div>
      )}
      <div className="ex-card-tags">
        {tags.map(t => <span key={t} className="tag">{t}</span>)}
      </div>
      <div className="ex-card-meta">
        {ex.profile?.duration && <span>{ex.profile.duration} · </span>}
        创建于 {fmtDate(ex.created_at)}
      </div>
      {isProcessing && (
        <div className="mini-progress">
          <div className="mini-progress-fill" style={{ width: `${ex.build_progress || 0}%` }} />
        </div>
      )}
    </div>
  )
}
