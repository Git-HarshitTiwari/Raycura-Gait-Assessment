/** Ask about one recording and show only the Stage 5 approved cards and sources. */
import { useEffect, useRef, useState } from "react";
import {
  Answer,
  Assessment,
  Limb,
  Motion,
  Source,
  getJSON,
  label,
} from "./assessmentData";

export function AssessmentEvidence({
  assessment,
  side,
  sources, motion, motions, changeMotion,
}: {
  assessment: Assessment;
  side: Limb;
  sources: Source[];
  motion: string;
  motions: Motion[];
  changeMotion: (key:string)=>void;
}) {
  const [question, setQuestion] = useState(
    "What recorded differences deserve review?",
  );
  const [answer, setAnswer] = useState<Answer>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null),
    walk = assessment.walks[side];
  useEffect(() => () => request.current?.abort(), []);
  function clear() {
    request.current?.abort();
    request.current = null;
    setAnswer(undefined);
    setBusy(false);
    setError("");
  }
  async function ask(e: React.FormEvent) {
    e.preventDefault();
    clear();
    if (!question.trim()) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    try {
      const result = await getJSON<Answer>(
        "/api/recordings/" + walk.id + "/explanation",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: question.trim(), motion }),
          signal: controller.signal,
        },
      );
      if (result.record_id !== walk.id || result.side !== side)
        throw new Error("The explanation belongs to another recording.");
      if (!controller.signal.aborted) setAnswer(result);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      <section className="panel evidence-panel">
        <div className="section-line">
          <h2>Understand this walk</h2>
          <span className="walk-label">{label(side)} walk</span>
        </div>
        <p>
          Ask what a number means, how the two walks compare, or why a pattern was seen. Answers use this person's saved measurements.
        </p>
        <label className="question-motion">Movement <select value={motion} onChange={e=>changeMotion(e.target.value)}>
          {motions.map(m=><option key={m.key} value={m.key}>{m.name}</option>)}</select></label>
        <div className="question-examples" aria-label="Example questions">{["What does range of motion mean?", "What does offset mean?", "What does curve difference mean?", "Which pattern was seen?"].map(q=><button type="button" key={q} onClick={()=>{clear();setQuestion(q);}}>{q}</button>)}</div>
        <form onSubmit={ask}>
          <label htmlFor="question">Your question</label>
          <textarea
            id="question"
            maxLength={1000}
            value={question}
            onChange={(e) => {
              clear();
              setQuestion(e.target.value);
            }}
          />
          <button className="primary" disabled={busy || !question.trim()}>
            {busy ? "Preparing explanation…" : "Explain this walk"}
          </button>
        </form>
        {error && <p role="alert">{error}</p>}
        {answer && (
          <section aria-live="polite" className="response">
            <h3>
              {answer.mode === "deterministic_fallback"
                ? "Saved explanation · local assistant unavailable"
                : answer.mode === "scope_help" ? "About your question" : answer.mode === "saved_explanation" ? "From this assessment" : "Local assistant explanation"}
            </h3>
            {answer.cards.map((c) => (
              <div key={c.id}>
                <h4>{c.title}</h4>
                <p>{c.text}</p>
              </div>
            ))}
            <SourceList sources={answer.sources} />
          </section>
        )}
      </section>
      <section className="panel evidence-panel">
        <h2>Muscle-function evidence</h2>
        <p>
          {walk.muscleCount === 0
            ? "This walk has no supported muscle-specific finding. The curves record movement angles. They do not measure muscle activity."
            : "See the supported examination suggestions in the saved report."}
        </p>
        <details>
          <summary>Browse evidence sources</summary>
          <SourceList sources={sources} />
        </details>
      </section>
    </>
  );
}
function SourceList({ sources }: { sources: Source[] }) {
  return (
    <ul className="sources">
      {sources.map((s) => (
        <li key={s.id}>
          <a href={s.url} target="_blank" rel="noreferrer">
            {s.id === "MYOGAIT_RULES" ? "How the movement checks are defined" : s.title}
          </a>
          <small>{s.id === "MYOGAIT_RULES" ? "Software method · myogait" : s.id === "ISB2024" ? "Professional guidance" : "Research paper"}</small>
        </li>
      ))}
    </ul>
  );
}
