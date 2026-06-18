import { Skeleton } from "@/components/ui/skeleton";
import { CoverLetterCard } from "@/features/cover-letters/ui/CoverLetterCard";
import { useMatchedJobs } from "@/features/jobs-board/hooks/useMatchedJobs";
import { useActiveProfile } from "@/features/profiles/hooks/useActiveProfile";
import { getApiErrorMessage } from "@/shared/api/errors";

function CoverLetterSkeleton() {
  return (
    <div className="w-full space-y-3 rounded-xl border p-6">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-64 w-full" />
      <Skeleton className="h-9 w-40" />
    </div>
  );
}

export function CoverLettersPage() {
  const { data: jobs, isPending, isError, error } = useMatchedJobs();
  // Active profile drives the "Регенерировать" pipeline; until it loads (or if
  // none exists) the regenerate button on each card stays disabled.
  const { data: profile } = useActiveProfile();

  return (
    <main className="mx-auto px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">Отклики</h1>
        <p className="text-muted-foreground">
          Готовые сопроводительные письма по подходящим вакансиям.
        </p>
      </header>

      {isPending ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <CoverLetterSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <p className="text-destructive">
          Не удалось загрузить отклики: {getApiErrorMessage(error)}
        </p>
      ) : jobs.length === 0 ? (
        <p className="text-muted-foreground">У вас пока нет готовых откликов.</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {jobs.map((job) => (
            // Key on updated_at as well as id: the card seeds its editable
            // drafts from props via useState (read once at mount), so a re-match
            // that rewrites the drafts must remount the card to pick them up.
            <CoverLetterCard
              key={`${job.id}:${job.updated_at}`}
              job={job}
              profileId={profile?.id ?? null}
            />
          ))}
        </div>
      )}
    </main>
  );
}
