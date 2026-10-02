import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Channel, type Project } from "../api";
import { Notice, PageHeader, usePid, useProject } from "../components/ui";

const CHANNEL_PRESETS: Record<string, string> = {
  sms: "SMS is plain text exactly as a phone shows it. Markdown symbols appear literally.",
  email: "Email renders as an email: greeting, body, sign-off.",
  chat: "The chat widget shows plain text with line breaks.",
  voice: "Voice replies are read aloud. No lists, links or symbols.",
};

type PV = { id: number; label: string; body: string; created_at: string };

export function Setup() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const [form, setForm] = useState<Partial<Project>>({});
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (project.data) setForm(project.data);
  }, [project.data]);
  const save = useMutation({
    mutationFn: (p: Partial<Project>) => api.patch<Project>(`/api/projects/${pid}`, p),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    },
  });
  const set = (k: keyof Project, v: any) => setForm((f) => ({ ...f, [k]: v }));
  const channels = (form.channels ?? []) as Channel[];
  if (!project.data) return null;
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <PageHeader title="Set up the project" sub="Capture the context you carry in your head when you judge a trace. You can edit all of this later." />
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ name: form.name, description: form.description, channels, business_facts: form.business_facts, reviewer_name: form.reviewer_name });
        }}
      >
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Product name</label>
            <input className="input" value={form.name ?? ""} onChange={(e) => set("name", e.target.value)} />
          </div>
          <div>
            <label className="label">Your name (reviewer)</label>
            <input className="input" placeholder="Stored on every label you make" value={form.reviewer_name ?? ""} onChange={(e) => set("reviewer_name", e.target.value)} />
          </div>
        </div>
        <div>
          <label className="label">What the AI system does, and for whom</label>
          <textarea className="input min-h-[90px]" value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
        </div>
        <div>
          <label className="label">Channels and how each one renders</label>
          <div className="space-y-2">
            {channels.map((c, i) => (
              <div key={i} className="flex gap-2">
                <input className="input w-36" value={c.name} onChange={(e) => set("channels", channels.map((x, j) => (j === i ? { ...x, name: e.target.value.toLowerCase() } : x)))} />
                <input className="input" value={c.render_rule} placeholder="Render rule, e.g. SMS is plain text" onChange={(e) => set("channels", channels.map((x, j) => (j === i ? { ...x, render_rule: e.target.value } : x)))} />
                <button type="button" className="btn-quiet" onClick={() => set("channels", channels.filter((_, j) => j !== i))} aria-label="Remove channel">✕</button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              {Object.keys(CHANNEL_PRESETS)
                .filter((k) => !channels.some((c) => c.name === k))
                .map((k) => (
                  <button type="button" key={k} className="chip hover:border-accent-400" onClick={() => set("channels", [...channels, { name: k, render_rule: CHANNEL_PRESETS[k] }])}>
                    + {k}
                  </button>
                ))}
              <button type="button" className="chip hover:border-accent-400" onClick={() => set("channels", [...channels, { name: "other", render_rule: "" }])}>
                + other
              </button>
            </div>
          </div>
        </div>
        <div>
          <label className="label">Things I know that the model does not</label>
          <textarea
            className="input min-h-[150px] font-mono text-[13px]"
            placeholder={"- We do not offer virtual tours\n- Same-day tour requests must go to a human"}
            value={form.business_facts ?? ""}
            onChange={(e) => set("business_facts", e.target.value)}
          />
          <p className="mt-1 text-xs text-mist-400">Shown to you while reviewing, and offered as context when drafting judges. Never used to judge traces automatically.</p>
        </div>
        <div className="flex items-center gap-3">
          <button className="btn-primary" disabled={save.isPending}>Save</button>
          {saved && <span className="text-sm text-pass-400">✓ Saved</span>}
        </div>
      </form>
      <PromptVersions pid={pid} />
    </div>
  );
}

function PromptVersions({ pid }: { pid: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pvs", pid], queryFn: () => api.get<PV[]>(`/api/projects/${pid}/prompt_versions`) });
  const [label, setLabel] = useState("");
  const [body, setBody] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/prompt_versions`, { label, body }),
    onSuccess: () => {
      setLabel("");
      setBody("");
      setErr("");
      qc.invalidateQueries({ queryKey: ["pvs", pid] });
    },
    onError: (e: any) => setErr(e.message),
  });
  return (
    <div className="mt-12">
      <div className="h2">System prompts under test</div>
      <p className="mb-3 mt-1 text-sm text-mist-400">Each stored with a version label. Imported traces that carry a prompt version are linked automatically.</p>
      <div className="space-y-2">
        {q.data?.map((v) => (
          <div key={v.id} className="rounded-lg border border-ink-700 bg-ink-900">
            <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" onClick={() => setOpen(open === v.id ? null : v.id)}>
              <span className="chip">{v.label}</span>
              <span className="truncate text-mist-400">{v.body.slice(0, 90)}</span>
              <span className="ml-auto text-mist-500">{open === v.id ? "▾" : "▸"}</span>
            </button>
            {open === v.id && <pre className="whitespace-pre-wrap border-t border-ink-800 px-4 py-3 font-mono text-[12.5px] text-mist-200">{v.body}</pre>}
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-[160px_1fr_auto] items-start gap-2">
        <input className="input" placeholder="Version, e.g. v1.5" value={label} onChange={(e) => setLabel(e.target.value)} />
        <textarea className="input min-h-[42px] font-mono text-[12.5px]" placeholder="Paste the system prompt" value={body} onChange={(e) => setBody(e.target.value)} />
        <button className="btn-ghost" disabled={!label.trim()} onClick={() => add.mutate()}>Add version</button>
      </div>
      {err && <div className="mt-2"><Notice tone="danger">{err}</Notice></div>}
    </div>
  );
}
