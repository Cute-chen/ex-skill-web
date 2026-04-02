import { useState } from 'react'

function PreviewSection({ title, content }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="preview-section">
      <div className="preview-header" onClick={() => setOpen(o => !o)}>
        <span>{title}</span>
        <span style={{ fontSize: 12, color: 'var(--text2)' }}>{open ? '▲ 收起' : '▼ 展开'}</span>
      </div>
      {open && (
        <div className="preview-body">{content}</div>
      )}
    </div>
  )
}

export default function Step4Preview({ data, onConfirm, onBack, saving }) {
  return (
    <div>
      <h2 style={{ marginBottom: 8 }}>预览并确认</h2>
      <p style={{ color: 'var(--text2)', fontSize: 14, marginBottom: 24 }}>
        确认后将生成 <strong style={{ color: 'var(--text)' }}>{data.name}</strong> 的记忆档案文件。
        后续可继续追加资料或对话纠正。
      </p>

      <PreviewSection title="📚 共同记忆（片段）" content={data.memories_preview} />
      <PreviewSection title="🧠 Persona 性格（片段）" content={data.persona_preview} />

      <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
        <button className="btn-secondary" onClick={onBack} disabled={saving}>← 重新生成</button>
        <button className="btn-primary" onClick={onConfirm} disabled={saving}>
          {saving ? '保存中...' : `✅ 确认创建「${data.name}」`}
        </button>
      </div>
    </div>
  )
}
