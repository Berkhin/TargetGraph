import { ProfileEditor } from "@/features/profiles/ui/ProfileEditor";

export function ProfilePage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">
          Настройки профиля
        </h1>
        <p className="text-muted-foreground">
          Просмотр и редактирование CV-данных кандидата (Master Profile).
        </p>
      </header>

      <ProfileEditor />
    </main>
  );
}
