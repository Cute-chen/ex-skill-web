import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import ExCard from '../components/ExCard'

export default function Home() {
  const [exes, setExes] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const data = await api.listExes()
        if (mounted) setExes(data)
      } catch (e) {
        console.error(e)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    load()
    const timer = setInterval(load, 4000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [])

  function handleDeleted(slug) {
    setExes(e => e.filter(x => x.slug !== slug))
  }

  if (loading) return <div style={{ color: 'var(--text2)', padding: 40 }}>加载中...</div>

  if (exes.length === 0) {
    return (
      <div className="empty-state">
        <h2>还没有「忘不掉的她」档案</h2>
        <p>导入聊天记录和描述，把回忆整理成可对话的记忆体。</p>
        <button className="btn-primary" onClick={() => navigate('/create')}>
          ✨ 新建第一个
        </button>
      </div>
    )
  }

  const processingCount = exes.filter(x => x.build_status === 'processing').length
  const previewCount = exes.filter(x => x.build_status === 'preview_ready').length

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">全部 ({exes.length})</h1>
          {(processingCount > 0 || previewCount > 0) && (
            <div style={{ fontSize: 13, color: 'var(--text2)' }}>
              {processingCount > 0 ? `处理中 ${processingCount} 个` : ''}
              {processingCount > 0 && previewCount > 0 ? ' · ' : ''}
              {previewCount > 0 ? `待确认 ${previewCount} 个` : ''}
            </div>
          )}
        </div>
        <button className="btn-primary" onClick={() => navigate('/create')}>✨ 新建</button>
      </div>
      <div className="ex-grid">
        {exes.map(ex => (
          <ExCard key={ex.slug} ex={ex} onDeleted={handleDeleted} />
        ))}
      </div>
    </div>
  )
}
