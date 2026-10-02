import { Term, pct } from "./ui";

export type Metrics = {
  confusion: { tp: number; fn: number; tn: number; fp: number };
  n: number;
  n_pos: number;
  n_neg: number;
  tpr: number | null;
  tpr_ci: [number | null, number | null];
  tnr: number | null;
  tnr_ci: [number | null, number | null];
  agreement: number | null;
  always_pass_agreement: number | null;
  low_confidence: boolean;
  errors?: number;
  passed?: boolean;
  threshold?: number;
  overfit_warning?: boolean;
  repeat_warning?: boolean;
  dev_gap?: number;
  run_number?: number;
  correct_fail?: number;
  correct_pass?: number;
};

export function ci(c?: [number | null, number | null]) {
  if (!c || c[0] === null || c[1] === null) return "";
  return `95% CI ${pct(c[0])}–${pct(c[1])}`;
}

export function LowConfidence() {
  return (
    <span className="chip border-warn-400/40 text-warn-400" title="Fewer than 30 examples of either class in this split. The interval is wide; label more traces.">
      ! low confidence
    </span>
  );
}

/** TPR and TNR are the headline; raw agreement is shown small, next to what an always-pass judge would score. */
export function MetricsPanel({ m, threshold, title, who = "judge" }: { m: Metrics; threshold?: number; title?: string; who?: string }) {
  const ok = (x: number | null) => (threshold === undefined || x === null ? "" : x >= threshold ? "text-pass-400" : "text-fail-400");
  return (
    <div className="grid grid-cols-[1fr_1fr_190px] gap-3">
      <div className="panel p-3">
        <div className="label"><Term tip="True positive rate: of the traces where you said the failure is present, how many were caught.">Catches real failures (TPR)</Term></div>
        <div className={`text-2xl font-semibold tabular-nums ${ok(m.tpr)}`}>{pct(m.tpr, 0)}</div>
        <div className="text-xs text-mist-400">{m.confusion.tp} of {m.n_pos} failures · {ci(m.tpr_ci)}</div>
      </div>
      <div className="panel p-3">
        <div className="label"><Term tip="True negative rate: of the traces where you said the failure is absent, how many were correctly passed.">Passes good traces (TNR)</Term></div>
        <div className={`text-2xl font-semibold tabular-nums ${ok(m.tnr)}`}>{pct(m.tnr, 0)}</div>
        <div className="text-xs text-mist-400">{m.confusion.tn} of {m.n_neg} non-failures · {ci(m.tnr_ci)}</div>
      </div>
      <div className="panel p-3">
        <div className="label">Confusion matrix{title ? ` · ${title}` : ""}</div>
        <table className="w-full text-center text-xs tabular-nums">
          <thead>
            <tr className="text-mist-500"><td /><td>{who}: fail</td><td>{who}: pass</td></tr>
          </thead>
          <tbody>
            <tr><td className="text-left text-mist-500">you: fail</td><td className="font-semibold text-pass-400">{m.confusion.tp}</td><td className="font-semibold text-fail-400">{m.confusion.fn}</td></tr>
            <tr><td className="text-left text-mist-500">you: pass</td><td className="font-semibold text-fail-400">{m.confusion.fp}</td><td className="font-semibold text-pass-400">{m.confusion.tn}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="col-span-3 flex flex-wrap items-center gap-3 text-xs text-mist-400">
        <span>
          <Term tip="Trap metric. If the failure occurs 10% of the time, a judge that always says 'pass' scores 90% agreement while catching nothing. Use TPR and TNR.">Raw agreement</Term>{" "}
          {pct(m.agreement)} <span className="text-mist-500">(an always-pass judge would score {pct(m.always_pass_agreement)})</span>
        </span>
        <span>n = {m.n} ({m.n_pos} with the failure, {m.n_neg} without)</span>
        {m.low_confidence && <LowConfidence />}
        {!!m.errors && <span className="text-fail-400">{m.errors} call(s) errored</span>}
      </div>
    </div>
  );
}
