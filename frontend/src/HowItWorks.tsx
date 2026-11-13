export const REPO_URL = 'https://github.com/semtip/research-assistant'

const STACK: [string, string][] = [
  ['React + TypeScript', 'the interface, with live progress and quotes highlighted in the transcript'],
  ['FastAPI (Python)', 'receives the interviews, runs each step and streams progress back'],
  ['Pydantic', "defines the exact shape of the AI's answer and rejects anything that doesn't fit"],
  ['PydanticAI + Gemini', "sends the interviews to the AI and asks it to fix quotes that don't match"],
  ['pytest + evaluation', '14 tests, and 7 of 7 planted pain points found in each of 3 runs'],
  ['Docker + Vercel', 'packaging, and hosting at semtip.nl/koos'],
]

export function HowItWorks() {
  return (
    <details className="how">
      <summary>How it works and how I built it</summary>
      <div className="how-body">
        <p>
          I built this in a day with Claude Code, to learn a production-style AI stack by building something real. I chose
          the problem, set the requirements and designed the interface. The AI's answers are treated as untrusted: every
          quote is checked word for word against the transcript.
        </p>
        <ul>
          {STACK.map(([name, role]) => (
            <li key={name}>
              <strong>{name}:</strong> {role}
            </li>
          ))}
        </ul>
        <a className="repo" href={REPO_URL} target="_blank" rel="noreferrer">
          View the code on GitHub
        </a>
      </div>
    </details>
  )
}
