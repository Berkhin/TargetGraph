import { useState } from "react";
import { Building2, ExternalLink, FileText, Trash2 } from "lucide-react";
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
import { useDeleteJob } from "@/features/jobs-board/hooks/useDeleteJob";
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
  DISCARDED: "outline",
};

const STATUS_LABEL: Record<JobStatus, string> = {
  NEW: "NEW",
  MATCHED: "MATCHED",
  REJECTED_BY_AI: "REJECTED",
  FILTERED_OUT: "FILTERED",
  DISCARDED: "DISCARDED",
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

  // Soft-delete with a confirm dialog so a generated card can be cleared off the
  // board without being re-ingested by the next sourcing run.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteJob = useDeleteJob(job.id);

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

          {/* Link to the company's LinkedIn page; only when the scraper resolved
              one (requires scrapeCompany on the sourcing run). */}
          {job.company_linkedin_url ? (
            <Button
              asChild
              variant="ghost"
              size="icon"
              aria-label="Страница компании"
            >
              <a
                href={job.company_linkedin_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Building2 />
              </a>
            </Button>
          ) : null}

          <Badge variant={STATUS_VARIANT[job.status]}>
            {STATUS_LABEL[job.status]}
          </Badge>

          {/* Soft-delete this posting. Opens a confirm dialog before removing. */}
          <Button
            variant="ghost"
            size="icon"
            aria-label="Удалить карточку"
            disabled={deleteJob.isPending}
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 />
          </Button>
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
            {job.employee_count !== null ? (
              <Badge variant="outline">
                {job.employee_count.toLocaleString("ru-RU")} сотрудников
              </Badge>
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

      {/* Delete confirmation — soft-delete removes the card from the board. */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить карточку?</DialogTitle>
            <DialogDescription>
              «{job.job_title} — {job.company_name}» исчезнет с доски. Это
              действие нельзя отменить из интерфейса.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteJob.isPending}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              disabled={deleteJob.isPending}
              onClick={() =>
                deleteJob.mutate(undefined, {
                  onSuccess: () => setDeleteOpen(false),
                })
              }
            >
              <Trash2 />
              {deleteJob.isPending ? "Удаление..." : "Удалить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
