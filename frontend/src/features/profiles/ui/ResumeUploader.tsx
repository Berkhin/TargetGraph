import { useRef, useState } from "react";
import { Upload, AlertCircle, CheckCircle } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
          <div className="flex gap-2 rounded-md border border-green-200 bg-green-50 p-3">
            <CheckCircle className="h-5 w-5 flex-shrink-0 text-green-600 mt-0.5" />
            <p className="text-sm text-green-800">
              Профиль успешно создан из резюме &quot;{fileName}&quot;
            </p>
          </div>
        )}

        {isError && (
          <div className="flex gap-2 rounded-md border border-red-200 bg-red-50 p-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-red-600 mt-0.5" />
            <p className="text-sm text-red-800">
              Ошибка при загрузке резюме. Убедитесь, что это валидный PDF файл.
            </p>
          </div>
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
