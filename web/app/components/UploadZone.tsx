"use client";

import { useRef, useState } from "react";

type Props = {
  file: File | null;
  disabled?: boolean;
  onFile: (file: File) => void;
  onError: (message: string) => void;
};

function mb(bytes: number): string {
  return (bytes / 1048576).toFixed(1) + " MB";
}

export default function UploadZone({ file, disabled, onFile, onError }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = (picked: File | null) => {
    if (!picked || disabled) return;
    if (!picked.name.toLowerCase().endsWith(".pdf")) {
      onError("Please choose a PDF file.");
      return;
    }
    onFile(picked);
  };

  return (
    <div
      className={`group flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-all ${
        dragging
          ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40"
          : "border-zinc-300 bg-white hover:border-indigo-400 hover:bg-indigo-50/50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-indigo-500 dark:hover:bg-indigo-950/20"
      } ${disabled ? "pointer-events-none opacity-60" : ""}`}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        pick(e.dataTransfer.files[0] ?? null);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />
      <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-indigo-100 text-indigo-600 transition-transform group-hover:scale-105 dark:bg-indigo-950 dark:text-indigo-400">
        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </div>
      {file ? (
        <>
          <p className="font-medium">{file.name}</p>
          <p className="mt-1 text-sm text-zinc-500">{mb(file.size)}</p>
          <p className="mt-2 text-xs text-indigo-500">Click to choose a different file</p>
        </>
      ) : (
        <>
          <p className="font-semibold">Drop your portfolio PDF here</p>
          <p className="mt-1 text-sm text-zinc-500">or click to browse — up to 200 MB</p>
        </>
      )}
    </div>
  );
}
