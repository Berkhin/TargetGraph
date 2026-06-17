import { JobCard } from "@/features/jobs-board/ui/JobCard";
import { Skeleton } from "@/components/ui/skeleton";
import { useJobs } from "@/features/jobs-board/hooks/useJobs";
import { useActiveProfile } from "@/features/profiles/hooks/useActiveProfile";
import { getApiErrorMessage } from "@/shared/api/errors";

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

export function JobsFeedPage() {
  const { data: jobs, isPending, isError, error } = useJobs();
  // Active profile drives the AI matching call; until it loads (or if none
  // exists) the generate button stays disabled.
  const { data: profile } = useActiveProfile();

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
      ) : jobs.length === 0 ? (
        <p className="text-muted-foreground">Новых вакансий нет.</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} profileId={profile?.id ?? null} />
          ))}
        </div>
      )}
    </main>
  );
}
