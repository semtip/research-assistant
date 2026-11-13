import type { AnalyzeResponse, TranscriptDraft } from './types'
import sanne from '../../data/interview-1-sanne.txt?raw'
import daan from '../../data/interview-2-daan.txt?raw'
import yara from '../../data/interview-3-yara.txt?raw'
import exampleResultJson from './example-result.json'

export const exampleTranscripts: Omit<TranscriptDraft, 'id'>[] = [
  { title: 'Interview 1, daily commuter', text: sanne },
  { title: 'Interview 2, groceries and family', text: daan },
  { title: 'Interview 3, student', text: yara },
]

// A real, unedited response from the API for the example interviews.
// Lets anyone see the result without spending AI quota. Regenerate with: python -m eval.run_eval --save
export const exampleResult = exampleResultJson as unknown as AnalyzeResponse | null
