"use client";

type Props = {
  label: string;
};

export default function ProgressBar({ label }: Props) {
  return (
    <div className="w-full">
      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        <div className="progress-slide h-full w-1/3 rounded-full bg-indigo-500" />
      </div>
      <p className="mt-3 text-center text-sm text-zinc-500">{label}</p>
    </div>
  );
}
