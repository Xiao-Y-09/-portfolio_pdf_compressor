"use client";

import { useCallback, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}";
const TARGETS = [5, 10, 15, 20];

type Phase = "idle" | "uploading" | "processing" | "done" | "error";

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
  vector_preserving: "Vector preserving — text stays sharp",
  page_rasterization: "Page rasterization — aggressive target",
  passthrough: "Already under target",
};

function mb(bytes: number): string {
  return (bytes / 1048576).toFixed(2) + " MB";
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState(10);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState<JobResult | null>(null);
  const [jobId, setJobId] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setPhase("idle");
    setError("");
    setResult(null);
    setJobId("");
    setFile(null);
  };

  const pickFile = (picked: File | null) => {
    if (!picked) return;
    if (!picked.name.toLowerCase().endsWith(".pdf")) {
      setError("Please choose a PDF file.");
      return;
    }
    setError("");
    setFile(picked);
    setPhase("idle");
    setResult(null);
  };

  const poll = useCallback(async (id: string) => {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      const res = await fetch(`${API}/api/jobs/${id}`);
      if (!res.ok) throw new Error(`status check failed (${res.status})`);
      const payload = await res.json();
      if (payload.status === "done") return payload.result as JobResult;
      if (payload.status === "error") throw new Error(payload.error ?? "compression failed");
    }
  }, []);

  const compress = async () => {
    if (!file) return;
    setPhase("uploading");
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("target_mb", String(target));
      const res = await fetch(`${API}/api/jobs`, { method: "POST", body: form });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail;
        throw new Error(typeof detail === "string" ? detail : `upload failed (${res.status})`);
      }
      const { job_id } = await res.json();
      setJobId(job_id);
      setPhase("processing");
      setResult(await poll(job_id));
      setPhase("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "something went wrong");
      setPhase("error");
    }
  };

  const busy = phase === "uploading" || phase === "processing";

  return (
    <main className="min-h-screen w-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto max-w-xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Portfolio Compressor</h1>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
          Compress your portfolio PDF to a hard size limit with the best possible
          image quality. Files are processed in memory and expire within an hour.
        </p>

        <div
          className={`mt-8 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
            dragging
              ? "border-zinc-900 bg-zinc-100 dark:border-zinc-100 dark:bg-zinc-900"
              : "border-zinc-300 dark:border-zinc-700"
          }`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pickFile(e.dataTransfer.files[0] ?? null);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
          />
          {file ? (
            <>
              <p className="font-medium">{file.name}</p>
              <p className="mt-1 text-sm text-zinc-500">{mb(file.size)}</p>
            </>
          ) : (
            <>
              <p className="font-medium">Drop your PDF here</p>
              <p className="mt-1 text-sm text-zinc-500">or click to browse</p>
            </>
          )}
        </div>

        <div className="mt-6">
          <p className="text-sm font-medium">Target size</p>
          <div className="mt-2 grid grid-cols-4 gap-2">
            {TARGETS.map((t) => (
              <button
                key={t}
                onClick={() => setTarget(t)}
                disabled={busy}
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                  target === t
                    ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                    : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
                }`}
              >
                {t} MB
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={compress}
          disabled={!file || busy}
          className="mt-6 w-full rounded-lg bg-zinc-900 px-4 py-3 text-sm font-semibold text-white transition-opacity disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {phase === "uploading"
            ? "Uploading..."
            : phase === "processing"
              ? "Compressing... this can take a minute or two"
              : `Compress to ${target} MB`}
        </button>

        {busy && (
          <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
            <div className="h-full w-1/3 animate-pulse rounded-full bg-zinc-900 dark:bg-zinc-100" />
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error}
          </p>
        )}

        {phase === "done" && result && (
          <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <p className="text-sm text-zinc-500">
              {mb(result.original_bytes)} →{" "}
              <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                {mb(result.output_bytes)}
              </span>{" "}
              · {result.page_count} pages · {result.duration_seconds.toFixed(1)}s
            </p>
            <p className="mt-1 text-xs text-zinc-400">
              {STRATEGY_LABEL[result.strategy] ?? result.strategy}
            </p>
            <a
              href={`${API}/api/jobs/${jobId}/download`}
              className="mt-4 block w-full rounded-lg bg-emerald-600 px-4 py-3 text-center text-sm font-semibold text-white hover:bg-emerald-700"
            >
              Download compressed PDF
            </a>
            <button
              onClick={reset}
              className="mt-2 w-full rounded-lg px-4 py-2 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            >
              Compress another file
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
