/** Display anatomical angles at the person's own marks against the report's printed ranges. */
import {Assessment,Limb,Motion,angle,label} from "./assessmentData";

export function WalkComparison({pair,motion}:{pair:{rangeDifference:number;rms:number};motion:Motion}) {
  const gap = pair.rangeDifference;
  const joint = motion.name.split(" ")[0].toLowerCase();
  const where = joint==="pelvic" ? "pelvis" : joint;
  const amount = Math.abs(gap)>0 && Math.abs(gap)<0.005 ? "less than 0.01°" : angle(Math.abs(gap));
  return <div className="walk-comparison">
    <h3>How the two walks compare</h3>
    <p>{gap===0 ? "Both walks covered the same range for this movement." :
      <>The {where} moved through <strong>{amount} {gap<0?"less":"more"}</strong> in the right walk than in the left.</>}</p>
    <p>The size of the gap between the two curves across the cycle was <strong>{angle(pair.rms)}</strong>. Two walks can cover a similar range and still reach different angles along the way.</p>
    <details><summary>How the curve gap is measured</summary><p>We compare the angles at 101 matching points, from the beginning to the end of each walk. Larger gaps count more in this measure, called RMS. A single number cannot tell us why the walks differed.</p></details>
  </div>;
}

export function PhaseComparison({assessment,sides,motion}:{assessment:Assessment;sides:Limb[];motion:Motion}) {
  const rows=assessment.walks[sides[0]].phaseReadings[motion.key];
  return <section className="phase-review"><h3>Angles at the eight marked points</h3>
    <p>At each point marked during the walk, compare the recorded angle with the range printed for that movement in the BeyondGait report.</p>
    {sides.map(s=>{
      const readings=assessment.walks[s].phaseReadings[motion.key];
      const available=readings.filter(v=>v.gap!==null);
      if(!available.length) return <p key={s}>{label(s)} · No marked angles available.</p>;
      const largest=available.reduce((a,b)=>a.gap!>=b.gap!?a:b);
      return <p key={s}><strong>{label(s)} walk.</strong> {largest.gap===0
        ? `All ${available.length} available readings were within their phase ranges.`
        : `The largest gap was at ${largest.phase}. The angle was ${largest.reading}, ${largest.position.toLowerCase()} the printed range (${largest.range}).`}</p>;
    })}
    <details><summary>Compare phase angles</summary><div className="phase-table-wrap"><table>
      <caption>{motion.name} · reference ranges from page {rows[0].page}</caption>
      <thead><tr><th scope="col">Marked phase</th><th scope="col">Reference range</th>{sides.map(s=><th key={s} scope="col">{label(s)} walk</th>)}</tr></thead>
      <tbody>{rows.map((r,i)=><tr key={r.phase}><th scope="row">{r.phase}</th><td>{r.range}</td>{sides.map(s=>{
        const v=assessment.walks[s].phaseReadings[motion.key][i];
        return <td key={s}><strong>{v.reading}</strong><small>At {v.pct}% · {v.position}</small></td>;
      })}</tr>)}</tbody></table></div>
      <p>“Outside” gives the distance to the nearest end of the printed range. Each comparison uses the angle at that one mark. A difference alone does not identify a walking disorder.</p>
    </details></section>;
}
