import { useState } from "react";
import {
  Copy,
  Download,
  ExternalLink,
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
} from "@/components/ui/dialog";
import {
  cvFileName,
  cvPdfBase64,
  downloadCvPdf,
} from "@/features/cover-letters/lib/cvToPdf";
import type { JobRead } from "@/features/jobs-board/api/types";
import { useDeleteJob } from "@/features/jobs-board/hooks/useDeleteJob";
import { useMatchJobStream } from "@/features/jobs-board/hooks/useMatchJobStream";
import { useSendOutreach } from "@/features/jobs-board/hooks/useSendOutreach";
import { StreamTerminal } from "@/features/jobs-board/ui/StreamTerminal";

export type CoverLetterCardProps = {
  job: JobRead;
  // Candidate profile to re-run the pipeline against (required by the match
  // stream). Null while the active profile is still loading or none exists yet,
  // in which case the "Регенерировать" button stays disabled.
  profileId: string | null;
};

// One matched posting with its editable cover letter and ATS-tailored CV. Both
// drafts are local (useState) so the user can polish them before copying; edits
// are intentionally not persisted — this card is a launchpad for applying, not a
// save form.
//
// "Регенерировать" re-runs the SAME full AI pipeline as the jobs board (over the
// match WebSocket via useMatchJobStream), streaming a live terminal. On a MATCHED
// result the hook invalidates the matched-jobs query; CoverLettersPage keys each
// card on `${id}:${updated_at}`, so the card remounts with the freshly generated
// drafts automatically — no local re-sync needed here.
export function CoverLetterCard({ job, profileId }: CoverLetterCardProps) {
  const [draft, setDraft] = useState(job.cover_letter_draft ?? "");
  const [cv, setCv] = useState(job.tailored_cv_draft ?? "");

  const { phase, isGenerating, streamLogs, startGeneration } =
    useMatchJobStream();
  // Terminal stays visible during the run and after it finishes (done/error);
  // "idle" shows the editable drafts.
  const showTerminal = phase !== "idle";

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

  // Delete (soft) with a confirm dialog — clearing a generated card is
  // irreversible from the UI, so the user confirms first.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteJob = useDeleteJob(job.id);

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
    <Card className="w-full">
      <CardHeader>
        <CardTitle>{job.job_title}</CardTitle>
        <CardDescription>{job.company_name}</CardDescription>
        {job.applied_at ? (
          <CardAction>
            <Badge variant="secondary">
              Подано · {new Date(job.applied_at).toLocaleDateString()}
            </Badge>
          </CardAction>
        ) : null}
      </CardHeader>

      <CardContent>
        {showTerminal ? (
          // Live AI pipeline "terminal" while regenerating; sized to roughly
          // match the drafts area it replaces.
          <StreamTerminal
            logs={streamLogs}
            phase={phase}
            heightClassName="h-72"
          />
        ) : (
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
        )}
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2">
        <Button asChild variant="outline">
          <a href={job.source_url} target="_blank" rel="noopener noreferrer">
            <ExternalLink /> Перейти к вакансии
          </a>
        </Button>
        {/* Send the cover letter to the recruiter via Gmail. Opens a confirm
            dialog (email is irreversible) prefilled with the resolved contact. */}
        <Button onClick={() => setSendOpen(true)}>
          <Send /> Отправить рекрутёру
        </Button>
        {/* Re-run the full AI pipeline for this posting (same flow as the jobs
            board). Disabled while a run is in flight or no profile is loaded. */}
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
        {/* Soft-delete this card (marks it DISCARDED). Opens a confirm dialog. */}
        <Button
          variant="destructive"
          disabled={deleteJob.isPending}
          onClick={() => setDeleteOpen(true)}
        >
          <Trash2 /> Удалить
        </Button>
      </CardFooter>

      {/* Outreach send dialog — review/edit recipient, subject, and body before
          the email goes out. */}
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

      {/* Delete confirmation — soft-delete is reversible only in the DB, so
          confirm before removing the card from the board. */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить карточку?</DialogTitle>
            <DialogDescription>
              «{job.job_title} — {job.company_name}» исчезнет из списка откликов.
              Это действие нельзя отменить из интерфейса.
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
