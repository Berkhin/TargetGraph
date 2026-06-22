import { JobCard } from "@/features/jobs-board/ui/JobCard";
import { Skeleton } from "@/components/ui/skeleton";
import { useJobs } from "@/features/jobs-board/hooks/useJobs";
import { useMatchedJobs } from "@/features/jobs-board/hooks/useMatchedJobs";
import { useActiveProfile } from "@/features/profiles/hooks/useActiveProfile";
import { getApiErrorMessage } from "@/shared/api/errors";
import type { JobRead } from "@/features/jobs-board/api/types";

function JobCardSkeleton() {
  return (
    <div className="w-full max-w-md space-y-3 rounded-xl border p-6">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-6 w-20" />
      <Skeleton className="h-9 w-full" />
    </div>
  );
}

// A card seeds its editable drafts from props at mount, so a re-match that
// rewrites them must remount the card — key on updated_at as well as id.
function cardKey(job: JobRead): string {
  return `${job.id}:${job.updated_at}`;
}

export function JobsFeedPage() {
  // Two queries feed one board: NEW postings awaiting matching, and MATCHED
  // postings ready to send. The MATCHED query shares its key with the "Отклики"
  // table, so TanStack serves both from one cache entry.
  const newJobsQuery = useJobs();
  const matchedQuery = useMatchedJobs();
  // Active profile drives the AI matching call; until it loads (or if none
  // exists) the generate/regenerate buttons stay disabled.
  const { data: profile } = useActiveProfile();
  const profileId = profile?.id ?? null;

  const isPending = newJobsQuery.isPending || matchedQuery.isPending;
  const isError = newJobsQuery.isError || matchedQuery.isError;
  const error = newJobsQuery.error ?? matchedQuery.error;

  const newJobs = newJobsQuery.data ?? [];
  // Sent postings live only in the "Отклики" table; the board shows MATCHED
  // postings that are still awaiting an outreach send (applied_at == null).
  const readyJobs = (matchedQuery.data ?? []).filter(
    (job) => job.applied_at == null,
  );

  return (
    <main className="mx-auto px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">Jobs Feed</h1>
        <p className="text-muted-foreground">
          {profile
            ? `Сопоставление с профилем: ${profile.candidate_name}`
            : "Sourced postings ready for AI matching."}
        </p>
      </header>

      {isPending ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <JobCardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <p className="text-destructive">
          Не удалось загрузить вакансии: {getApiErrorMessage(error)}
        </p>
      ) : newJobs.length === 0 && readyJobs.length === 0 ? (
        <p className="text-muted-foreground">Новых вакансий нет.</p>
      ) : (
        <div className="space-y-12">
          {readyJobs.length > 0 ? (
            <section>
              <h2 className="mb-4 text-xl font-semibold tracking-tight">
                Готовые к отправке
              </h2>
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                {readyJobs.map((job) => (
                  <JobCard
                    key={cardKey(job)}
                    job={job}
                    profileId={profileId}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {newJobs.length > 0 ? (
            <section>
              <h2 className="mb-4 text-xl font-semibold tracking-tight">
                Новые
              </h2>
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {newJobs.map((job) => (
                  <JobCard
                    key={cardKey(job)}
                    job={job}
                    profileId={profileId}
                  />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      )}
    </main>
  );
}
