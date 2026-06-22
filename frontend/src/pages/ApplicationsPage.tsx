import { useState } from "react";
import { ExternalLink, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { JobRead } from "@/features/jobs-board/api/types";
import { useDeleteJob } from "@/features/jobs-board/hooks/useDeleteJob";
import { useMatchedJobs } from "@/features/jobs-board/hooks/useMatchedJobs";
import { getApiErrorMessage } from "@/shared/api/errors";

// One row in the sent-applications log. Each row owns its delete mutation and
// confirm dialog (hooks can't run inside a .map), so a single row can be
// removed without touching the others. useDeleteJob invalidates the MATCHED
// list, so the row disappears on success without a manual refetch.
function ApplicationRow({ job }: { job: JobRead }) {
  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteJob = useDeleteJob(job.id);

  return (
    <TableRow>
      <TableCell className="font-medium">{job.company_name}</TableCell>
      <TableCell>{job.job_title}</TableCell>
      <TableCell>
        {job.recruiter_name || job.recruiter_email ? (
          <div className="flex flex-col">
            {job.recruiter_name ? <span>{job.recruiter_name}</span> : null}
            {job.recruiter_email ? (
              <a
                href={`mailto:${job.recruiter_email}`}
                className="text-muted-foreground text-xs hover:underline"
              >
                {job.recruiter_email}
              </a>
            ) : null}
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap">
        {job.applied_at
          ? new Date(job.applied_at).toLocaleDateString()
          : "—"}
      </TableCell>
      <TableCell>
        {job.match_score != null ? `${job.match_score}%` : "—"}
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          <Button asChild variant="ghost" size="icon" aria-label="Открыть вакансию">
            <a href={job.source_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink />
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Удалить отклик"
            disabled={deleteJob.isPending}
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 />
          </Button>
        </div>

        {/* Delete confirmation — soft-delete removes the row from the log. */}
        <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Удалить отклик?</DialogTitle>
              <DialogDescription>
                «{job.job_title} — {job.company_name}» исчезнет из журнала
                откликов. Это действие нельзя отменить из интерфейса.
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
      </TableCell>
    </TableRow>
  );
}

// Read-only log of outreach already sent: MATCHED postings stamped with an
// applied_at. Shares the MATCHED query with the jobs board (deduped by key);
// the board shows not-yet-sent matches, this table shows the sent ones.
export function ApplicationsPage() {
  const { data, isPending, isError, error } = useMatchedJobs();
  const sent = (data ?? []).filter((job) => job.applied_at != null);

  return (
    <main className="mx-auto px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">Отклики</h1>
        <p className="text-muted-foreground">
          Журнал отправленных откликов: кому и когда отправлено.
        </p>
      </header>

      {isPending ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-destructive">
          Не удалось загрузить отклики: {getApiErrorMessage(error)}
        </p>
      ) : sent.length === 0 ? (
        <p className="text-muted-foreground">
          Вы ещё не отправили ни одного отклика.
        </p>
      ) : (
        <div className="rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Компания</TableHead>
                <TableHead>Должность</TableHead>
                <TableHead>Рекрутёр</TableHead>
                <TableHead>Дата отправки</TableHead>
                <TableHead>Match</TableHead>
                <TableHead className="text-right">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sent.map((job) => (
                <ApplicationRow key={job.id} job={job} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  );
}
