import { useRef, useState } from "react";
import { Upload, AlertCircle, CheckCircle } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useUploadResume } from "@/features/profiles/hooks/useUploadResume";

export function ResumeUploader() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const uploadMutation = useUploadResume();

  const handleFileSelect = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      alert("Пожалуйста, выберите PDF файл");
      return;
    }

    setFileName(file.name);
    await uploadMutation.mutateAsync(file);
  };

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  const isLoading = uploadMutation.isPending;
  const isSuccess = uploadMutation.isSuccess;
  const isError = uploadMutation.isError;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Загрузить резюме</CardTitle>
        <CardDescription>
          Загрузите PDF файл с вашим резюме. LLM автоматически распарсит его и
          создаст профиль
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isSuccess && (
          <Alert className="border-green-200 bg-green-50">
            <CheckCircle className="h-4 w-4 text-green-600" />
            <AlertDescription className="text-green-800">
              Профиль успешно создан из резюме &quot;{fileName}&quot;
            </AlertDescription>
          </Alert>
        )}

        {isError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Ошибка при загрузке резюме. Убедитесь, что это валидный PDF файл.
            </AlertDescription>
          </Alert>
        )}

        <div
          className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors ${
            isLoading
              ? "border-gray-300 bg-gray-50"
              : "border-gray-300 hover:border-blue-400 hover:bg-blue-50 cursor-pointer"
          }`}
          onClick={handleClick}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              handleClick();
            }
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            onChange={handleFileSelect}
            disabled={isLoading}
            className="hidden"
            aria-label="Upload resume PDF"
          />

          {isLoading ? (
            <>
              <div className="h-12 w-12 animate-spin rounded-full border-4 border-gray-300 border-t-blue-500" />
              <p className="mt-3 text-sm font-medium text-gray-600">
                Загрузка и парсинг резюме...
              </p>
            </>
          ) : (
            <>
              <Upload className="h-12 w-12 text-gray-400" />
              <p className="mt-3 text-sm font-medium text-gray-700">
                Нажмите чтобы выбрать PDF файл
              </p>
              <p className="mt-1 text-xs text-gray-500">
                или перетащите файл сюда
              </p>
            </>
          )}
        </div>

        <p className="text-xs text-gray-500 text-center">
          Максимальный размер: не ограничен. Поддерживаемый формат: PDF
        </p>
      </CardContent>
    </Card>
  );
}
