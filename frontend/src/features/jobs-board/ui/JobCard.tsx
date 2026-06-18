import { ExternalLink, FileText } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { JobRead, JobStatus } from "@/features/jobs-board/api/types";
import { useMatchJobStream } from "@/features/jobs-board/hooks/useMatchJobStream";
import { StreamTerminal } from "@/features/jobs-board/ui/StreamTerminal";

// Visual treatment per lifecycle status (see JobStatus in contracts/job.ts).
const STATUS_VARIANT: Record<
  JobStatus,
  React.ComponentProps<typeof Badge>["variant"]
> = {
  NEW: "default",
  MATCHED: "secondary",
  REJECTED_BY_AI: "destructive",
  FILTERED_OUT: "outline",
};

const STATUS_LABEL: Record<JobStatus, string> = {
  NEW: "NEW",
  MATCHED: "MATCHED",
  REJECTED_BY_AI: "REJECTED",
  FILTERED_OUT: "FILTERED",
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
  const { phase, isGenerating, streamLogs, startGeneration } =
    useMatchJobStream();

  const displayLocation = location ?? job.location;

  // Terminal stays visible during the run and after it finishes (done/error),
  // so the log remains readable; only "idle" shows the metadata badges.
  const showTerminal = phase !== "idle";

  const buttonLabel = isGenerating
    ? "Генерация..."
    : phase === "done"
      ? "Сгенерировать заново"
      : phase === "error"
        ? "Повторить"
        : "Сгенерировать отклик";

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>{job.job_title}</CardTitle>
        <CardDescription>{job.company_name}</CardDescription>
        <CardAction className="flex items-center gap-1">
          {/* Description popup: the full posting text is long, so it lives in a
              modal instead of cluttering the card. */}
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Описание вакансии">
                <FileText />
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[80vh] overflow-hidden">
              <DialogHeader>
                <DialogTitle>{job.job_title}</DialogTitle>
                <DialogDescription>{job.company_name}</DialogDescription>
              </DialogHeader>
              <div className="max-h-[55vh] overflow-y-auto pr-2 text-sm whitespace-pre-wrap">
                {job.description}
              </div>
              <DialogFooter>
                <Button asChild variant="outline">
                  <a
                    href={job.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink /> Открыть вакансию
                  </a>
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {/* Direct link to the original posting, always one click away. */}
          <Button
            asChild
            variant="ghost"
            size="icon"
            aria-label="Открыть вакансию"
          >
            <a href={job.source_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink />
            </a>
          </Button>

          <Badge variant={STATUS_VARIANT[job.status]}>
            {STATUS_LABEL[job.status]}
          </Badge>
        </CardAction>
      </CardHeader>

      <CardContent>
        {showTerminal ? (
          // Live AI pipeline "terminal": replaces the metadata while streaming
          // and remains after completion so the log stays readable.
          <StreamTerminal logs={streamLogs} phase={phase} />
        ) : (
          <div className="flex flex-wrap gap-2">
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
          </div>
        )}
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          disabled={isGenerating || profileId === null}
          onClick={() =>
            profileId !== null && startGeneration(job.id, profileId)
          }
        >
          {buttonLabel}
        </Button>
      </CardFooter>
    </Card>
  );
}
