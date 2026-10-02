import { Link } from "react-router-dom";
import { STAGE_ROUTES } from "../components/Layout";
import { StatusIcon, Term, usePid, useProject, useStatus } from "../components/ui";

export function Home() {
  const pid = usePid();
  const project = useProject(pid);
  const status = useStatus(pid);
  const st = status.data;
  if (!st) return null;
  const next = st.next;
  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <div className="mb-8">
        <div className="text-sm text-mist-400">{project.data?.reviewer_name ? `Welcome back, ${project.data.reviewer_name}.` : "Welcome."}</div>
        <h1 className="h1 mt-1">{project.data?.name}</h1>
      </div>

      {next ? (
        <div className="card relative overflow-hidden border-gold-500/40 p-6">
          <div className="absolute inset-y-0 left-0 w-1 bg-gold-400" />
          <div className="label text-gold-300">Next best action</div>
          <div className="mt-1 text-xl font-semibold text-mist-50">
            {st.stages.findIndex((x) => x.key === next.key) + 1}. {next.term ? <Term tip={next.term}>{next.title}</Term> : next.title}
          </div>
          <p className="mt-2 text-mist-200">{next.next}</p>
          <p className="mt-1 text-sm text-mist-400">{next.summary}</p>
          <Link to={`/p/${pid}/${STAGE_ROUTES[next.key]}`} className="btn-primary mt-5">
            Go →
          </Link>
        </div>
      ) : (
        <div className="card p-6">
          <div className="h2">Everything is up to date.</div>
          <p className="mt-1 text-sm text-mist-300">Review 10–20 fresh traces each week, and re-run error analysis after big changes.</p>
        </div>
      )}

      <div className="mt-8 grid grid-cols-2 gap-x-8 gap-y-1 md:grid-cols-2">
        {st.stages.map((s, i) => (
          <Link key={s.key} to={`/p/${pid}/${STAGE_ROUTES[s.key]}`} className="flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-ink-900">
            <StatusIcon status={s.status} />
            <div>
              <div className={`text-sm ${s.status === "locked" ? "text-mist-500" : "text-mist-100"}`}>
                {i + 1}. {s.title} <span className="text-xs text-mist-500">· {s.status.replace("_", " ")}</span>
              </div>
              <div className="text-xs text-mist-400">{s.status === "locked" ? s.unlock : s.next}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
