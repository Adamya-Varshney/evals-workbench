import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Notice, PageHeader, usePid, useProject, useStatus } from "../components/ui";

const CONTENTS: [string, string][] = [
  ["EVAL_SPEC.md", "What each evaluator measures, the failure and frequency that motivated it, how it was validated (TPR, TNR, sample sizes, date), its owner and where it should run."],
  ["failure_taxonomy.json", "Failure modes with definitions, counts as / does not count as, counts, severity and decisions."],
  ["error_analysis.csv", "Every reviewed trace with your note, verdict and failure modes, plus the count table."],
  ["judges/<slug>.md", "Prompt, model, version, context scope and validation metrics. Judges that aren't validated carry a DRAFT banner."],
  ["checks/code_checks.py", "Code checks as pytest assertions (EVAL_TRACES=outputs.jsonl pytest checks/)."],
  ["datasets/<slug>_{train,dev,test}.jsonl", "Your labelled ground truth per judge, by split."],
  ["golden_regression.jsonl", "Traces that capture important workflows and past failures."],
  ["run_evals.py + suite.json + evals_lib.py", "A small, self-contained runner for the whole suite against any JSONL of traces."],
];

export function Export() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const status = useStatus(pid);
  const [downloaded, setDownloaded] = useState(false);
  const stage = status.data?.stages.find((s) => s.key === "export");
  const last = project.data?.settings.last_export_at;
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <PageHeader title="Export and operate" sub="Everything exports to open formats: Markdown, JSON, CSV and JSONL. No proprietary query language." />
      {stage?.status === "locked" && <div className="mb-4"><Notice tone="warn">{stage.unlock} You can still export now; the spec will show what is missing.</Notice></div>}
      <div className="card flex items-center gap-4 p-4">
        <div className="min-w-0 flex-1">
          <div className="h2">Eval bundle (.zip)</div>
          <div className="text-xs text-mist-400">{last ? `Last exported ${new Date(last).toLocaleString()}` : "Not exported yet."}</div>
        </div>
        <a
          className="btn-primary"
          href={`/api/projects/${pid}/export`}
          onClick={() => {
            setDownloaded(true);
            setTimeout(() => {
              qc.invalidateQueries({ queryKey: ["project", pid] });
              qc.invalidateQueries({ queryKey: ["status", pid] });
            }, 1500);
          }}
        >
          ⬇ Download bundle
        </a>
      </div>
      {downloaded && <div className="mt-2"><Notice tone="ok">Downloading. Unzip it, then run <code className="font-mono">python run_evals.py</code> inside the folder.</Notice></div>}

      <div className="mt-6 overflow-hidden rounded-lg border border-ink-700">
        <table className="tbl">
          <thead><tr><th className="w-72">File</th><th>What it contains</th></tr></thead>
          <tbody>{CONTENTS.map(([f, d]) => <tr key={f}><td className="font-mono text-xs text-mist-100">{f}</td><td className="text-mist-300">{d}</td></tr>)}</tbody>
        </table>
      </div>

      <div className="mt-6">
        <div className="h2 mb-2">Run it</div>
        <pre className="rounded-md border border-ink-700 bg-ink-900 p-3 font-mono text-[12.5px] text-mist-100">{`python run_evals.py                          # golden set, code checks
python run_evals.py outputs.jsonl --judges   # + LLM judges (needs ANTHROPIC_API_KEY, pip install anthropic)
EVAL_TRACES=outputs.jsonl pytest checks/     # code checks as CI assertions`}</pre>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4">
        <Guide title="In CI" items={["Run code checks and the golden set on every change.", "Use LLM judges sparingly there because of cost.", "Fast, objective code checks may also run inline as guardrails. Judges are for measurement after the fact."]} />
        <Guide title="In production" items={["Sample live traces regularly and run judges asynchronously.", "Investigate when the confidence interval for a failure rate crosses the agreed threshold.", "Add any new failure found in production to the golden set."]} />
        <Guide title="Keep looking at data" items={["Re-run error analysis on 100+ fresh traces after significant changes (new features, prompt or model changes).", "Review 10–20 traces weekly in between."]} />
        <Guide title="Maintain the suite" items={["Re-check judges against fresh human labels periodically.", "Retire evaluators that always pass."]} />
      </div>
    </div>
  );
}

function Guide({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="panel p-4">
      <div className="mb-2 font-semibold text-mist-50">{title}</div>
      <ul className="list-disc space-y-1 pl-4 text-[13px] text-mist-300">{items.map((x) => <li key={x}>{x}</li>)}</ul>
    </div>
  );
}
