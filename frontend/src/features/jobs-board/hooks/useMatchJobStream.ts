import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { jobsKeys } from "@/features/jobs-board/api/queryKeys";

// Lifecycle of one streaming run. The terminal log stays visible in every
// non-idle phase, so a finished run keeps its history on screen.
export type StreamPhase = "idle" | "streaming" | "done" | "error";

// Frames emitted by the backend streaming pipeline
// (see run_pipeline_stream in app/services/orchestrator.py). One JSON object
// per WebSocket message, discriminated by `step`.
type StreamFrame =
  | { step: "init"; message: string }
  | {
      step:
        | "extract_requirements"
        | "generate_cover_letter"
        | "generate_tailored_cv"
        | "reviewer";
      message: string;
    }
  | { step: "match_profile"; score: number | null; reason: string | null }
  | {
      step: "find_recruiter_contact";
      recruiter_name: string | null;
      recruiter_email: string | null;
    }
  | {
      step: "done";
      status: "MATCHED" | "REJECTED_BY_AI";
      score: number;
      reason: string;
      cover_letter_draft: string | null;
      tailored_cv_draft: string | null;
    }
  | { step: "error"; message: string };

// Derive the ws(s):// endpoint from the REST base URL. The WebSocket route
// lives at /jobs/{id}/ws-match?profile_id=... on the same versioned API root
// (see app/api/v1/jobs.py).
function buildStreamUrl(jobId: string, profileId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
  // Absolute override (e.g. http://host:8000/api/v1): just swap the scheme.
  // Relative default (/api/v1): WebSocket needs an absolute URL, so borrow the
  // current page's scheme + host so the handshake goes through the same proxy.
  const wsBase = /^https?:/.test(base)
    ? base.replace(/^http/, "ws")
    : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${
        window.location.host
      }${base}`;
  return `${wsBase}/jobs/${jobId}/ws-match?profile_id=${profileId}`;
}

// Human-readable log line per stage. Node steps arrive with a generic server
// message ("Шаг 'x' завершён"), so we render our own copy for a nicer terminal.
function frameToLog(frame: StreamFrame): string | null {
  switch (frame.step) {
    case "init":
      return "Данные загружены";
    case "extract_requirements":
      return "Анализ требований...";
    case "match_profile":
      return `Оценка соответствия: ${frame.score ?? "—"}%${
        frame.reason ? ` — ${frame.reason}` : ""
      }`;
    case "find_recruiter_contact":
      return frame.recruiter_name
        ? `Контакт найден: ${frame.recruiter_name}${
            frame.recruiter_email ? ` <${frame.recruiter_email}>` : ""
          }`
        : "Контакт рекрутёра не найден — обращение к Hiring Team";
    case "generate_cover_letter":
      return "Генерация сопроводительного письма...";
    case "generate_tailored_cv":
      return "Генерация ATS-резюме...";
    case "reviewer":
      return "Проверка черновика...";
    case "done":
      return frame.status === "MATCHED"
        ? `Готово: совпадение ${frame.score}%`
        : `Готово: вакансия отклонена (${frame.score}%)`;
    case "error":
      return `Ошибка: ${frame.message}`;
    default:
      return null;
  }
}

// Drives the AI matching pipeline over a WebSocket, exposing the live progress
// log so the UI can render a streaming "terminal" instead of a single spinner.
// The log is retained after completion (phase "done"/"error") so the user can
// read what happened; it only resets on the next run.
export function useMatchJobStream() {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<StreamPhase>("idle");
  const [streamLogs, setStreamLogs] = useState<string[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  // Marks that a terminal frame (done/error) was handled, so the later onclose
  // doesn't report a spurious "connection dropped".
  const terminalRef = useRef(false);

  const closeSocket = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  // Tear down a still-open socket if the component unmounts mid-stream.
  useEffect(() => closeSocket, [closeSocket]);

  const startGeneration = useCallback(
    (jobId: string, profileId: string) => {
      // Ignore re-entry while a stream is already running.
      if (socketRef.current) return;

      setStreamLogs([]);
      setPhase("streaming");
      terminalRef.current = false;

      const socket = new WebSocket(buildStreamUrl(jobId, profileId));
      socketRef.current = socket;

      socket.onmessage = (event) => {
        let frame: StreamFrame;
        try {
          frame = JSON.parse(event.data as string) as StreamFrame;
        } catch {
          return; // ignore anything that isn't a JSON frame
        }

        const line = frameToLog(frame);
        if (line) setStreamLogs((prev) => [...prev, line]);

        if (frame.step === "done") {
          terminalRef.current = true;
          toast.success(
            frame.status === "MATCHED"
              ? `Отклик готов (совпадение ${frame.score}%)`
              : "Вакансия отклонена ИИ",
          );
          // A run changes the posting's status, so refresh the board: the job
          // leaves the NEW list and, on a match, joins the MATCHED list. The
          // card is keyed on updated_at, so it remounts into the right feed
          // section (NEW → «Готовые к отправке») with the freshly generated
          // drafts. The completed terminal log is dropped on that remount, but
          // the success toast already reported the outcome.
          setPhase("done");
          closeSocket();
          void queryClient.invalidateQueries({ queryKey: jobsKeys.new() });
          if (frame.status === "MATCHED") {
            void queryClient.invalidateQueries({ queryKey: jobsKeys.matched() });
          }
        } else if (frame.step === "error") {
          terminalRef.current = true;
          toast.error("Не удалось сгенерировать отклик", {
            description: frame.message,
          });
          setPhase("error");
          closeSocket();
        }
      };

      socket.onerror = () => {
        // Browsers fire onerror then onclose; the reset happens in onclose.
        toast.error("Ошибка соединения с сервером");
      };

      socket.onclose = () => {
        socketRef.current = null;
        if (!terminalRef.current) {
          // Closed before a final frame — surface it but keep the log.
          setStreamLogs((prev) => [...prev, "Соединение прервано"]);
          setPhase("error");
        }
      };
    },
    [closeSocket, queryClient],
  );

  return {
    phase,
    isGenerating: phase === "streaming",
    streamLogs,
    startGeneration,
  };
}
