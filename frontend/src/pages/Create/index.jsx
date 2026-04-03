import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { useToast } from '../../components/Toast'
import Step1Intake from './Step1Intake'
import Step2Upload from './Step2Upload'
import Step3Analyzing from './Step3Analyzing'
import Step4Preview from './Step4Preview'

const STEP_LABELS = ['基础信息', '导入原材料', 'AI 分析中', '预览确认']

export default function Create() {
  const [step, setStep] = useState(0)
  const [intake, setIntake] = useState({
    name: '',
    basic_info: '',
    personality: '',
    analysis_mode: 'direct',
  })
  const [materials, setMaterials] = useState([])
  const [analyzeStage, setAnalyzeStage] = useState('')
  const [analyzeProgress, setAnalyzeProgress] = useState(0)
  const [previewData, setPreviewData] = useState(null)
  const [saving, setSaving] = useState(false)
  const [jobId, setJobId] = useState('')
  const toast = useToast()
  const navigate = useNavigate()
  const pollTimerRef = useRef(null)
  const pollErrorShownRef = useRef(false)

  function stopPolling() {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }

  useEffect(() => {
    return () => stopPolling()
  }, [])

  async function pollJob(id, materialLabels) {
    try {
      const job = await api.getCreateJob(id)
      pollErrorShownRef.current = false

      if (job.status === 'failed' || job.status === 'cancelled') {
        stopPolling()
        toast(`分析失败：${job.error || '任务失败'}`, 'error')
        setStep(1)
        return true
      }

      if (job.stage) setAnalyzeStage(job.stage)
      if (typeof job.progress === 'number') setAnalyzeProgress(job.progress)

      if (job.status === 'preview_ready' && job.data) {
        stopPolling()
        const data = {
          ...job.data,
          materials_labels: job.data.materials_labels || materialLabels,
        }
        setPreviewData(data)
        setAnalyzeProgress(100)
        setStep(3)
        return true
      }
      return false
    } catch (err) {
      setAnalyzeStage('读取任务进度失败，重试中...')
      if (!pollErrorShownRef.current) {
        toast(`读取任务进度失败：${err.message}`, 'error')
        pollErrorShownRef.current = true
      }
      return false
    }
  }

  async function startAnalysis() {
    stopPolling()
    setStep(2)
    setAnalyzeStage('任务创建中...')
    setAnalyzeProgress(2)
    setPreviewData(null)

    const materialTexts = materials.map(m => m.content)
    const materialLabels = materials.map(m => m.label)

    try {
      const res = await api.createCreateJob({
        name: intake.name,
        basic_info: intake.basic_info,
        personality: intake.personality,
        materials: materialTexts,
        materials_labels: materialLabels,
        analysis_mode: intake.analysis_mode || 'direct',
      })

      const id = res.job_id
      setJobId(id)
      setAnalyzeStage('后台分析中...')

      const done = await pollJob(id, materialLabels)
      if (!done) {
        pollTimerRef.current = setInterval(() => {
          pollJob(id, materialLabels)
        }, 2000)
      }
    } catch (err) {
      toast(`任务创建失败：${err.message}`, 'error')
      setStep(1)
    }
  }

  async function handleConfirm() {
    if (!previewData) return
    setSaving(true)
    try {
      await api.confirmCreate({
        slug: previewData.slug,
        name: previewData.name,
        intake: previewData.intake,
        memories_content: previewData.memories_content,
        persona_content: previewData.persona_content,
        materials_labels: previewData.materials_labels || [],
      })
      toast(`「${previewData.name}」已创建 🎉`, 'success')
      navigate(`/chat/${previewData.slug}`)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">新建「忘不掉的她」</h1>
      </div>

      <div className="wizard">
        {/* Step indicator */}
        <div className="wizard-steps">
          {STEP_LABELS.map((label, i) => (
            <div
              key={i}
              className={`wizard-step${i === step ? ' active' : i < step ? ' done' : ''}`}
            >
              {label}
            </div>
          ))}
        </div>

        {step === 0 && (
          <Step1Intake
            data={intake}
            onChange={setIntake}
            onNext={() => setStep(1)}
          />
        )}
        {step === 1 && (
          <Step2Upload
            materials={materials}
            onChange={setMaterials}
            onNext={startAnalysis}
            onBack={() => setStep(0)}
          />
        )}
        {step === 2 && (
          <Step3Analyzing
            stage={analyzeStage}
            progress={analyzeProgress}
            jobId={jobId}
            analysisMode={intake.analysis_mode || 'direct'}
          />
        )}
        {step === 3 && previewData && (
          <Step4Preview
            data={previewData}
            onConfirm={handleConfirm}
            onBack={() => setStep(1)}
            saving={saving}
          />
        )}
      </div>
    </div>
  )
}
