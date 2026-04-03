import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api, streamSSE } from '../api'
import { useToast } from '../components/Toast'

const POLL_INTERVAL = 3000

function PreviewSection({ title, content }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="preview-section">
      <div className="preview-header" onClick={() => setOpen(v => !v)}>
        <span>{title}</span>
        <span style={{ fontSize: 12, color: 'var(--text2)' }}>{open ? '▲ 收起' : '▼ 展开'}</span>
      </div>
      {open && <div className="preview-body">{content || '暂无内容'}</div>}
    </div>
  )
}

export default function ExDetail() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const [ex, setEx] = useState(null)
  const [versions, setVersions] = useState([])
  const [correction, setCorrection] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [updateMaterials, setUpdateMaterials] = useState('')
  const [updating, setUpdating] = useState(false)
  const [updateStage, setUpdateStage] = useState('')
  const [confirming, setConfirming] = useState(false)
  const pollRef = useRef(null)

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  async function loadEx() {
    const data = await api.getEx(slug)
    setEx(data)
    return data
  }

  async function loadVersions() {
    try {
      const list = await api.listVersions(slug)
      setVersions(list)
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    let cancelled = false
    stopPolling()

    ;(async () => {
      try {
        const data = await api.getEx(slug)
        if (cancelled) return
        setEx(data)
        if ((data.meta?.build_status || 'ready') === 'ready') {
          loadVersions()
        } else {
          setVersions([])
        }
      } catch (err) {
        toast(err.message, 'error')
        navigate('/')
      }
    })()

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [slug])

  const buildStatus = ex?.meta?.build_status || 'ready'
  const buildProgress = ex?.meta?.build_progress || 0
  const buildStage = ex?.meta?.build_stage || ''
  const buildError = ex?.meta?.build_error || ''
  const isReady = buildStatus === 'ready'
  const isProcessing = buildStatus === 'processing'
  const isPreviewReady = buildStatus === 'preview_ready'
  const isFailed = buildStatus === 'failed' || buildStatus === 'cancelled'

  useEffect(() => {
    stopPolling()
    if (!slug || !isProcessing) return

    pollRef.current = setInterval(async () => {
      try {
        const latest = await api.getEx(slug)
        setEx(latest)
        const nextStatus = latest.meta?.build_status || 'ready'
        if (nextStatus !== 'processing') {
          stopPolling()
          if (nextStatus === 'ready') loadVersions()
        }
      } catch (err) {
        console.error(err)
      }
    }, POLL_INTERVAL)

    return () => stopPolling()
  }, [slug, isProcessing])

  async function handleCorrection() {
    if (!isReady || !correction.trim()) return
    setSubmitting(true)
    try {
      await api.addCorrection(slug, correction)
      toast('纠正已记录 ✓', 'success')
      setCorrection('')
      loadEx()
      loadVersions()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  function handleUpdate() {
    if (!isReady || !updateMaterials.trim()) return
    setUpdating(true)
    setUpdateStage('准备中...')

    streamSSE(
      `/api/exes/${slug}/update`,
      { materials: [updateMaterials] },
      (data) => {
        if (data.error) {
          toast(`更新失败：${data.error}`, 'error')
          setUpdating(false)
          return
        }
        if (data.stage === 'done') {
          toast('已追加并更新记忆档案 ✓', 'success')
          setUpdateMaterials('')
          setUpdating(false)
          setUpdateStage('')
          loadEx()
          loadVersions()
        } else {
          setUpdateStage(data.stage || '')
        }
      },
      (err) => {
        toast(err.message, 'error')
        setUpdating(false)
      }
    )
  }

  async function handleRollback(version) {
    if (!isReady) return
    if (!confirm(`回滚到 ${version}？当前版本将被覆盖。`)) return
    try {
      await api.rollback(slug, version)
      toast(`已回滚到 ${version}`, 'success')
      loadEx()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function handleConfirmPreview() {
    if (!isPreviewReady) return
    setConfirming(true)
    try {
      await api.confirmCreate({ slug })
      toast('已确认创建，记忆档案已生成 ✓', 'success')
      const latest = await loadEx()
      if ((latest.meta?.build_status || 'ready') === 'ready') {
        loadVersions()
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setConfirming(false)
    }
  }

  function statusButtonText() {
    if (isReady) return '💬 开始聊天'
    if (isProcessing) return `处理中 ${buildProgress}%`
    if (isPreviewReady) return '等待确认创建'
    if (buildStatus === 'cancelled') return '任务已取消'
    return '处理失败'
  }

  if (!ex) return <div style={{ color: 'var(--text2)', padding: 40 }}>加载中...</div>

  const { meta } = ex

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="btn-secondary" style={{ padding: '6px 10px' }} onClick={() => navigate(-1)}>←</button>
          <h1 className="page-title">{meta.name}</h1>
        </div>
        <button className="btn-primary" disabled={!isReady} onClick={() => navigate(`/chat/${slug}`)}>
          {statusButtonText()}
        </button>
      </div>

      <div style={{ maxWidth: 640 }}>
        {(isProcessing || isFailed) && (
          <div className="card detail-section" style={{ marginBottom: 20 }}>
            <h3>后台处理状态</h3>
            <div style={{ fontSize: 14, color: 'var(--text2)', marginBottom: 12 }}>
              {buildStage || (isProcessing ? '处理中' : (buildStatus === 'cancelled' ? '任务已取消' : '处理失败'))}
            </div>
            {isProcessing && (
              <>
                <div className="progress-bar" style={{ margin: '0 0 8px' }}>
                  <div className="progress-fill" style={{ width: `${buildProgress}%` }} />
                </div>
                <div style={{ fontSize: 12, color: 'var(--text2)' }}>
                  {buildProgress}% · 可在“全部”页持续查看进度
                </div>
              </>
            )}
            {buildError && (
              <div style={{ marginTop: 10, color: 'var(--danger)', fontSize: 13 }}>
                {buildError}
              </div>
            )}
          </div>
        )}

        {isPreviewReady && (
          <div className="card detail-section" style={{ marginBottom: 20 }}>
            <h3>预览结果（待确认）</h3>
            <p style={{ fontSize: 14, color: 'var(--text2)', marginBottom: 16 }}>
              数据已处理完成。确认后会写入最终记忆档案，并变为可聊天状态。
            </p>

            <PreviewSection
              title="📚 共同记忆（片段）"
              content={ex.preview?.memories_preview}
            />
            <PreviewSection
              title="🧠 Persona 性格（片段）"
              content={ex.preview?.persona_preview}
            />

            {!ex.preview && (
              <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 6 }}>
                预览内容尚未加载完整，仍可尝试直接确认创建。
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
              <button className="btn-secondary" onClick={() => navigate('/')}>返回全部</button>
              <button className="btn-primary" onClick={handleConfirmPreview} disabled={confirming}>
                {confirming ? '确认中...' : `✅ 确认创建「${meta.name}」`}
              </button>
            </div>
          </div>
        )}

        {isReady && (
          <>
        {/* Meta info */}
        <div className="card detail-section" style={{ marginBottom: 20 }}>
          <div className="detail-meta-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 14 }}>
            {meta.profile?.duration && <div><span style={{ color: 'var(--text2)' }}>在一起：</span>{meta.profile.duration}</div>}
            {meta.profile?.mbti || meta.tags?.mbti ? <div><span style={{ color: 'var(--text2)' }}>MBTI：</span>{meta.tags?.mbti || meta.profile?.mbti}</div> : null}
            {meta.tags?.attachment && <div><span style={{ color: 'var(--text2)' }}>依恋类型：</span>{meta.tags.attachment}</div>}
            <div><span style={{ color: 'var(--text2)' }}>版本：</span>{meta.version}</div>
            <div>
              <span style={{ color: 'var(--text2)' }}>分析策略：</span>
              {meta.analysis_mode === 'direct'
                ? 'Claude 同款极速'
                : meta.analysis_mode === 'fast'
                  ? '快速分块'
                  : '保真优先'}
            </div>
            <div><span style={{ color: 'var(--text2)' }}>纠正次数：</span>{meta.corrections_count}</div>
          </div>
          {meta.impression && (
            <div style={{ marginTop: 12, fontSize: 14, color: 'var(--text2)', fontStyle: 'italic' }}>
              "{meta.impression}"
            </div>
          )}
        </div>

        {/* Correction */}
        <div className="detail-section">
          <h3>对话纠正</h3>
          <textarea
            value={correction}
            onChange={e => setCorrection(e.target.value)}
            placeholder='例如：她不会这样，她生气了不会直接说，应该是已读不回然后发"哦"'
            rows={3}
            style={{ resize: 'vertical', marginBottom: 10 }}
          />
          <button className="btn-primary" onClick={handleCorrection} disabled={!correction.trim() || submitting}>
            {submitting ? '处理中...' : '提交纠正'}
          </button>
        </div>

        {/* Update */}
        <div className="detail-section" style={{ marginTop: 24 }}>
          <h3>追加新材料</h3>
          <textarea
            value={updateMaterials}
            onChange={e => setUpdateMaterials(e.target.value)}
            placeholder="粘贴新的聊天记录或任何文字..."
            rows={5}
            style={{ resize: 'vertical', marginBottom: 10 }}
            disabled={updating}
          />
          {updating && <div className="stage-text">{updateStage}</div>}
          <button className="btn-primary" onClick={handleUpdate} disabled={!updateMaterials.trim() || updating}>
            {updating ? '更新中...' : '追加并更新'}
          </button>
        </div>

        {/* Version history */}
        {versions.length > 0 && (
          <div className="detail-section" style={{ marginTop: 24 }}>
            <h3>版本历史</h3>
            {versions.map(v => (
              <div key={v.version} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px', background: 'var(--bg3)', borderRadius: 8, marginBottom: 6
              }}>
                <div>
                  <span style={{ fontWeight: 600 }}>{v.version}</span>
                  {v.ts && <span style={{ color: 'var(--text2)', fontSize: 13, marginLeft: 10 }}>
                    {new Date(v.ts).toLocaleDateString('zh-CN')}
                  </span>}
                </div>
                <button className="btn-secondary" style={{ fontSize: 12, padding: '4px 10px' }}
                  onClick={() => handleRollback(v.version)}>
                  回滚
                </button>
              </div>
            ))}
          </div>
        )}
          </>
        )}
      </div>
    </div>
  )
}
