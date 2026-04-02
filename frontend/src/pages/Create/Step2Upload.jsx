import { useState, useRef } from 'react'
import { api } from '../../api'
import { useToast } from '../../components/Toast'

const TABS = [
  { id: 'wechat', label: '微信', icon: '💬' },
  { id: 'imessage', label: 'iMessage', icon: '📱' },
  { id: 'sms', label: '短信', icon: '📨' },
  { id: 'social', label: '社交媒体', icon: '🌐' },
  { id: 'photo', label: '照片', icon: '📷' },
  { id: 'text', label: '直接粘贴', icon: '📝' },
]

function DropZone({ accept, multiple, onFiles, hint }) {
  const [drag, setDrag] = useState(false)
  const inputRef = useRef()

  function handleDrop(e) {
    e.preventDefault()
    setDrag(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) onFiles(files)
  }

  return (
    <div
      className={`dropzone${drag ? ' dragover' : ''}`}
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        style={{ display: 'none' }}
        onChange={e => {
          const files = Array.from(e.target.files)
          if (files.length) onFiles(files)
          e.target.value = ''
        }}
      />
      <div className="dropzone-text">
        <div style={{ fontSize: 28, marginBottom: 8 }}>📂</div>
        点击或拖拽文件到此处
        {hint && <div style={{ marginTop: 6, fontSize: 12 }}>{hint}</div>}
      </div>
    </div>
  )
}

export default function Step2Upload({ materials, onChange, onNext, onBack }) {
  const [tab, setTab] = useState('wechat')
  const [loading, setLoading] = useState({})
  const [pasteText, setPasteText] = useState('')
  const [targetName, setTargetName] = useState('')
  const [platform, setPlatform] = useState('weibo')
  const toast = useToast()

  function setLoading2(key, val) {
    setLoading(l => ({ ...l, [key]: val }))
  }

  async function handleFile(type, files, extra = {}) {
    setLoading2(type, true)
    try {
      let result
      if (type === 'photo') {
        result = await api.uploadPhotos(files)
      } else {
        result = await api.uploadFile(type, files[0], { target: targetName, ...extra })
      }
      if (result.content) {
        const label = `${type}:${files[0]?.name || 'photos'}`
        onChange([...materials, { label, content: result.content }])
        toast(`${type} 解析成功`, 'success')
      }
    } catch (err) {
      toast(`解析失败：${err.message}`, 'error')
    } finally {
      setLoading2(type, false)
    }
  }

  function addPaste() {
    if (!pasteText.trim()) return
    const label = `text:粘贴内容`
    onChange([...materials, { label, content: pasteText.trim() }])
    setPasteText('')
    toast('已添加', 'success')
  }

  function removeMaterial(idx) {
    onChange(materials.filter((_, i) => i !== idx))
  }

  return (
    <div>
      <h2 style={{ marginBottom: 8 }}>导入原材料</h2>
      <p style={{ color: 'var(--text2)', fontSize: 14, marginBottom: 20 }}>
        提供聊天记录、照片或描述，可多种来源混用，也可跳过仅凭描述生成。
      </p>

      {/* Target name */}
      <div className="field">
        <label>她的名字 / 备注（用于筛选消息）</label>
        <input
          value={targetName}
          onChange={e => setTargetName(e.target.value)}
          placeholder="可选，留空解析全部消息"
          style={{ maxWidth: 300 }}
        />
      </div>

      {/* Tabs */}
      <div className="tab-list">
        {TABS.map(t => (
          <div
            key={t.id}
            className={`tab-item${tab === t.id ? ' active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.icon} {t.label}
          </div>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'wechat' && (
        <div>
          <DropZone
            accept=".txt,.html,.csv"
            hint="支持 WechatExporter 导出的 txt / html 文件"
            onFiles={files => handleFile('wechat', files, { target: targetName })}
          />
          {loading.wechat && <div className="stage-text">解析中...</div>}
        </div>
      )}

      {tab === 'imessage' && (
        <div>
          <DropZone
            accept=".txt,.csv"
            hint="从 Mac chat.db 导出的 txt / csv 文件"
            onFiles={files => handleFile('imessage', files, { target: targetName })}
          />
          {loading.imessage && <div className="stage-text">解析中...</div>}
        </div>
      )}

      {tab === 'sms' && (
        <div>
          <DropZone
            accept=".xml,.csv,.txt"
            hint="Android SMS Backup & Restore 导出的 xml / csv 文件"
            onFiles={files => handleFile('sms', files, { target: targetName })}
          />
          {loading.sms && <div className="stage-text">解析中...</div>}
        </div>
      )}

      {tab === 'social' && (
        <div>
          <div className="field" style={{ marginBottom: 12 }}>
            <label>平台</label>
            <select value={platform} onChange={e => setPlatform(e.target.value)} style={{ maxWidth: 200 }}>
              <option value="weibo">微博</option>
              <option value="douban">豆瓣</option>
              <option value="xiaohongshu">小红书</option>
              <option value="instagram">Instagram</option>
              <option value="text">其他文本</option>
            </select>
          </div>
          <DropZone
            accept=".json,.html,.txt,.csv"
            hint="各平台 JSON 数据导出文件"
            onFiles={files => handleFile('social', files, { platform, target: targetName })}
          />
          {loading.social && <div className="stage-text">解析中...</div>}
        </div>
      )}

      {tab === 'photo' && (
        <div>
          <DropZone
            accept="image/*,.heic,.heif"
            multiple
            hint="支持 jpg / png / heic，提取照片时间线（不上传图片内容）"
            onFiles={files => handleFile('photo', files)}
          />
          {loading.photo && <div className="stage-text">分析中...</div>}
        </div>
      )}

      {tab === 'text' && (
        <div>
          <textarea
            value={pasteText}
            onChange={e => setPasteText(e.target.value)}
            placeholder="把聊天记录、日记或任何文字粘贴到这里..."
            rows={8}
            style={{ resize: 'vertical', marginBottom: 10 }}
          />
          <button className="btn-secondary" onClick={addPaste} disabled={!pasteText.trim()}>
            ＋ 添加
          </button>
        </div>
      )}

      {/* Added materials */}
      {materials.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 8 }}>
            已添加 {materials.length} 份原材料：
          </div>
          {materials.map((m, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 12px', background: 'var(--bg3)', borderRadius: 6, marginBottom: 6,
              fontSize: 13
            }}>
              <span style={{ color: 'var(--text2)' }}>
                {m.label} ({Math.round(m.content.length / 100) / 10}k 字)
              </span>
              <button
                onClick={() => removeMaterial(i)}
                style={{ background: 'none', color: 'var(--text2)', padding: '2px 6px', fontSize: 12 }}
              >✕</button>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 28 }}>
        <button className="btn-secondary" onClick={onBack}>← 上一步</button>
        <button className="btn-primary" onClick={onNext}>
          {materials.length === 0 ? '跳过，仅凭描述生成 →' : '开始分析 →'}
        </button>
      </div>
    </div>
  )
}
