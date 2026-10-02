import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Project } from "../api";

export function Projects() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/api/projects") });
  const [name, setName] = useState("");
  const demo = useMutation({
    mutationFn: () => api.post<Project>("/api/projects/demo"),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      nav(`/p/${p.id}`);
    },
  });
  const create = useMutation({
    mutationFn: () => api.post<Project>("/api/projects", { name }),
    onSuccess: (p) => nav(`/p/${p.id}/setup`),
  });
  return (
    <div className="mx-auto max-w-4xl px-8 py-14">
      <div className="mb-10">
        <div className="mb-3 inline-flex items-center gap-2 text-sm text-gold-300">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-gold-400 font-bold text-ink-950">E</span> Evals Workbench
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-mist-50">Find out how your AI product actually fails.</h1>
        <p className="mt-3 max-w-2xl text-mist-300">
          Read real traces, write down what goes wrong, count it, and turn only the failures that matter into a small, validated set of checks you can run in CI and production.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <div className="h2">Try the demo</div>
          <p className="mt-1 text-sm text-mist-300">Larkspur Residences: an apartment-leasing assistant on SMS, email, chat and voice. 120 traces, some of them failing in ways you will find by reading.</p>
          <button className="btn-primary mt-4" onClick={() => demo.mutate()} disabled={demo.isPending}>
            Open the demo project →
          </button>
        </div>
        <div className="card p-5">
          <div className="h2">Start your own</div>
          <p className="mt-1 text-sm text-mist-300">Name it after the AI product you are evaluating.</p>
          <form
            className="mt-4 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate();
            }}
          >
            <input className="input" placeholder="e.g. Support copilot" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-ghost" disabled={!name.trim()}>Create</button>
          </form>
        </div>
      </div>
      {!!projects.data?.length && (
        <div className="mt-10">
          <div className="label">Your projects</div>
          <div className="divide-y divide-ink-800 overflow-hidden rounded-xl border border-ink-700">
            {projects.data.map((p) => (
              <button key={p.id} onClick={() => nav(`/p/${p.id}`)} className="flex w-full items-center justify-between bg-ink-900 px-4 py-3 text-left hover:bg-ink-850">
                <div>
                  <div className="font-medium text-mist-50">{p.name}{p.is_demo && <span className="chip ml-2">demo</span>}</div>
                  <div className="line-clamp-1 text-sm text-mist-400">{p.description || "No description yet"}</div>
                </div>
                <span className="text-mist-400">→</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
