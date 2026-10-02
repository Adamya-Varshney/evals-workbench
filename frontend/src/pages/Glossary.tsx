import { PageHeader } from "../components/ui";

export const GLOSSARY: [string, string, string][] = [
  ["Trace", "trace", "The full record of one interaction: system prompt, user messages, tool calls and results, assistant replies, and metadata."],
  ["Review traces", "open coding", "Reading each trace and writing, in your own words, what went wrong. Each note is an open code."],
  ["Group failures", "axial coding", "Grouping your notes into a small set of specific, named failure modes with definitions."],
  ["Failure mode", "category / axial code", "One specific, observable way the product fails, e.g. 'Markdown sent over SMS'. Must pass the colleague test."],
  ["Colleague test", "", "Could a colleague label traces using only the failure mode's name and definition? If not, it isn't specific enough."],
  ["None of the above", "", "A bucket for notes no failure mode covers. Each one is a prompt to consider a new category."],
  ["Saturation", "theoretical saturation", "The point where reviewing more traces stops revealing new kinds of problem. Around 100 traces is typical, but it's a heuristic."],
  ["First failure", "first upstream failure", "In a multi-turn trace, the earliest turn where things went wrong. Later problems are often consequences of it."],
  ["Code check", "assertion", "A deterministic if/else on the trace. Cheapest and most reliable evaluator."],
  ["LLM judge", "LLM-as-judge", "A prompt that asks a model whether one specific failure is present. Needs validation against your labels."],
  ["Ground truth", "labels", "Your own judgement of whether a failure is present on a trace, with a critique. The judge is measured against it."],
  ["Train / dev / test split", "", "Train (10–20%) may appear in the judge prompt as examples; dev (40–45%) is for iterating; test (40–45%) is held out for final validation. A trace never changes split."],
  ["TPR", "true positive rate / recall", "Of the traces where you said the failure is present, the share the judge also flagged."],
  ["TNR", "true negative rate / specificity", "Of the traces where you said the failure is absent, the share the judge also passed."],
  ["Raw agreement", "accuracy (trap metric)", "Share of traces where judge and human agree. Misleading when failures are rare: an always-pass judge scores high."],
  ["Wilson interval", "95% confidence interval", "The plausible range for a rate given the sample size. Small samples give wide intervals."],
  ["Corrected failure rate", "prevalence correction", "The judge's raw failure rate adjusted for its own errors: (p_obs + TNR − 1) / (TPR + TNR − 1), with a bootstrap interval."],
  ["Pass-all rate", "", "Share of traces that pass every active evaluator."],
  ["Golden set", "regression set", "Traces capturing important workflows and past failures, re-run on every change."],
  ["Synthetic inputs", "", "Generated user messages built from dimensions (feature, scenario, persona) when real traces aren't available yet."],
  ["Transition failure matrix", "", "For agentic traces: last successful step (rows) against first failing step (columns), from first-failure marks."],
];

export function Glossary() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <PageHeader title="Glossary" sub="Plain-language labels used in the app, with the technical term you may see elsewhere." />
      <div className="overflow-hidden rounded-lg border border-ink-700">
        <table className="tbl">
          <thead><tr><th className="w-52">In this app</th><th className="w-48">Also called</th><th>Meaning</th></tr></thead>
          <tbody>
            {GLOSSARY.map(([a, b, c]) => (
              <tr key={a}><td className="font-medium text-mist-50">{a}</td><td className="text-mist-400">{b || "—"}</td><td className="text-mist-300">{c}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
