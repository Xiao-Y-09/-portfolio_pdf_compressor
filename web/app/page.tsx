"use client";

import { useCallback, useState } from "react";
import ProgressBar from "./components/ProgressBar";
import ThumbnailGrid, { type PageType } from "./components/ThumbnailGrid";
import UploadZone from "./components/UploadZone";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TARGETS = [5, 10, 15, 20];

type Phase = "upload" | "analyzing" | "review" | "compressing" | "done";

type Analysis = {
  job_id: string;
  page_count: number;
  original_size_mb: number;
  thumbnails: string[];
  page_classifications: PageType[];
  ai_suggested_pages: number[];
};

type JobResult = {
  strategy: string;
  original_bytes: number;
  output_bytes: number;
  target_bytes: number;
  page_count: number;
  quality_maxed: boolean;
  duration_seconds: number;
};

const STRATEGY_LABEL: Record<string, string> = {
  vector_preserving: "Vector preserving — your text stays razor sharp",
  page_rasterization: "Page rasterization — extreme target fallback",
  passthrough: "Already under target — no compression needed",
};

function mb(bytes: number): string {
  return (bytes / 1048576).toFixed(2) + " MB";
}

async function apiError(res: Response, fallback: string): Promise<string> {
  const detail = (await res.json().catch(() => null))?.detail;
  return typeof detail === "string" ? detail : fallback;
}

export default function Home() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState(10);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [result, setResult] = useState<JobResult | null>(null);
  const [error, setError] = useState("");

  const reset = () => {
    setPhase("upload");
    setFile(null);
    setAnalysis(null);
    setSelected([]);
    setResult(null);
    setError("");
  };

  const analyze = async (picked: File) => {
    setFile(picked);
    setError("");
    setPhase("analyzing");
    try {
      const form = new FormData();
      form.append("file", picked);
      const res = await fetch(`${API}/api/jobs`, { method: "POST", body: form });
      if (!res.ok) throw new Error(await apiError(res, `upload failed (${res.status})`));
      const payload = (await res.json()) as Analysis;
      setAnalysis(payload);
      setSelected(payload.ai_suggested_pages);
      setPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "something went wrong");
      setPhase("upload");
    }
  };

  const poll = useCallback(async (jobId: string): Promise<JobResult> => {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      const res = await fetch(`${API}/api/jobs/${jobId}`);
      if (!res.ok) throw new Error(`status check failed (${res.status})`);
      const payload = await res.json();
      if (payload.status === "done") return payload.result as JobResult;
      if (payload.status === "error") throw new Error(payload.error ?? "compression failed");
    }
  }, []);

  const compress = async () => {
    if (!analysis) return;
    setError("");
    setPhase("compressing");
    try {
      const res = await fetch(`${API}/api/jobs/${analysis.job_id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_size_mb: target, selected_pages: selected }),
      });
      if (!res.ok) throw new Error(await apiError(res, `confirm failed (${res.status})`));
      setResult(await poll(analysis.job_id));
      setPhase("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "something went wrong");
      setPhase("review");
    }
  };

  return (
    <main className="min-h-screen w-full bg-gradient-to-b from-indigo-50/60 to-zinc-50 text-zinc-900 dark:from-zinc-900 dark:to-zinc-950 dark:text-zinc-100">
      <header className="mx-auto flex max-w-3xl items-center gap-2.5 px-6 pt-10">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 font-bold text-white shadow-sm">
          PC
        </div>
        <span className="text-lg font-semibold tracking-tight">
          Portfolio Compressor
        </span>
      </header>

      <div className="mx-auto max-w-3xl px-6 py-10">
        {phase === "upload" && (
          <section>
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Hit the size limit.{" "}
              <span className="text-indigo-600 dark:text-indigo-400">
                Keep the quality.
              </span>
            </h1>
            <p className="mt-3 max-w-xl text-zinc-600 dark:text-zinc-400">
              Compress your 60–100 MB portfolio to 5/10/15/20 MB. Text always stays
              vector-sharp; you choose which pages get the best image treatment.
            </p>
            <div className="mt-8">
              <UploadZone file={file} onFile={analyze} onError={setError} />
            </div>
          </section>
        )}

        {phase === "analyzing" && (
          <section className="rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-6 text-xl font-semibold">Analyzing {file?.name}…</h2>
            <ProgressBar label="Rendering page previews and classifying pages" />
          </section>
        )}

        {phase === "review" && analysis && (
          <section className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-xl font-semibold">Review your pages</h2>
            <p className="mt-1 mb-5 text-sm text-zinc-500">
              {analysis.page_count} pages · {analysis.original_size_mb} MB. Pages marked{" "}
              <span className="font-medium text-indigo-600 dark:text-indigo-400">
                important
              </span>{" "}
              keep higher image quality. We pre-selected what looks important — adjust
              freely.
            </p>

            <ThumbnailGrid
              thumbnails={analysis.thumbnails}
              classifications={analysis.page_classifications}
              selected={selected}
              onSelectionChange={setSelected}
            />

            <div className="mt-6">
              <p className="text-sm font-medium">Target size</p>
              <div className="mt-2 grid grid-cols-4 gap-2">
                {TARGETS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTarget(t)}
                    className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                      target === t
                        ? "border-indigo-600 bg-indigo-600 text-white"
                        : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    }`}
                  >
                    {t} MB
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-6 flex flex-col gap-2 sm:flex-row">
              <button
                onClick={compress}
                className="flex-1 rounded-lg bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700"
              >
                Compress to {target} MB
              </button>
              <button
                onClick={reset}
                className="rounded-lg border border-zinc-300 px-4 py-3 text-sm text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                Start over
              </button>
            </div>
          </section>
        )}

        {phase === "compressing" && (
          <section className="rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-6 text-xl font-semibold">
              Compressing to {target} MB…
            </h2>
            <ProgressBar label="Recompressing images and subsetting fonts — this can take a minute or two" />
          </section>
        )}

        {phase === "done" && result && analysis && (
          <section className="rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="mb-1 flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400">
                ✓
              </span>
              <h2 className="text-xl font-semibold">Ready to download</h2>
            </div>
            <p className="mt-3 text-sm text-zinc-500">
              {mb(result.original_bytes)} →{" "}
              <span className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                {mb(result.output_bytes)}
              </span>{" "}
              · {result.page_count} pages · {result.duration_seconds.toFixed(1)}s
            </p>
            <p className="mt-1 text-xs text-zinc-400">
              {STRATEGY_LABEL[result.strategy] ?? result.strategy}
            </p>
            <a
              href={`${API}/api/jobs/${analysis.job_id}/download`}
              className="mt-6 block w-full rounded-lg bg-emerald-600 px-4 py-3 text-center text-sm font-semibold text-white shadow-sm transition-colors hover:bg-emerald-700"
            >
              Download compressed PDF
            </a>
            <button
              onClick={reset}
              className="mt-2 w-full rounded-lg px-4 py-2 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            >
              Compress another file
            </button>
          </section>
        )}

        {error && (
          <p className="mt-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error}
          </p>
        )}

        <footer className="mt-12 text-center text-xs text-zinc-400">
          Files are processed in memory and deleted within an hour. No accounts, no
          storage.
        </footer>
      </div>
    </main>
  );
}
