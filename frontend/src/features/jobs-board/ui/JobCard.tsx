import { useState } from "react";
import {
  Building2,
  Copy,
  Download,
  ExternalLink,
  FileText,
  RefreshCw,
  Send,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  cvFileName,
  cvPdfBase64,
  downloadCvPdf,
} from "@/features/jobs-board/lib/cvToPdf";
import type { JobRead, JobStatus } from "@/features/jobs-board/api/types";
import { useDeleteJob } from "@/features/jobs-board/hooks/useDeleteJob";
import { useMatchJobStream } from "@/features/jobs-board/hooks/useMatchJobStream";
import { useSendOutreach } from "@/features/jobs-board/hooks/useSendOutreach";
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
  // Candidate profile to match this job against (required by the match stream).
  // Null while the active profile is still loading or none exists yet.
  profileId: string | null;
  // Optional caller-supplied location override; falls back to the persisted
  // `job.location` now exposed by the backend.
  location?: string;
};

// A single lifecycle-aware posting card. The same component covers the whole
// flow that used to be split across two pages:
//   • NEW  → metadata badges + "Сгенерировать отклик" (runs the match stream).
//   • MATCHED → editable Cover Letter / Tailored CV tabs, copy / download PDF,
//     "Отправить рекрутёру" (Gmail), and "Регенерировать" (re-runs the pipeline).
// The header (links, status, applied marker, soft-delete) is shown in both
// states; while a run streams, the terminal replaces the content.
//
// Matched drafts are local (useState) so the user can polish them before
// sending/copying; edits are intentionally not persisted. Because they are
// seeded from props at mount, a re-match that rewrites the drafts must remount
// the card — JobsFeedPage keys each card on `${id}:${updated_at}` for this.
export function JobCard({ job, profileId, location }: JobCardProps) {
  const isMatched = job.status === "MATCHED";

  const { phase, isGenerating, streamLogs, startGeneration } =
    useMatchJobStream();

  // Soft-delete with a confirm dialog so a card can be cleared off the board
  // without being re-ingested by the next sourcing run.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteJob = useDeleteJob(job.id);

  // Editable matched-state drafts. Harmless to seed for a NEW job (nulls → "")
  // since they are only rendered once the card is MATCHED.
  const [draft, setDraft] = useState(job.cover_letter_draft ?? "");
  const [cv, setCv] = useState(job.tailored_cv_draft ?? "");

  // Cold-outreach send dialog. Recipient/subject are seeded from the job and
  // remain editable — sending an email is irreversible, so the user confirms
  // every field before it goes out. Body defaults to the (edited) cover letter.
  const [sendOpen, setSendOpen] = useState(false);
  const [toEmail, setToEmail] = useState(job.recruiter_email ?? "");
  const [subject, setSubject] = useState(
    `Application for ${job.job_title} — ${job.company_name}`,
  );
  const sendOutreach = useSendOutreach(job.id);
  // Covers the WHOLE send op — including the async PDF build that precedes the
  // mutation. Without it the button is only disabled once isPending flips (after
  // .mutate), leaving a window during PDF generation where a second click sends
  // a duplicate email.
  const [isPreparing, setIsPreparing] = useState(false);
  const isSending = isPreparing || sendOutreach.isPending;

  const displayLocation = location ?? job.location;

  // Terminal stays visible during the run and after it finishes (done/error),
  // so the log remains readable; only "idle" shows the metadata/drafts.
  const showTerminal = phase !== "idle";

  const buttonLabel = isGenerating
    ? "Генерация..."
    : phase === "done"
      ? "Сгенерировать заново"
      : phase === "error"
        ? "Повторить"
        : "Сгенерировать отклик";

  const submitSend = async () => {
    if (isSending) return; // re-entry guard: swallows a double click mid-build

    setIsPreparing(true);
    try {
      // Attach the tailored CV as a generated PDF when one exists. Built from the
      // (possibly edited) CV text, same renderer as the "Скачать PDF" button.
      let attachment_filename: string | undefined;
      let attachment_content_base64: string | undefined;
      if (cv.trim()) {
        try {
          attachment_content_base64 = await cvPdfBase64(cv);
          attachment_filename = cvFileName([
            job.company_name,
            job.job_title,
            "CV",
          ]);
        } catch {
          toast.error("Не удалось приложить PDF резюме");
          return; // finally still resets isPreparing
        }
      }

      // mutateAsync keeps isPreparing held until the request actually settles,
      // leaving no gap between the PDF build and isPending.
      await sendOutreach.mutateAsync({
        to_email: toEmail.trim(),
        subject: subject.trim(),
        body: draft,
        attachment_filename,
        attachment_content_base64,
      });
      setSendOpen(false);
    } catch {
      // Network/API errors are already surfaced via the hook's onError toast.
    } finally {
      setIsPreparing(false);
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Скопировано!");
    } catch {
      toast.error("Не удалось скопировать в буфер обмена");
    }
  };

  const downloadPdf = async () => {
    if (!cv.trim()) return;
    try {
      await downloadCvPdf(cv, [job.company_name, job.job_title, "CV"]);
      toast.success("PDF скачан");
    } catch {
      toast.error("Не удалось создать PDF");
    }
  };

  return (
    <Card className={isMatched ? "w-full" : "w-full max-w-md"}>
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

          {/* Applied marker — stamped once an outreach email goes out. */}
          {job.applied_at ? (
            <Badge variant="secondary">
              Подано · {new Date(job.applied_at).toLocaleDateString()}
            </Badge>
          ) : null}

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
          // Live AI pipeline "terminal": replaces the content while streaming and
          // remains after completion so the log stays readable.
          <StreamTerminal
            logs={streamLogs}
            phase={phase}
            heightClassName={isMatched ? "h-72" : undefined}
          />
        ) : isMatched ? (
          <Tabs defaultValue="cover">
            <TabsList>
              <TabsTrigger value="cover">Cover Letter</TabsTrigger>
              <TabsTrigger value="cv">Tailored CV</TabsTrigger>
            </TabsList>

            <TabsContent value="cover" className="mt-3">
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="min-h-64 text-sm"
                placeholder="Текст сопроводительного письма..."
              />
              <Button
                variant="secondary"
                className="mt-2"
                onClick={() => copy(draft)}
              >
                <Copy /> Скопировать письмо
              </Button>
            </TabsContent>

            <TabsContent value="cv" className="mt-3">
              {job.tailored_cv_draft ? (
                <>
                  <Textarea
                    value={cv}
                    onChange={(e) => setCv(e.target.value)}
                    className="min-h-64 font-mono text-sm"
                  />
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => copy(cv)}>
                      <Copy /> Скопировать резюме
                    </Button>
                    <Button variant="default" onClick={downloadPdf}>
                      <Download /> Скачать PDF
                    </Button>
                  </div>
                </>
              ) : (
                // The tailored CV is produced during the match run, alongside the
                // cover letter. A null draft means this match was made before the
                // CV feature, or the CV step produced no output — "Регенерировать"
                // below re-runs the full pipeline and fills it in.
                <p className="text-muted-foreground py-8 text-center text-sm">
                  ATS-резюме для этого отклика не было сгенерировано. Нажмите
                  «Регенерировать», чтобы запустить подбор заново и получить его.
                </p>
              )}
            </TabsContent>
          </Tabs>
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

      <CardFooter className={isMatched ? "flex flex-wrap gap-2" : undefined}>
        {isMatched ? (
          <>
            <Button asChild variant="outline">
              <a
                href={job.source_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink /> Перейти к вакансии
              </a>
            </Button>
            {/* Send the cover letter to the recruiter via Gmail. Opens a confirm
                dialog (email is irreversible) prefilled with the resolved
                contact. */}
            <Button onClick={() => setSendOpen(true)}>
              <Send /> Отправить рекрутёру
            </Button>
            {/* Re-run the full AI pipeline for this posting. Disabled while a run
                is in flight or no profile is loaded. */}
            <Button
              variant="secondary"
              disabled={isGenerating || profileId === null}
              onClick={() =>
                profileId !== null && startGeneration(job.id, profileId)
              }
            >
              <RefreshCw className={isGenerating ? "animate-spin" : undefined} />
              {isGenerating ? "Регенерация..." : "Регенерировать"}
            </Button>
          </>
        ) : (
          <Button
            className="w-full"
            disabled={isGenerating || profileId === null}
            onClick={() =>
              profileId !== null && startGeneration(job.id, profileId)
            }
          >
            {buttonLabel}
          </Button>
        )}
      </CardFooter>

      {/* Outreach send dialog — review/edit recipient, subject, and body before
          the email goes out. Matched cards only. */}
      {isMatched ? (
        <Dialog open={sendOpen} onOpenChange={setSendOpen}>
          <DialogContent className="max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Отправить письмо рекрутёру</DialogTitle>
              <DialogDescription>
                {job.recruiter_name
                  ? `Контакт: ${job.recruiter_name}`
                  : "Рекрутёр не был найден — укажите адрес вручную."}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="outreach-to">Кому</Label>
                <Input
                  id="outreach-to"
                  type="email"
                  value={toEmail}
                  onChange={(e) => setToEmail(e.target.value)}
                  placeholder="recruiter@company.com"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="outreach-subject">Тема</Label>
                <Input
                  id="outreach-subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="outreach-body">Текст письма</Label>
                <Textarea
                  id="outreach-body"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="min-h-56 text-sm"
                />
              </div>
              <p className="text-muted-foreground text-xs">
                {cv.trim()
                  ? `📎 Вложение: ${cvFileName([job.company_name, job.job_title, "CV"])} (генерируется из текущего резюме)`
                  : "Резюме не сгенерировано — письмо уйдёт без вложения."}
              </p>
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setSendOpen(false)}
                disabled={isSending}
              >
                Отмена
              </Button>
              <Button
                onClick={submitSend}
                disabled={isSending || !toEmail.trim() || !draft.trim()}
              >
                <Send />
                {isSending ? "Отправка..." : "Отправить"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

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
