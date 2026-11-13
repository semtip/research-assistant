// Mirrors backend/models.py (the API contract).

export type InsightKind = 'pain_point' | 'positive' | 'need'
export type QuoteStatus = 'verified' | 'near' | 'misattributed' | 'not_found'

export interface Evidence {
  participant: string
  quote: string
  status: QuoteStatus
  found_in: string | null
  start: number | null
  end: number | null
  score: number
}

export interface Insight {
  title: string
  kind: InsightKind
  summary: string
  status: 'verified' | 'near' | 'dropped'
  participants: string[]
  evidence: Evidence[]
  counter_evidence: Evidence[]
}

export interface TranscriptOut {
  pid: string
  title: string
  text: string
  redactions: Record<string, number>
}

export interface Stats {
  quotes_total: number
  quotes_verified: number
  quotes_near: number
  quotes_rejected: number
  insights_kept: number
  insights_dropped: number
  retried: boolean
  retry_feedback: string[]
  model: string
  seconds: number
}

export interface AnalyzeResponse {
  transcripts: TranscriptOut[]
  insights: Insight[]
  stats: Stats
}

export interface TranscriptDraft {
  id: string
  title: string
  text: string
}

// Events from POST /api/analyze/stream (newline-delimited JSON).
export type ProgressEvent =
  | { type: 'step'; step: 'privacy'; status: 'done'; transcripts: number; names: number; emails: number; phones: number }
  | { type: 'step'; step: 'read'; status: 'active'; model: string }
  | { type: 'step'; step: 'read'; status: 'done'; insights: number }
  | { type: 'step'; step: 'verify'; status: 'active'; quotes: number }
  | { type: 'step'; step: 'verify'; status: 'done'; verified: number; quotes: number }
  | { type: 'model_busy'; model: string; next: string | null }
  | { type: 'retry'; problems: number; quotes: number }
  | { type: 'result'; data: AnalyzeResponse }
  | { type: 'error'; status: number; message: string }
