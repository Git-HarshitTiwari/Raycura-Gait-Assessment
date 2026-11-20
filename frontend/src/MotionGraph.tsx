/** Render the exact same local Plotly specification that is used in HTML exports. */
import { useEffect, useRef, useState } from "react";
import { Figure, useResult } from "./assessmentData";
declare global {
  interface Window {
    Plotly?: {
      newPlot: (
        div: HTMLElement,
        data: unknown[],
        layout: object,
        config: object,
      ) => Promise<unknown>;
      purge: (div: HTMLElement) => void;
      Plots: { resize: (div: HTMLElement) => void };
    };
  }
}
export function MotionGraph({ url, name }: { url: string; name: string }) {
  const result = useResult<Figure>(url);
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const el = host.current,
      plot = window.Plotly;
    if (!el || !result.data || !plot) return;
    let active = true,
      painted = false;
    const box = document.createElement("div");
    box.className = "plot-inner";
    el.replaceChildren(box);
    setFailed(false);
    const observer = new ResizeObserver(() => {
      if (active && painted) plot.Plots.resize(box);
    });
    plot
      .newPlot(box, result.data.data, result.data.layout, {
        responsive: true,
        displaylogo: false,
        displayModeBar: false,
        scrollZoom: false,
      })
      .then(() => {
        if (active) {
          painted = true;
          observer.observe(el);
        } else plot.purge(box);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      observer.disconnect();
      if (painted) plot.purge(box);
      box.remove();
    };
  }, [result.data]);
  return (
    <div className="graph-area" aria-label={name + " angle by gait cycle"}>
      <div ref={host} />
      {result.error || !window.Plotly || failed ? (
        <p role="alert" className="plot-message">
          {result.error ||
            "The local graph could not be displayed. The measurements are available below."}
        </p>
      ) : !result.data ? (
        <p role="status" className="plot-message">
          Loading curves…
        </p>
      ) : null}
    </div>
  );
}
