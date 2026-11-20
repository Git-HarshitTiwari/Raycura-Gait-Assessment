/** Types and record-bound fetching for the local saved-result API. */
import { useEffect, useState } from "react";

export type Limb = "left" | "right";
export type ViewSide = Limb | "both";
export type Band = Limb | "off";
export const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
export const angle = (v: number | null, signed = false) =>
  v === null
    ? "Unavailable"
    : (signed && v > 0 ? "+" : "") + v.toFixed(2).replace("-", "−") + "°";
export const formatDate = (v: string) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(v.slice(0, 10) + "T12:00:00"));
export type Source = {
  id: string;
  title: string;
  url: string;
  section: string;
};
export type Motion = {
  key: string;
  name: string;
  guide: string;
  cycleGuide: string;
  positive: string;
  negative: string;
};
export type Person = { key: string; name: string; date: string };
export type Directory = {
  people: Person[];
  motions: Motion[];
  sources: Source[];
};
export type Metric = {
  rom_deg: number | null;
  rms_difference_deg: number | null;
  mean_offset_deg: number | null;
  measurement_status: string;
  reference_status: string;
  reference_participants: number | null;
  quality_flags: string | null;
};
export type Rule = {
  id: string;
  question: string;
  title: string;
  guide: string;
  reading: string;
  status: string;
  channels: string[];
  windows: Record<string, [number, number]>;
  evidence: string[];
  source: string;
};
export type Observation = {
  id: string;
  title: string;
  observation: string;
  interpretation: string;
  next_check: string;
  channels: string[];
  source_ids: string[];
};
export type PhaseReading = {
  phase: string; pct: number; reading: string; range: string; position: string; gap: number | null; page: number;
};
export type Walk = {
  id: string;
  time: string;
  marks: { name: string; pct: number; frameTime: string }[];
  motions: Record<string, Metric>;
  rules: Rule[];
  observations: Observation[];
  phaseReadings: Record<string, PhaseReading[]>;
  muscleCount: number;
};
export type Assessment = {
  key: string;
  name: string;
  walks: Record<Limb, Walk>;
  comparison: Record<string, { rangeDifference: number; rms: number }>;
};
export type Answer = {
  record_id: string;
  side: Limb;
  mode: string;
  cards: { id: string; title: string; text: string }[];
  sources: Source[];
};
export type Figure = { data: unknown[]; layout: Record<string, unknown> };

export async function getJSON<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, { ...options, cache: "no-store" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "The local request failed (" + response.status + ").",
    );
  }
  return response.json();
}
export function useResult<T>(url: string) {
  const [result, setResult] = useState<{
    url: string;
    data?: T;
    error?: string;
  }>({ url: "" });
  useEffect(() => {
    const controller = new AbortController();
    getJSON<T>(url, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ url, data });
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setResult({ url, error: e.message });
      });
    return () => controller.abort();
  }, [url]);
  return result.url === url ? result : { url };
}
export function referenceLabel(m: Metric) {
  if (m.reference_status === "company_mean_numeric_comparison")
    return "Reference curve · average angle at each point in the cycle";
  if (
    m.reference_status === "exploratory_same_side_cohort_participant_excluded"
  )
    return "Average for this side from " + m.reference_participants + " other people";
  if (m.reference_status === "approved_exploratory_same_side_mean")
    return "Average for this side from " + m.reference_participants + " people";
  return "Reference unavailable";
}
