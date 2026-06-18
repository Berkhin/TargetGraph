import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { JobRead, JobStatus } from "@/features/jobs-board/api/types";
import { useMatchJob } from "@/features/jobs-board/hooks/useMatchJob";

// Visual treatment per lifecycle status (see JobStatus in contracts/job.ts).
const STATUS_VARIANT: Record<
  JobStatus,
  React.ComponentProps<typeof Badge>["variant"]
> = {
  NEW: "default",
  MATCHED: "secondary",
  REJECTED_BY_AI: "destructive",
};

const STATUS_LABEL: Record<JobStatus, string> = {
  NEW: "NEW",
  MATCHED: "MATCHED",
  REJECTED_BY_AI: "REJECTED",
};

export type JobCardProps = {
  job: JobRead;
  // Candidate profile to match this job against (required by POST /match).
  // Null while the active profile is still loading or none exists yet.
  profileId: string | null;
  // Optional caller-supplied location override; falls back to the persisted
  // `job.location` now exposed by the backend.
  location?: string;
};

export function JobCard({ job, profileId, location }: JobCardProps) {
  const matchJob = useMatchJob();

  const displayLocation = location ?? job.location;

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>{job.job_title}</CardTitle>
        <CardDescription>{job.company_name}</CardDescription>
        <CardAction>
          <Badge variant={STATUS_VARIANT[job.status]}>
            {STATUS_LABEL[job.status]}
          </Badge>
        </CardAction>
      </CardHeader>

      <CardContent className="flex flex-wrap gap-2">
        {displayLocation ? (
          <Badge variant="outline">{displayLocation}</Badge>
        ) : null}
        {job.employment_type ? (
          <Badge variant="outline">{job.employment_type}</Badge>
        ) : null}
        {job.seniority_level ? (
          <Badge variant="outline">{job.seniority_level}</Badge>
        ) : null}
        {job.salary ? (
          <Badge variant="outline">{job.salary}</Badge>
        ) : null}
        {job.match_score !== null ? (
          <Badge variant="secondary">Match {job.match_score}%</Badge>
        ) : null}
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          disabled={matchJob.isPending || profileId === null}
          onClick={() =>
            profileId !== null &&
            matchJob.mutate({ jobId: job.id, profileId })
          }
        >
          {matchJob.isPending ? "Генерация..." : "Сгенерировать отклик"}
        </Button>
      </CardFooter>
    </Card>
  );
}
