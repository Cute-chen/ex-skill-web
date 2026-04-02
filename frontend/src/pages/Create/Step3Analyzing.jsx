export default function Step3Analyzing({ stage, progress, jobId, analysisMode }) {
  const modeLabel = analysisMode === 'fast' ? '极限速度（允许少量细节损失）' : '保真优先加速'
  return (
    <div style={{ textAlign: 'center', padding: '60px 0' }}>
      <div style={{ fontSize: 40, marginBottom: 20 }}>
        {progress < 100 ? '✨' : '🎉'}
      </div>
      <h2 style={{ marginBottom: 16 }}>
        {progress < 100 ? '正在蒸馏回忆...' : '分析完成'}
      </h2>
      <div className="stage-text">{stage}</div>
      <div className="progress-bar" style={{ maxWidth: 360, margin: '16px auto 0' }}>
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>
      <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text2)' }}>
        {progress}%
      </div>
      {jobId && (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text2)' }}>
          任务ID：{jobId}
        </div>
      )}
      <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text2)' }}>
        当前策略：{modeLabel}
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text2)' }}>
        任务在后台执行中，你可以留在页面定时查看进度。
      </div>
    </div>
  )
}
