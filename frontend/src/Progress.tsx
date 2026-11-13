import { useEffect, useState } from 'react'
import type { ProgressEvent } from './types'

type StepState = 'pending' | 'active' | 'done'

export interface ProgressState {
  startedAt: number
  interviews: number
  privacy: StepState
  read: StepState
  verify: StepState
  readStartedAt?: number
  redactions?: { names: number; emails: number; phones: number }
  model?: string
  busy: string[]
  retry?: number
  insights?: number
  quotes?: number
  verified?: number
}

export const TYPICAL_SECONDS = 30

export const initialProgress = (interviews: number): ProgressState => ({
  startedAt: Date.now(),
  interviews,
  privacy: 'active',
  read: 'pending',
  verify: 'pending',
  busy: [],
})

export function reduceProgress(p: ProgressState, e: ProgressEvent): ProgressState {
  switch (e.type) {
    case 'step':
      if (e.step === 'privacy') return { ...p, privacy: 'done', redactions: { names: e.names, emails: e.emails, phones: e.phones } }
      if (e.step === 'read' && e.status === 'active') return { ...p, read: 'active', verify: 'pending', model: e.model, readStartedAt: p.readStartedAt ?? Date.now() }
      if (e.step === 'read' && e.status === 'done') return { ...p, read: 'done', insights: e.insights }
      if (e.step === 'verify' && e.status === 'active') return { ...p, verify: 'active', quotes: e.quotes }
      if (e.step === 'verify' && e.status === 'done') return { ...p, read: 'done', verify: 'done', quotes: e.quotes, verified: e.verified }
      return p
    case 'model_busy':
      return { ...p, busy: [...p.busy, e.model] }
    case 'retry':
      // The model's quotes did not all match: it gets one chance to correct them.
      return { ...p, read: 'active', verify: 'pending', retry: e.problems }
    default:
      return p
  }
}

export const prettyModel = (m?: string) =>
  (m ?? 'The AI')
    .replace(/^[\w-]+:/, '')
    .split('-')
    .map((w) => (w === 'gemini' ? 'Gemini' : /^\d/.test(w) ? w : w[0].toUpperCase() + w.slice(1)))
    .join(' ')

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function listJoin(items: string[]) {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** Fraction 0..1. Real events move it forward; while the model reads, it eases toward 85%. */
function fraction(p: ProgressState, now: number, done: boolean) {
  if (done || p.verify === 'done') return 1
  if (p.verify === 'active') return 0.92
  if (p.read === 'done') return 0.88
  if (p.read === 'active' && p.readStartedAt) {
    const t = (now - p.readStartedAt) / 1000
    return 0.12 + 0.73 * (1 - Math.exp(-t / (TYPICAL_SECONDS * 0.8)))
  }
  return p.privacy === 'done' ? 0.12 : 0.04
}

export function ProgressPanel({ p, done, onCancel }: { p: ProgressState; done: boolean; onCancel: () => void }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (done) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [done])

  const elapsed = Math.floor((now - p.startedAt) / 1000)
  const r = p.redactions
  const replaced = r
    ? [r.names && plural(r.names, 'name mention'), r.emails && plural(r.emails, 'email'), r.phones && plural(r.phones, 'phone number')].filter(Boolean) as string[]
    : []

  const privacyDetail =
    p.privacy === 'done' ? (replaced.length ? `Replaced ${listJoin(replaced)}` : 'Nothing needed replacing') : 'Replacing names, emails and phone numbers'

  let readDetail = 'The AI reads the interviews'
  if (p.read === 'active') {
    const busy = p.busy.length ? `${listJoin(p.busy.map(prettyModel))} ${p.busy.length === 1 ? 'is' : 'are'} busy, so ` : ''
    readDetail = p.retry
      ? `${plural(p.retry, 'quote')} did not match the transcripts. ${prettyModel(p.model)} is correcting ${p.retry === 1 ? 'it' : 'them'}`
      : `${busy}${prettyModel(p.model)} is reading ${plural(p.interviews, 'interview')}`
  } else if (p.read === 'done') {
    readDetail = `Found ${plural(p.insights ?? 0, 'insight')} with ${prettyModel(p.model)}`
  }

  const verifyDetail =
    p.verify === 'done'
      ? `${p.verified} of ${plural(p.quotes ?? 0, 'quote')} found word for word`
      : p.verify === 'active'
        ? `Checking ${plural(p.quotes ?? 0, 'quote')}`
        : 'Every quote is matched word for word against the transcripts'

  const steps: [string, StepState, string][] = [
    ['Protect privacy', p.privacy, privacyDetail],
    ['Find insights', p.read, readDetail],
    ['Check every quote', p.verify, verifyDetail],
  ]
  const current = steps.find(([, s]) => s === 'active')
  const slow = !done && elapsed > TYPICAL_SECONDS

  return (
    <div className="progress">
      <div className="progress-head">
        <strong>{done ? 'Done' : `Analyzing ${plural(p.interviews, 'interview')}`}</strong>
        <span className="muted time" aria-hidden="true">
          {elapsed}s{!done && elapsed <= TYPICAL_SECONDS ? ` · usually about ${TYPICAL_SECONDS}s` : ''}
        </span>
        {!done && <button className="ghost cancel" onClick={onCancel}>Cancel</button>}
      </div>

      <div className="bar" role="progressbar" aria-label="Progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(fraction(p, now, done) * 100)}>
        <span style={{ transform: `scaleX(${fraction(p, now, done)})` }} />
      </div>

      <ol className="stepper">
        {steps.map(([title, state, detail]) => (
          <li key={title} className={state}>
            <span className="dot" aria-hidden="true">
              {state === 'done' && (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 5 5 9-10" /></svg>
              )}
            </span>
            <span>
              <strong>{title}</strong>
              <span className="muted">{detail}</span>
            </span>
          </li>
        ))}
      </ol>

      {slow && <p className="muted slow">Taking longer than usual. The free AI models are busy, so this can take up to a minute.</p>}

      <span className="sr-only" role="status">
        {done ? 'Analysis complete' : current ? `${current[0]}: ${current[2]}` : ''}
      </span>
    </div>
  )
}
