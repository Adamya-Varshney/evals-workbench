import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader, useMeta, usePid, useProject } from "../components/ui";

type Tpl = { id: number; key: string; title: string; body: string; default_body: string };

export function Settings() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const meta = useMeta();
  const [s, setS] = useState<Record<string, any>>({});
  useEffect(() => {
    if (project.data) setS(project.data.settings);
  }, [project.data]);
  const save = useMutation({
    mutationFn: () => api.patch(`/api/projects/${pid}`, { settings: s }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
    },
  });
  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <PageHeader title="Settings" sub="Project preferences and every prompt template the app sends to the model." />
      <div className="card grid grid-cols-2 gap-5 p-5">
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" checked={s.ai_assist_enabled !== false} onChange={(e) => setS({ ...s, ai_assist_enabled: e.target.checked })} />
          AI assist on (when off, nothing is ever sent to the Anthropic API)
        </label>
        <div className="text-sm text-mist-400">
          Model: <span className="font-mono text-mist-200">{meta.data?.model}</span> · mode: <span className="font-mono text-mist-200">{meta.data?.llm_mode}</span>
          <div className="text-xs">Set EVALS_MODEL and LLM_MODE in .env.</div>
        </div>
        <div>
          <label className="label">Traces to review by hand before AI features unlock</label>
          <input className="input w-32" type="number" min={0} value={s.ai_unlock_threshold ?? 30} onChange={(e) => setS({ ...s, ai_unlock_threshold: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">Nudge after this many seconds on one trace</label>
          <input className="input w-32" type="number" min={30} value={s.review_nudge_seconds ?? 120} onChange={(e) => setS({ ...s, review_nudge_seconds: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">Saturation window (recent traces checked for new problems)</label>
          <input className="input w-32" type="number" min={5} value={s.saturation_window ?? 20} onChange={(e) => setS({ ...s, saturation_window: Number(e.target.value) })} />
        </div>
        <div className="flex items-end">
          <button className="btn-primary" onClick={() => save.mutate()}>{save.isSuccess ? "Saved ✓" : "Save settings"}</button>
        </div>
      </div>
      <Templates />
    </div>
  );
}

function Templates() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["templates"], queryFn: () => api.get<Tpl[]>("/api/templates") });
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const save = useMutation({ mutationFn: (k: string) => api.put(`/api/templates/${k}`, { body: draft }), onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }) });
  const reset = useMutation({
    mutationFn: (k: string) => api.post<Tpl>(`/api/templates/${k}/reset`),
    onSuccess: (t) => {
      setDraft(t.body);
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  return (
    <div className="mt-10">
      <div className="h2">Prompt templates</div>
      <p className="mb-3 mt-1 text-sm text-mist-400">Every prompt the app sends is built from these. Placeholders look like {"{{notes}}"}.</p>
      <div className="space-y-2">
        {q.data?.map((t) => (
          <div key={t.key} className="rounded-lg border border-ink-700 bg-ink-900">
            <button
              className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm"
              onClick={() => {
                setOpen(open === t.key ? null : t.key);
                setDraft(t.body);
              }}
            >
              <span className="font-medium text-mist-100">{t.title}</span>
              <span className="font-mono text-xs text-mist-500">{t.key}</span>
              {t.body !== t.default_body && <span className="chip border-gold-500/40 text-gold-300">edited</span>}
              <span className="ml-auto text-mist-500">{open === t.key ? "▾" : "▸"}</span>
            </button>
            {open === t.key && (
              <div className="border-t border-ink-800 p-3">
                <textarea className="input min-h-[300px] font-mono text-[12.5px] leading-relaxed" value={draft} onChange={(e) => setDraft(e.target.value)} />
                <div className="mt-2 flex gap-2">
                  <button className="btn-primary" onClick={() => save.mutate(t.key)}>Save</button>
                  <button className="btn-ghost" onClick={() => reset.mutate(t.key)}>Reset to default</button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
