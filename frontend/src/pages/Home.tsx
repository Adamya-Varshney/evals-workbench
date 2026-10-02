import { Link } from "react-router-dom";
import { STAGE_ROUTES } from "../components/Layout";
import { Page, Stat, StatusIcon, Term, usePid, useProject, useStatus } from "../components/ui";

export function Home() {
  const pid = usePid();
  const project = useProject(pid);
  const status = useStatus(pid);
  const st = status.data;
  if (!st) return null;
  const next = st.next;
  const nextIdx = next ? st.stages.findIndex((x) => x.key === next.key) : -1;
  return (
    <Page>
      <div className="mb-5 flex items-end justify-between">
        <div>
          <div className="text-xs text-mist-400">{project.data?.reviewer_name ? `Reviewer: ${project.data.reviewer_name}` : "No reviewer set"}</div>
          <h1 className="h1">{project.data?.name}</h1>
        </div>
      </div>

      {next ? (
        <div className="card flex items-center gap-5 p-4">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent-400/10 text-[15px] font-semibold text-accent-400">{nextIdx + 1}</div>
          <div className="min-w-0 flex-1">
            <div className="label mb-0 text-accent-400">Next best action</div>
            <div className="text-[15px] font-semibold text-mist-50">{next.term ? <Term tip={next.term}>{next.title}</Term> : next.title}</div>
            <div className="text-mist-300">{next.next}</div>
          </div>
          <Link to={`/p/${pid}/${STAGE_ROUTES[next.key]}`} className="btn-primary">Go to step {nextIdx + 1} →</Link>
        </div>
      ) : (
        <div className="card p-4">
          <div className="h2">Everything is up to date.</div>
          <p className="mt-1 text-mist-400">Review 10–20 fresh traces each week, and re-run error analysis after big changes.</p>
        </div>
      )}

      <div className="mt-4 grid grid-cols-4 gap-3">
        <Stat label="Traces" value={st.counts.traces} sub={`${st.counts.batches} batch${st.counts.batches === 1 ? "" : "es"}`} />
        <Stat label="Reviewed" value={st.counts.reviewed} sub={`${st.counts.failed} failing`} />
        <Stat label="Failure modes" value={st.counts.failure_modes} />
        <Stat label="Evaluators" value={st.counts.evaluators} sub={`${st.counts.ground_truth} ground-truth labels`} />
      </div>

      <div className="mt-6 overflow-hidden rounded-lg border border-ink-700">
        <table className="tbl">
          <thead>
            <tr><th className="w-10">#</th><th className="w-64">Stage</th><th className="w-32">Status</th><th>What to do next</th></tr>
          </thead>
          <tbody>
            {st.stages.map((s, i) => (
              <tr key={s.key}>
                <td className="text-mist-500">{i + 1}</td>
                <td>
                  <Link to={`/p/${pid}/${STAGE_ROUTES[s.key]}`} className={`font-medium hover:underline ${s.status === "locked" ? "text-mist-400" : "text-mist-50"}`}>{s.title}</Link>
                  {s.term && <div className="text-xxs text-mist-500">{s.term}</div>}
                </td>
                <td><span className="inline-flex items-center gap-1.5 text-xs text-mist-300"><StatusIcon status={s.status} n={i + 1} />{s.status.replace("_", " ")}</span></td>
                <td className="text-mist-300">{s.status === "locked" ? <span className="text-mist-500">{s.unlock}</span> : s.next}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
