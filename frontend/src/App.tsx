import { useEffect, useRef, useState } from 'react'
import { exampleResult, exampleTranscripts } from './examples'
import { HowItWorks, REPO_URL } from './HowItWorks'
import { ProgressPanel, initialProgress, reduceProgress, type ProgressState } from './Progress'
import type { AnalyzeResponse, Evidence, Insight, InsightKind, ProgressEvent, TranscriptDraft, TranscriptOut } from './types'

const API = `${import.meta.env.BASE_URL}api`
const MAX_PER = 12_000
const MAX_TOTAL = 30_000
const MAX_TRANSCRIPTS = 5

const GROUPS: { kind: InsightKind; title: string }[] = [
  { kind: 'pain_point', title: 'Pain points' },
  { kind: 'need', title: 'Needs' },
  { kind: 'positive', title: 'What works' },
]

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

let nextId = 1
const newDraft = (title = '', text = ''): TranscriptDraft => ({ id: String(nextId++), title, text })
const exampleDrafts = () => exampleTranscripts.map((e) => newDraft(e.title, e.text))

type Selection = { pid: string; start: number; end: number; key: string }

// semtip.nl/koos#example opens straight into the saved example result.
const startWithExample = window.location.hash === '#example' && exampleResult != null

const ICONS = {
  plus: 'M12 5v14M5 12h14',
  upload: 'M12 15V3m0 0L7 8m5-5 5 5M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4',
  back: 'M19 12H5m0 0 6-6m-6 6 6 6',
  chevron: 'm9 6 6 6-6 6',
  close: 'M6 6l12 12M18 6 6 18',
}

function Icon({ name, size = 18 }: { name: keyof typeof ICONS; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  )
}

export default function App() {
  const [drafts, setDrafts] = useState<TranscriptDraft[]>(() => (startWithExample ? exampleDrafts() : [newDraft()]))
  const [result, setResult] = useState<AnalyzeResponse | null>(startWithExample ? exampleResult : null)
  const [isExample, setIsExample] = useState(startWithExample)
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<ProgressState | null>(null)
  const [finished, setFinished] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  const total = drafts.reduce((n, d) => n + d.text.length, 0)
  const tooLong = drafts.some((d) => d.text.length > MAX_PER) || total > MAX_TOTAL
  const usable = drafts.filter((d) => d.text.trim().length >= 20)
  const canAnalyze = usable.length > 0 && !tooLong && !loading
  const blank = drafts.every((d) => !d.text.trim() && !d.title.trim())

  const update = (id: string, patch: Partial<TranscriptDraft>) =>
    setDrafts((all) => all.map((x) => (x.id === id ? { ...x, ...patch } : x)))
  const remove = (id: string) =>
    setDrafts((all) => {
      const rest = all.filter((x) => x.id !== id)
      return rest.length ? rest : [newDraft()]
    })

  function loadExamples() {
    setDrafts(exampleDrafts())
    setError(null)
  }

  function showExample() {
    if (!exampleResult) return
    setDrafts(exampleDrafts())
    setResult(exampleResult)
    setIsExample(true)
    setError(null)
  }

  async function onFiles(files: FileList | null) {
    if (!files) return
    const empty = drafts.filter((d) => !d.text.trim() && !d.title.trim())
    const kept = drafts.filter((d) => !empty.includes(d))
    const picked = Array.from(files).slice(0, MAX_TRANSCRIPTS - kept.length)
    const loaded = await Promise.all(picked.map(async (f) => newDraft(f.name.replace(/\.[^.]+$/, ''), await f.text())))
    setDrafts([...kept, ...loaded])
  }

  async function analyze() {
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setFinished(false)
    setError(null)
    setProgress(initialProgress(usable.length))
    requestAnimationFrame(() => progressRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))

    try {
      const res = await fetch(`${API}/analyze/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcripts: usable.map(({ title, text }) => ({ title, text })) }),
        signal: controller.signal,
      })
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : `The server returned an error (${res.status}). Try again.`)
      }

      // Read newline-delimited JSON events as they arrive.
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      let final: AnalyzeResponse | null = null
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += value
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.trim()) continue
          const event = JSON.parse(line) as ProgressEvent
          if (event.type === 'error') throw new Error(event.message)
          if (event.type === 'result') final = event.data
          else setProgress((p) => (p ? reduceProgress(p, event) : p))
        }
      }
      if (!final) throw new Error('The connection closed before the analysis finished. Try again.')

      // Let people see every step checked off before the results replace the page.
      setFinished(true)
      await new Promise((r) => setTimeout(r, 700))
      setResult(final)
      setIsExample(false)
    } catch (e) {
      if (controller.signal.aborted) return
      setError(e instanceof Error && e.message !== 'Failed to fetch' ? e.message : 'Could not reach the server. Check your connection and try again.')
    } finally {
      abortRef.current = null
      setLoading(false)
      setProgress(null)
    }
  }

  function cancel() {
    abortRef.current?.abort()
  }

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [result])

  if (result) {
    return (
      <div className="page wide">
        <Results result={result} isExample={isExample} onEdit={() => setResult(null)} />
        <Footer />
      </div>
    )
  }

  return (
    <div className="page">
      <header className="intro">
        <h1>Research Assistant</h1>
        <p className="muted">
          I built this with Claude Code to learn the stack behind your role (FastAPI, Pydantic and React) by building
          something real. AI is
          good at summarizing interviews, but designers rightly don't trust a summary they can't trace back. If one quote is
          invented, the whole synthesis is suspect. So this tool treats the model as an untrusted narrator and lets the user
          verify the results (<a href={REPO_URL} target="_blank" rel="noreferrer">read more on GitHub</a>).
        </p>
        <HowItWorks intro={false} />
      </header>

      {blank && exampleResult && (
        <button className="callout" onClick={loadExamples}>
          <span>
            <strong>Try it with example interviews</strong>
            <span className="muted">Three made-up interviews about an e-bike subscription</span>
          </span>
          <Icon name="chevron" />
        </button>
      )}

      <fieldset className="inputs" disabled={loading}>
      <ol className="drafts">
        {drafts.map((d, i) => (
          <li key={d.id} className="draft">
            <div className="draft-head">
              <input
                aria-label={`Title of interview ${i + 1}`}
                value={d.title}
                placeholder={`Interview ${i + 1}`}
                onChange={(e) => update(d.id, { title: e.target.value })}
              />
              {d.text.length > MAX_PER * 0.8 && (
                <span className={d.text.length > MAX_PER ? 'warn' : 'muted'}>
                  {d.text.length.toLocaleString()} of {MAX_PER.toLocaleString()} characters
                </span>
              )}
              {(drafts.length > 1 || d.text || d.title) && (
                <button className="icon" onClick={() => remove(d.id)} aria-label={`Remove interview ${i + 1}`}>
                  <Icon name="close" />
                </button>
              )}
            </div>
            <textarea
              aria-label={`Transcript of interview ${i + 1}`}
              value={d.text}
              placeholder={'Paste a transcript with speaker labels:\n\nInterviewer: How do you use the app?\nAnna: Every morning, mostly to…'}
              onChange={(e) => update(d.id, { text: e.target.value })}
            />
          </li>
        ))}
      </ol>

      {drafts.length < MAX_TRANSCRIPTS && (
        <div className="add">
          <button className="ghost" onClick={() => setDrafts((d) => [...d, newDraft()])}>
            <Icon name="plus" /> Add interview
          </button>
          <label className="ghost">
            <Icon name="upload" /> Upload .txt files
            <input type="file" accept=".txt,text/plain" multiple hidden onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} />
          </label>
        </div>
      )}

      </fieldset>

      <div className="submit" ref={progressRef}>
        {progress ? (
          <ProgressPanel p={progress} done={finished} onCancel={cancel} />
        ) : (
          <div className="actions">
            <button className="primary" disabled={!canAnalyze} onClick={analyze}>
              {`Analyze ${usable.length > 1 ? plural(usable.length, 'interview') : 'interview'}`}
            </button>
            {exampleResult && <button className="ghost" onClick={showExample}>See an example result</button>}
          </div>
        )}
        {tooLong ? (
          <p className="warn">Too much text. Keep each interview under {MAX_PER.toLocaleString()} characters and the total under {MAX_TOTAL.toLocaleString()}.</p>
        ) : (
          <p className="muted">
            Speaker names, emails and phone numbers are replaced before anything is sent to the AI, and nothing is stored.
          </p>
        )}
        {error && <p className="warn" role="alert">{error}</p>}
      </div>

      <Footer />
    </div>
  )
}

function Footer() {
  return (
    <footer className="footer muted">
      Built by <a href="https://semtip.nl">Sem Tip</a> with FastAPI, PydanticAI, Gemini and React.
    </footer>
  )
}

function Results({ result, isExample, onEdit }: { result: AnalyzeResponse; isExample: boolean; onEdit: () => void }) {
  const { stats, transcripts } = result
  const [sel, setSel] = useState<Selection | null>(null)
  const [tab, setTab] = useState(transcripts[0]?.pid ?? 'P1')

  const kept = result.insights.filter((i) => i.status !== 'dropped')
  const dropped = result.insights.filter((i) => i.status === 'dropped')
  const n = transcripts.length

  function select(ev: Evidence, key: string) {
    if (ev.start == null || ev.end == null) return
    const pid = ev.found_in ?? ev.participant
    setSel({ pid, start: ev.start, end: ev.end, key })
    setTab(pid)
  }

  const allVerified = stats.quotes_verified === stats.quotes_total

  return (
    <>
      <header className="intro">
        <button className="ghost back" onClick={onEdit}><Icon name="back" /> Edit interviews</button>
        <h1>{plural(kept.length, 'insight')} from {plural(n, 'interview')}</h1>
        <p>
          {allVerified
            ? `All ${stats.quotes_total} quotes were found word for word in the transcripts.`
            : `${stats.quotes_verified} of ${stats.quotes_total} quotes were found word for word in the transcripts. The others are marked.`}{' '}
          Select a quote to see it in context.
        </p>
        <p className="muted">
          {isExample ? 'Saved from a real run, so no AI call was made. ' : ''}
          {stats.model.replace(/^google:/, '')}, {stats.seconds} seconds.
        </p>
        <HowItWorks />
      </header>

      {stats.retried && (
        <details className="note">
          <summary>The first answer had {plural(stats.retry_feedback.length, 'quote problem')}, so the model was told what was wrong and tried again.</summary>
          <ul>{stats.retry_feedback.map((f) => <li key={f}>{f}</li>)}</ul>
        </details>
      )}

      <div className="split">
        <div className="insights">
          {GROUPS.map(({ kind, title }) => {
            const items = kept.filter((i) => i.kind === kind)
            if (!items.length) return null
            return (
              <section key={kind} aria-labelledby={`g-${kind}`}>
                <h2 id={`g-${kind}`} className="group-title"><span className={`pill ${kind}`}>{title}</span><span className="count">{items.length}</span></h2>
                {items.map((ins, i) => (
                  <InsightBlock key={ins.title + i} ins={ins} idKey={`${kind}${i}`} sel={sel} onSelect={select} />
                ))}
              </section>
            )
          })}

          {dropped.length > 0 && (
            <details className="note dropped">
              <summary>{plural(dropped.length, 'insight')} left out because none of its quotes could be found</summary>
              {dropped.map((ins, i) => (
                <InsightBlock key={ins.title + i} ins={ins} idKey={`d${i}`} sel={sel} onSelect={select} />
              ))}
            </details>
          )}
        </div>

        <SourceViewer transcripts={transcripts} tab={tab} setTab={setTab} sel={sel} />
      </div>
    </>
  )
}

function InsightBlock({ ins, idKey, sel, onSelect }: {
  ins: Insight; idKey: string; sel: Selection | null; onSelect: (e: Evidence, key: string) => void
}) {
  return (
    <article className={`insight ${ins.status}`}>
      <h3>{ins.title}</h3>
      <p className="muted">{ins.summary}</p>
      <ul className="quotes">
        {ins.evidence.map((e, j) => <Quote key={j} e={e} k={`${idKey}e${j}`} sel={sel} onSelect={onSelect} />)}
      </ul>
      {ins.counter_evidence.length > 0 && (
        <>
          <p className="but muted">But</p>
          <ul className="quotes">
            {ins.counter_evidence.map((e, j) => <Quote key={j} e={e} k={`${idKey}c${j}`} sel={sel} onSelect={onSelect} />)}
          </ul>
        </>
      )}
    </article>
  )
}

function flag(e: Evidence) {
  if (e.status === 'near') return `Close but not exact, ${e.score}% similar`
  if (e.status === 'misattributed') return `Said by ${e.found_in}, not ${e.participant}`
  if (e.status === 'not_found') return 'Not in the transcript'
  return null
}

function Quote({ e, k, sel, onSelect }: { e: Evidence; k: string; sel: Selection | null; onSelect: (e: Evidence, key: string) => void }) {
  const note = flag(e)
  const content = (
    <>
      <span className="by" aria-label={`Participant ${e.participant}`}>{e.participant}</span>
      <span className="text">
        <span className="q">“{e.quote}”</span>
        {note && <span className="flag">{note}</span>}
      </span>
    </>
  )
  return (
    <li className={`quote ${e.status} ${sel?.key === k ? 'active' : ''}`}>
      {e.start != null ? (
        <button onClick={() => onSelect(e, k)} aria-pressed={sel?.key === k}>{content}</button>
      ) : (
        <div>{content}</div>
      )}
    </li>
  )
}

const TOKEN_RE = /(\[EMAIL\]|\[PHONE\]|\bP\d+\b|\bInterviewer\b)/g

function Tokens({ text }: { text: string }) {
  return (
    <>
      {text.split(TOKEN_RE).map((p, i) =>
        i % 2 === 1 ? <span key={i} className={p.startsWith('[') ? 'redacted' : 'speaker'}>{p}</span> : p,
      )}
    </>
  )
}

function SourceViewer({ transcripts, tab, setTab, sel }: {
  transcripts: TranscriptOut[]; tab: string; setTab: (p: string) => void; sel: Selection | null
}) {
  const markRef = useRef<HTMLElement>(null)
  const t = transcripts.find((x) => x.pid === tab) ?? transcripts[0]
  const hl = sel && sel.pid === t.pid ? sel : null

  useEffect(() => {
    markRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [hl?.key, hl?.pid])

  const r = t.redactions
  const replaced = [
    r.names && plural(r.names, 'name'),
    r.emails && plural(r.emails, 'email'),
    r.phones && plural(r.phones, 'phone number'),
  ].filter(Boolean)

  return (
    <aside className="source" aria-labelledby="source-title">
      <h2 id="source-title">Check it against the transcripts</h2>
      <div className="tabs" role="tablist" aria-label="Transcripts">
        {transcripts.map((x) => (
          <button key={x.pid} role="tab" aria-selected={x.pid === t.pid} onClick={() => setTab(x.pid)} title={x.title}>
            {x.pid}
          </button>
        ))}
      </div>
      <p className="muted">
        {t.title}. {replaced.length ? `${replaced.join(', ')} replaced.` : 'Nothing needed replacing.'}
      </p>
      <pre className="transcript" tabIndex={0}>
        {hl ? (
          <>
            <Tokens text={t.text.slice(0, hl.start)} />
            <mark ref={markRef}><Tokens text={t.text.slice(hl.start, hl.end)} /></mark>
            <Tokens text={t.text.slice(hl.end)} />
          </>
        ) : (
          <Tokens text={t.text} />
        )}
      </pre>
    </aside>
  )
}
