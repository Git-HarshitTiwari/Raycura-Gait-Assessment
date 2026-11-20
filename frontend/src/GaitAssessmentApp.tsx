/** Named patient directory, bilateral motion review and standalone assessment reports. */
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Assessment,
  Band,
  Directory,
  Limb,
  Motion,
  Person,
  ViewSide,
  angle,
  formatDate,
  label,
  referenceLabel,
  useResult,
} from "./assessmentData";
import { AssessmentEvidence } from "./AssessmentEvidence";
import { PhaseComparison, WalkComparison } from "./PhaseComparison";
import { MotionGraph } from "./MotionGraph";
import "./assessment.css";

function GaitAssessmentApp() {
  const directory = useResult<Directory>("/api/directory");
  const [selected, setSelected] = useState(""),
    [search, setSearch] = useState(""),
    [picker, setPicker] = useState(false);
  const people = directory.data?.people || [],
    key = selected || people[0]?.key,
    person = people.find((p) => p.key === key);
  const filtered = people.filter((p) =>
    p.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );
  function choose(p: Person) {
    setSelected(p.key);
    setPicker(false);
  }
  return (
    <div className="workspace">
      <header className="mast">
        <div className="brand">
          <img src="/better-logo.png" alt="Better." />
          <span></span>
          <strong>Gait assessment</strong>
        </div>
        <span className="workspace-type">Research workspace</span>
      </header>
      <div className="shell">
        <aside className={"directory " + (picker ? "expanded" : "")}>
          <div className="directory-heading">
            <h2>Patients</h2>
            <span>{people.length || "–"}</span>
          </div>
          <button
            className="mobile-picker"
            onClick={() => setPicker(!picker)}
            aria-expanded={picker}
          >
            {picker ? "Close patient list" : "Choose patient"}
          </button>
          <div className="directory-content">
            <label className="search">
              <span aria-hidden="true">⌕</span>
              <input
                aria-label="Search patients by name"
                placeholder="Search by name"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <div className="patient-list" aria-label="Patients">
              {filtered.map((p) => (
                <button
                  key={p.key}
                  onClick={() => choose(p)}
                  className={key === p.key ? "patient active" : "patient"}
                  aria-pressed={key === p.key}
                >
                  <span className="avatar" aria-hidden="true">
                    {p.name
                      .trim()
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((n) => n[0])
                      .join("")
                      .toUpperCase()}
                  </span>
                  <span className="patient-detail">
                    <strong>{p.name}</strong>
                    <small>{formatDate(p.date)}</small>
                  </span>
                </button>
              ))}
              {search && !filtered.length && (
                <p className="empty">No matching names.</p>
              )}
            </div>
          </div>
        </aside>
        <main>
          {directory.error ? (
            <p role="alert">{directory.error}</p>
          ) : person && directory.data ? (
            <Review
              key={person.key}
              person={person}
              directory={directory.data}
            />
          ) : (
            <p role="status">Opening saved assessments…</p>
          )}
        </main>
      </div>
    </div>
  );
}

function Review({
  person,
  directory,
}: {
  person: Person;
  directory: Directory;
}) {
  const result = useResult<Assessment>("/api/participants/" + person.key);
  const [side, setSide] = useState<ViewSide>("both"),
    [motion, setMotion] = useState("hip_flexion"),
    [tab, setTab] = useState("curves");
  const [marks, setMarks] = useState(true),
    [reference, setReference] = useState(true),
    [band, setBand] = useState<Band>("off"),
    [windowId, setWindow] = useState("");
  const [evidenceSide, setEvidenceSide] = useState<Limb>("left");
  const sides: Limb[] = side === "both" ? ["left", "right"] : [side],
    m = directory.motions.find((x) => x.key === motion)!;
  const ass = result.data;
  function chooseSide(s: ViewSide) {
    setSide(s);
    if (s !== "both") {
      setEvidenceSide(s);
      if (band !== "off" && band !== s) setBand("off");
    }
  }
  const params = new URLSearchParams({
    side,
    marks: String(marks),
    reference: String(reference),
    band,
    window: windowId,
    motion,
  });
  const reportParams = new URLSearchParams(params);
  if (tab === "evidence") {
    reportParams.set("side", evidenceSide);
    if (band !== evidenceSide) reportParams.set("band", "off");
  }
  const base = "/api/participants/" + person.key;
  const times = ass
    ? (tab === "evidence" ? [evidenceSide] : sides).map(
        (s) =>
          label(s) +
          " · " +
          formatDate(ass.walks[s].time) +
          " · " +
          ass.walks[s].time.slice(11, 16),
      )
    : [];
  return (
    <>
      <div className="overview-head">
        <div>
          <span className="eyebrow">Patient assessment</span>
          <h1>{person.name}</h1>
          <div className="capture-times">
            {times.map((t) => (
              <span key={t}>{t}</span>
            ))}
          </div>
        </div>
        {ass && (
          <div className="report-downloads">
            <a className="export" href={base + "/report.pdf?" + reportParams} download>
              <span aria-hidden="true">↓</span> Download PDF
            </a>
            <a href={base + "/report?" + reportParams} download>Interactive HTML</a>
          </div>
        )}
      </div>
      <nav aria-label="Assessment views" className="section-tabs">
        <button
          onClick={() => setTab("curves")}
          aria-pressed={tab === "curves"}
        >
          Motion analysis
        </button>
        <button
          onClick={() => setTab("evidence")}
          aria-pressed={tab === "evidence"}
        >
          Evidence & assistant
        </button>
      </nav>
      {result.error ? (
        <p role="alert">{result.error}</p>
      ) : !ass ? (
        <p role="status">Loading walks…</p>
      ) : tab === "evidence" ? (
        <>
          <div className="evidence-limb">
            <span>Explain one walk</span>
            <SideSelect
              side={evidenceSide}
              choices={["left", "right"]}
              change={(s) => setEvidenceSide(s as Limb)}
            />
          </div>
          <AssessmentEvidence
            key={ass.key + evidenceSide + motion}
            motion={motion}
            motions={directory.motions}
            changeMotion={(value) => {setMotion(value); setWindow("");}}
            assessment={ass}
            side={evidenceSide}
            sources={directory.sources}
          />
        </>
      ) : (
        <>
          <section className="panel plot-panel">
            <div className="chart-head">
              <div>
                <span className="eyebrow">Motion graph</span>
                <h2>{m.name}</h2>
              </div>
              <SideSelect
                side={side}
                choices={["left", "right", "both"]}
                change={chooseSide}
              />
            </div>
            <div className="chart-fields">
              <label>
                Motion
                <select
                  aria-label="Select motion"
                  value={motion}
                  onChange={(e) => {
                    setMotion(e.target.value);
                    setWindow("");
                  }}
                >
                  {directory.motions.map((x) => (
                    <option key={x.key} value={x.key}>
                      {x.name}
                    </option>
                  ))}
                </select>
              </label>
              <span className="direction">
                + {m.positive} <b>/</b> − {m.negative}
              </span>
            </div>
            <p className="graph-guide"><strong>How to read this graph.</strong> {m.cycleGuide} {m.guide}</p>
            <MotionGraph
              url={base + "/graph/" + motion + "?" + params}
              name={m.name}
            />
            {marks && <p className="chart-note"><strong>Read the first mark.</strong>{" "}
              {sides.map(s => {
                const first = ass.walks[s].phaseReadings[motion][0];
                return <span key={s}>{label(s)} at {first.pct}% ({first.phase}) · {first.reading}. </span>;
              })}
              Tap or hover over a marker for its phase name. The table below compares each marked angle with its reference range.
            </p>}
            <div className="overlay-controls">
              <label>
                <input
                  type="checkbox"
                  checked={marks}
                  onChange={(e) => setMarks(e.target.checked)}
                />{" "}
                Manual phase marks
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={reference}
                  onChange={(e) => setReference(e.target.checked)}
                />{" "}
                Reference curve
              </label>
              <label>
                Healthy-group spread
                <select
                  aria-label="Healthy-group spread"
                  value={band}
                  onChange={(e) => setBand(e.target.value as Band)}
                >
                  <option value="off">Off</option>
                  {sides.map((s) => (
                    <option value={s} key={s}>
                      {label(s)} walk
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="chart-note">
              {side === "both"
                ? "Left and right were recorded in separate walks. Each runs from 0% to 100% of its own cycle."
                : ""}{" "}
              {reference && "The dotted reference line is an average for comparison. A gap from it alone cannot tell you whether anything is wrong. "}
              {band !== "off" &&
                "Shading shows the middle 90% of angles in the comparison group for the chosen side, at each point in the cycle."}
              {side === "both" && !ass.comparison[motion] && (
                <strong> {ass.walks.left.time.slice(0, 10) !== ass.walks.right.time.slice(0, 10)
                  ? "These walks were recorded on different dates. Same-day comparison statistics are unavailable."
                  : "A paired numerical comparison is unavailable for this motion."}</strong>
              )}
            </p>
            {marks && (
              <details className="phase-details">
                <summary>Recorded phase names and positions</summary>
                {sides.map((s) => (
                  <div key={s}>
                    <h4>{label(s)} walk</h4>
                    <p>
                      {ass.walks[s].marks
                        .map((p) => p.name + " " + p.pct + "%")
                        .join(" · ")}
                    </p>
                  </div>
                ))}
                <p>
                  The person reviewing the walk marked these points on the video. Their positions are approximate.
                </p>
              </details>
            )}
          </section>
          <Measurements assessment={ass} sides={sides} motion={m} />
          <section className="panel findings">
            <div className="section-line">
              <h2>What this graph shows</h2>
            </div>
            {side === "both" && ass.comparison[motion] && <WalkComparison pair={ass.comparison[motion]} motion={m} />}
            {sides.flatMap((s) =>
              ass.walks[s].observations
                .filter((c) => c.channels.includes(motion))
                .map((c) => (
                  <article className="observation" key={s + c.id}>
                    <span className="walk-label">{label(s)} walk</span>
                    <h3>{c.title}</h3>
                    <p>{c.observation}</p>
                    <details>
                      <summary>Why it deserves a closer look</summary>
                      <p>{c.interpretation}</p>
                      <p>{c.next_check}</p>
                      {c.source_ids.map((id) => {
                        const src = directory.sources.find((d) => d.id === id);
                        return src ? (
                          <a
                            key={id}
                            href={src.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {src.title}{" "}
                          </a>
                        ) : null;
                      })}
                    </details>
                  </article>
                )),
            )}
            <PhaseComparison assessment={ass} sides={sides} motion={m} />
            <Checks
              assessment={ass}
              sides={sides}
              motion={motion}
              windowId={windowId}
              setWindow={setWindow}
            />
          </section>
        </>
      )}
    </>
  );
}

function SideSelect({
  side,
  choices,
  change,
}: {
  side: ViewSide;
  choices: ViewSide[];
  change: (s: ViewSide) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label="Walk selection">
      {choices.map((s) => (
        <button key={s} aria-pressed={s === side} onClick={() => change(s)}>
          {label(s)}
        </button>
      ))}
    </div>
  );
}
function Measurements({
  assessment,
  sides,
  motion,
}: {
  assessment: Assessment;
  sides: Limb[];
  motion: Motion;
}) {
  const metrics = [
    ["rom_deg", "Range of motion", "How far the angle moved between its two extremes."],
    [
      "rms_difference_deg",
      "Overall curve difference",
      "Each walk compared with its reference across the cycle. A larger number means the angles differed more overall.",
    ],
    [
      "mean_offset_deg",
      "Average angular shift",
      "Average distance above (+) or below (−) the reference curve. High and low points can cancel out.",
    ],
  ] as const;
  return (
    <section className="metric-strip" aria-label="Recorded measurements">
      {metrics.map(([k, name, help]) => (
        <div key={k}>
          <h3>{name}</h3>
          <div className="metrics-values">
            {sides.map((s) => (
              <span key={s}>
                <small>{label(s)}</small>
                <strong>
                  {angle(
                    assessment.walks[s].motions[motion.key][k],
                    k === "mean_offset_deg",
                  )}
                </strong>
              </span>
            ))}
          </div>
          <p>{help}</p>
        </div>
      ))}
    </section>
  );
}
function Checks({
  assessment,
  sides,
  motion,
  windowId,
  setWindow,
}: {
  assessment: Assessment;
  sides: Limb[];
  motion: string;
  windowId: string;
  setWindow: (id: string) => void;
}) {
  const rules = assessment.walks[sides[0]].rules.filter((r) =>
    r.channels.includes(motion),
  );
  return (
    <>
      {!rules.length && (
        <p>
          This motion has no dedicated pattern check. Its curve and measurements
          are available above.
        </p>
      )}
      {rules.map((rule) => (
        <article className="check" key={rule.id}>
          <h3>{rule.title}</h3>
          {sides.map((s) => {
            const r = assessment.walks[s].rules.find((x) => x.id === rule.id)!;
            return (
              <div className="check-row" key={s}>
                <span className="walk-label">{label(s)}</span>
                <strong className={r.status === "matched" ? "seen" : ""}>
                  {r.status === "matched"
                    ? "Pattern seen"
                    : r.status === "not_matched"
                      ? "Pattern not seen"
                      : "Couldn’t check"}
                </strong>
                <span>{r.reading}</span>
              </div>
            );
          })}
          <details className="rule-how"><summary>How this pattern is checked</summary><p>{rule.guide}</p><p>The cutoffs come from the myogait movement check. One angle can fall outside its printed range even when this pattern is absent.</p></details>
          <div className="check-links">
            <button
              aria-pressed={windowId === rule.id}
              onClick={() => setWindow(windowId === rule.id ? "" : rule.id)}
            >
              {windowId === rule.id ? "Hide" : "Highlight"}{" "}
              {rule.windows[motion].join("–")}% on graph
            </button>
            <a href={rule.source} rel="noreferrer" target="_blank">
              Rule source
            </a>
          </div>
        </article>
      ))}
      <details>
        <summary>What is the reference curve?</summary>
        <p>The dotted line shows an average angle at each point of the walk. The gap from this line tells you how the recorded movement differs from that average.</p>
        {sides.map(s => <p key={s}><b>{label(s)}.</b> {referenceLabel(assessment.walks[s].motions[motion])}.
          {assessment.walks[s].motions[motion].measurement_status !== "usable" && " Some measurements were unavailable for this walk."}</p>)}
      </details>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<GaitAssessmentApp />);
