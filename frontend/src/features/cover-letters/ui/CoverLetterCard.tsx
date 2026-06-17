import { useState } from "react";
import { Copy, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { JobRead } from "@/features/jobs-board/api/types";

export type CoverLetterCardProps = {
  job: JobRead;
};

// One matched posting with its editable cover letter and ATS-tailored CV. Both
// drafts are local (useState) so the user can polish them before copying; edits
// are intentionally not persisted — this card is a launchpad for applying, not a
// save form.
export function CoverLetterCard({ job }: CoverLetterCardProps) {
  const [draft, setDraft] = useState(job.cover_letter_draft ?? "");
  const [cv, setCv] = useState(job.tailored_cv_draft ?? "");

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Скопировано!");
    } catch {
      toast.error("Не удалось скопировать в буфер обмена");
    }
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>{job.job_title}</CardTitle>
        <CardDescription>{job.company_name}</CardDescription>
      </CardHeader>

      <CardContent>
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
                <Button
                  variant="secondary"
                  className="mt-2"
                  onClick={() => copy(cv)}
                >
                  <Copy /> Скопировать резюме
                </Button>
              </>
            ) : (
              // The tailored CV is produced during the match run, alongside the
              // cover letter — there is no separate "generate" action here. A
              // null draft means this match was made before the CV feature, or
              // the CV step did not produce output. Re-run the match on the jobs
              // board to generate it.
              <p className="text-muted-foreground py-8 text-center text-sm">
                ATS-резюме для этого отклика не было сгенерировано. Запустите
                подбор для вакансии заново на доске вакансий, чтобы получить его.
              </p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>

      <CardFooter>
        <Button asChild variant="outline">
          <a href={job.source_url} target="_blank" rel="noopener noreferrer">
            <ExternalLink /> Перейти к вакансии
          </a>
        </Button>
      </CardFooter>
    </Card>
  );
}
