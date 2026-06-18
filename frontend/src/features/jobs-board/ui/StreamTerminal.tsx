import type { StreamPhase } from "@/features/jobs-board/hooks/useMatchJobStream";

export type StreamTerminalProps = {
  // Live log lines emitted by the matching pipeline (see useMatchJobStream).
  logs: string[];
  // Current run phase; colours the last line green on "done", red on "error".
  phase: StreamPhase;
  // Tailwind height utility for the scroll area, so each card can size it to
  // fit its layout (the compact JobCard vs the wider CoverLetterCard).
  heightClassName?: string;
};

// The streaming "terminal" shown while the AI pipeline runs and after it
// finishes, so the log stays readable. Shared by JobCard and CoverLetterCard so
// the "regenerate" action looks identical on both.
export function StreamTerminal({
  logs,
  phase,
  heightClassName = "h-40",
}: StreamTerminalProps) {
  return (
    <div
      className={`${heightClassName} overflow-y-auto rounded-md bg-zinc-900 p-3 font-mono text-xs leading-relaxed text-zinc-100`}
    >
      {logs.length === 0 ? (
        <p className="text-zinc-400">Подключение...</p>
      ) : (
        logs.map((line, i) => {
          const isLast = i === logs.length - 1;
          const doneColor =
            isLast && phase === "done"
              ? "text-emerald-400"
              : isLast && phase === "error"
                ? "text-red-400"
                : "";
          return (
            <p key={i} className={doneColor}>
              <span className="text-emerald-400">$</span> {line}
            </p>
          );
        })
      )}
    </div>
  );
}
