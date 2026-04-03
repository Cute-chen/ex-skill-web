export default function Step1Intake({ data, onChange, onNext }) {
  function set(k, v) {
    onChange({ ...data, [k]: v })
  }

  const canNext = data.name && data.name.trim()
  const mode = data.analysis_mode || 'direct'

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>基础信息</h2>

      <div className="field">
        <label>昵称 / 代号 *</label>
        <input
          value={data.name || ''}
          onChange={e => set('name', e.target.value)}
          placeholder="小美、A、她..."
          autoFocus
        />
      </div>

      <div className="field">
        <label>基本信息 <span style={{ color: 'var(--text2)', fontWeight: 400 }}>(可选)</span></label>
        <textarea
          value={data.basic_info || ''}
          onChange={e => set('basic_info', e.target.value)}
          placeholder="在一起三年 大学同学 分手一年 她做设计"
          rows={3}
          style={{ resize: 'vertical' }}
        />
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 4 }}>
          在一起多久、怎么认识、分手多久、她的职业……想到什么写什么
        </div>
      </div>

      <div className="field">
        <label>性格画像 <span style={{ color: 'var(--text2)', fontWeight: 400 }}>(可选)</span></label>
        <textarea
          value={data.personality || ''}
          onChange={e => set('personality', e.target.value)}
          placeholder="ENFP 双子座 焦虑型 爱撒娇 翻旧账 嘴上说不在意其实比谁都在意"
          rows={3}
          style={{ resize: 'vertical' }}
        />
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 4 }}>
          MBTI · 星座 · 依恋类型 · 恋爱标签 · 你的主观印象
        </div>
      </div>

      <div className="field">
        <label>分析策略</label>
        <div className="analysis-mode-grid">
          <button
            type="button"
            className={`analysis-mode-card${mode === 'direct' ? ' active' : ''}`}
            onClick={() => set('analysis_mode', 'direct')}
          >
            <strong>Claude 同款极速（推荐）</strong>
            <span>单流程直连分析，速度最快，日常使用优先选这个。</span>
          </button>
          <button
            type="button"
            className={`analysis-mode-card${mode === 'fidelity' ? ' active' : ''}`}
            onClick={() => set('analysis_mode', 'fidelity')}
          >
            <strong>保真优先</strong>
            <span>多轮分块分析，细节最完整，但耗时最长。</span>
          </button>
          <button
            type="button"
            className={`analysis-mode-card${mode === 'fast' ? ' active' : ''}`}
            onClick={() => set('analysis_mode', 'fast')}
          >
            <strong>快速分块</strong>
            <span>大分块+少轮合并，速度和细节均衡。</span>
          </button>
        </div>
        <div className="field-help">
          后续可在“追加新材料”中继续补充内容，逐步提高完整度。
        </div>
      </div>

      <button className="btn-primary" onClick={onNext} disabled={!canNext} style={{ marginTop: 8 }}>
        下一步 →
      </button>
    </div>
  )
}
