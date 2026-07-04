"use client";

export type PageType = "hero" | "process";

type Props = {
  thumbnails: string[]; // base64 JPEG per page
  classifications: PageType[];
  selected: number[]; // 1-indexed page numbers
  onSelectionChange: (pages: number[]) => void;
};

export default function ThumbnailGrid({
  thumbnails,
  classifications,
  selected,
  onSelectionChange,
}: Props) {
  const selectedSet = new Set(selected);
  const allPages = thumbnails.map((_, i) => i + 1);

  const toggle = (page: number) => {
    const next = new Set(selectedSet);
    if (next.has(page)) next.delete(page);
    else next.add(page);
    onSelectionChange([...next].sort((a, b) => a - b));
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-zinc-500">
          <span className="font-semibold text-zinc-900 dark:text-zinc-100">
            {selected.length}
          </span>{" "}
          of {thumbnails.length} pages marked important
        </p>
        <div className="flex gap-1.5 text-xs">
          <button
            onClick={() => onSelectionChange(allPages)}
            className="rounded-md border border-zinc-300 px-2.5 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Select all
          </button>
          <button
            onClick={() => onSelectionChange([])}
            className="rounded-md border border-zinc-300 px-2.5 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Clear
          </button>
          <button
            onClick={() =>
              onSelectionChange(allPages.filter((p) => !selectedSet.has(p)))
            }
            className="rounded-md border border-zinc-300 px-2.5 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Invert
          </button>
        </div>
      </div>

      <div className="grid max-h-[26rem] grid-cols-2 gap-3 overflow-y-auto rounded-xl border border-zinc-200 bg-zinc-50 p-3 sm:grid-cols-3 md:grid-cols-4 dark:border-zinc-800 dark:bg-zinc-950">
        {thumbnails.map((thumb, i) => {
          const page = i + 1;
          const isSelected = selectedSet.has(page);
          const aiHero = classifications[i] === "hero";
          return (
            <button
              key={page}
              onClick={() => toggle(page)}
              aria-pressed={isSelected}
              className={`group relative overflow-hidden rounded-lg border-2 bg-white text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md dark:bg-zinc-900 ${
                isSelected
                  ? "border-indigo-500 ring-2 ring-indigo-200 dark:ring-indigo-900"
                  : "border-transparent"
              }`}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`data:image/jpeg;base64,${thumb}`}
                alt={`Page ${page}`}
                className="aspect-[3/4] w-full object-cover"
              />
              <span
                className={`absolute left-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-md border text-[11px] font-bold ${
                  isSelected
                    ? "border-indigo-500 bg-indigo-500 text-white"
                    : "border-zinc-300 bg-white/90 text-transparent dark:border-zinc-600 dark:bg-zinc-800/90"
                }`}
              >
                ✓
              </span>
              <div className="flex items-center justify-between px-2 py-1.5">
                <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
                  p.{page}
                </span>
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                    aiHero
                      ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
                      : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                  }`}
                >
                  AI: {aiHero ? "important" : "standard"}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
