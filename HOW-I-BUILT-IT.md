# How I built this

The Research Assistant turns user-interview transcripts into insights (pain points, needs and what works), each backed by quotes you can check in the transcript.

I built this in a day with Claude Code, to learn a production-style AI stack by building something real. I chose the problem, set the requirements and designed the interface. The AI's answers are treated as untrusted: every quote is checked word for word against the transcript.

- **React + TypeScript:** the interface, with live progress and quotes highlighted in the transcript
- **FastAPI (Python):** receives the interviews, runs each step and streams progress back
- **Pydantic:** defines the exact shape of the AI's answer and rejects anything that doesn't fit
- **PydanticAI + Gemini:** sends the interviews to the AI and asks it to fix quotes that don't match
- **pytest + evaluation:** 14 tests, and 7 of 7 planted pain points found in each of 3 runs
- **Docker + Vercel:** packaging, and hosting at semtip.nl/koos

Details and limits are in the [README](README.md).
