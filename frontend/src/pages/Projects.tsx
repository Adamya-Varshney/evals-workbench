import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Project } from "../api";
import { Logo } from "../components/Layout";
import { DemoBanner, useTheme } from "../components/ui";

export function Projects() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [theme, toggleTheme] = useTheme();
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
    <div className="min-h-full bg-ink-950">
      <DemoBanner />
      <header className="flex h-11 items-center gap-2 border-b border-ink-700 px-4">
        <Logo />
        <span className="text-[13px] font-semibold text-mist-50">Evals Workbench</span>
        <button onClick={toggleTheme} className="btn-quiet btn-sm ml-auto w-7 justify-center px-0" aria-label="Toggle theme">{theme === "light" ? "☾" : "☀"}</button>
      </header>
      <div className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight text-mist-50">Projects</h1>
        <p className="mt-1 max-w-2xl text-mist-400">
          Read real traces, write down what goes wrong, count it, and turn only the failures that matter into a small, validated set of checks for CI and production.
        </p>

        <div className="mt-6 grid gap-3 md:grid-cols-2">
          <div className="card p-4">
            <div className="flex items-center gap-2">
              <div className="h2">Larkspur Residences demo</div>
              <span className="chip">120 traces</span>
            </div>
            <p className="mt-1 text-mist-400">An apartment-leasing assistant on SMS, email, chat and voice. Some traces fail in ways you'll find by reading.</p>
            <button className="btn-primary mt-3" onClick={() => demo.mutate()} disabled={demo.isPending}>Open demo project</button>
          </div>
          <div className="card p-4">
            <div className="h2">New project</div>
            <p className="mt-1 text-mist-400">Name it after the AI product you're evaluating.</p>
            <form
              className="mt-3 flex gap-2"
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
          <div className="mt-8 overflow-hidden rounded-lg border border-ink-700">
            <table className="tbl">
              <thead>
                <tr><th>Name</th><th>Description</th><th className="w-32">Reviewer</th><th className="w-24" /></tr>
              </thead>
              <tbody>
                {projects.data.map((p) => (
                  <tr key={p.id} className="cursor-pointer" onClick={() => nav(`/p/${p.id}`)}>
                    <td className="font-medium text-mist-50">{p.name}{p.is_demo && <span className="chip ml-2">demo</span>}</td>
                    <td className="max-w-md truncate text-mist-400">{p.description || "—"}</td>
                    <td className="text-mist-300">{p.reviewer_name || "—"}</td>
                    <td className="text-right text-accent-400">Open →</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
