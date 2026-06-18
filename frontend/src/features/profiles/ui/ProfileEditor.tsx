import { useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { isAxiosError } from "axios";
import { Plus, Trash2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useActiveProfile } from "@/features/profiles/hooks/useActiveProfile";
import { useUpdateProfile } from "@/features/profiles/hooks/useUpdateProfile";
import type { ProfileRead, ProfileUpdate } from "@/contracts/profile";
import { getApiErrorMessage } from "@/shared/api/errors";

// Form mirror of the profile, flattened into editable primitives:
//  - target_titles: one input per title
//  - preferences: editable key/value rows (rendered back into an object)
//  - skills: a category + a comma-separated list of skills
//  - experiences: structured fields, highlights as one bullet per line
type FormValues = {
  candidate_name: string;
  target_titles: { value: string }[];
  preferences: { key: string; value: string }[];
  skills: { category: string; skills: string }[];
  experiences: {
    company: string;
    role: string;
    highlights: string;
    start_date: string;
    end_date: string;
  }[];
};

// Split a comma- or newline-separated string into a trimmed, non-empty list.
function splitList(raw: string, separator: "," | "\n"): string[] {
  return raw
    .split(separator)
    .map((item) => item.trim())
    .filter(Boolean);
}

function toFormValues(profile: ProfileRead): FormValues {
  return {
    candidate_name: profile.candidate_name,
    target_titles: profile.target_titles.map((value) => ({ value })),
    preferences: Object.entries(profile.preferences).map(([key, value]) => ({
      key,
      // Render non-string preference values as JSON so they survive a round-trip.
      value: typeof value === "string" ? value : JSON.stringify(value),
    })),
    skills: profile.skills.map((s) => ({
      category: s.category,
      skills: s.skills.join(", "),
    })),
    experiences: profile.experiences.map((e) => ({
      company: e.company,
      role: e.role,
      highlights: e.highlights.join("\n"),
      start_date: e.start_date,
      end_date: e.end_date ?? "",
    })),
  };
}

function toPayload(values: FormValues): ProfileUpdate {
  const preferences: Record<string, unknown> = {};
  for (const { key, value } of values.preferences) {
    const trimmedKey = key.trim();
    if (trimmedKey) preferences[trimmedKey] = value;
  }

  return {
    candidate_name: values.candidate_name.trim(),
    target_titles: values.target_titles
      .map((t) => t.value.trim())
      .filter(Boolean),
    preferences,
    skills: values.skills
      .filter((s) => s.category.trim())
      .map((s) => ({
        category: s.category.trim(),
        skills: splitList(s.skills, ","),
      })),
    experiences: values.experiences
      .filter((e) => e.company.trim() && e.role.trim())
      .map((e) => ({
        company: e.company.trim(),
        role: e.role.trim(),
        highlights: splitList(e.highlights, "\n"),
        start_date: e.start_date,
        end_date: e.end_date.trim() || null,
      })),
  };
}

export function ProfileEditor() {
  const { data: profile, isPending, isError, error } = useActiveProfile();
  const updateProfile = useUpdateProfile();

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      candidate_name: "",
      target_titles: [],
      preferences: [],
      skills: [],
      experiences: [],
    },
  });

  const titles = useFieldArray({ control, name: "target_titles" });
  const prefs = useFieldArray({ control, name: "preferences" });
  const skills = useFieldArray({ control, name: "skills" });
  const experiences = useFieldArray({ control, name: "experiences" });

  // Hydrate the form once the profile arrives (and on subsequent refetches).
  useEffect(() => {
    if (profile) reset(toFormValues(profile));
  }, [profile, reset]);

  if (isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError) {
    const status = isAxiosError(error) ? error.response?.status : undefined;
    if (status === 404) {
      return (
        <p className="text-muted-foreground">
          Профиль ещё не создан. Засидите его на бэкенде (seed_profile.py).
        </p>
      );
    }
    return (
      <p className="text-destructive">
        Не удалось загрузить профиль: {getApiErrorMessage(error)}
      </p>
    );
  }

  const onSubmit = (values: FormValues) => {
    updateProfile.mutate({ id: profile.id, data: toPayload(values) });
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
      {/* Basics ----------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Основное</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="candidate_name">Имя кандидата</Label>
            <Input
              id="candidate_name"
              aria-invalid={errors.candidate_name ? true : undefined}
              {...register("candidate_name", { required: "Имя обязательно" })}
            />
            {errors.candidate_name ? (
              <p className="text-destructive text-sm">
                {errors.candidate_name.message}
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* Target titles ---------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Желаемые роли</CardTitle>
          <CardDescription>
            Должности, на которые нацелен поиск вакансий.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {titles.fields.length === 0 ? (
            <p className="text-muted-foreground text-sm">Пока пусто.</p>
          ) : null}
          {titles.fields.map((field, index) => (
            <div key={field.id} className="flex gap-2">
              <Input
                placeholder="Напр.: Senior Backend Engineer"
                {...register(`target_titles.${index}.value` as const)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => titles.remove(index)}
                aria-label="Удалить роль"
              >
                <Trash2 />
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => titles.append({ value: "" })}
          >
            <Plus /> Добавить роль
          </Button>
        </CardContent>
      </Card>

      {/* Preferences ------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle>Предпочтения</CardTitle>
          <CardDescription>
            Произвольные пары «ключ — значение» (локация, email, формат работы…).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {prefs.fields.length === 0 ? (
            <p className="text-muted-foreground text-sm">Пока пусто.</p>
          ) : null}
          {prefs.fields.map((field, index) => (
            <div key={field.id} className="flex gap-2">
              <Input
                className="max-w-[12rem]"
                placeholder="ключ"
                {...register(`preferences.${index}.key` as const)}
              />
              <Input
                placeholder="значение"
                {...register(`preferences.${index}.value` as const)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => prefs.remove(index)}
                aria-label="Удалить предпочтение"
              >
                <Trash2 />
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => prefs.append({ key: "", value: "" })}
          >
            <Plus /> Добавить пару
          </Button>
        </CardContent>
      </Card>

      {/* Skills ----------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Навыки</CardTitle>
          <CardDescription>
            Категория и список навыков через запятую.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {skills.fields.length === 0 ? (
            <p className="text-muted-foreground text-sm">Пока пусто.</p>
          ) : null}
          {skills.fields.map((field, index) => (
            <div
              key={field.id}
              className="space-y-2 rounded-md border p-3"
            >
              <div className="flex items-center gap-2">
                <Input
                  className="max-w-[14rem]"
                  placeholder="Категория (напр.: Backend)"
                  {...register(`skills.${index}.category` as const)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="ml-auto"
                  onClick={() => skills.remove(index)}
                  aria-label="Удалить категорию навыков"
                >
                  <Trash2 />
                </Button>
              </div>
              <Input
                placeholder="Python, FastAPI, PostgreSQL"
                {...register(`skills.${index}.skills` as const)}
              />
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => skills.append({ category: "", skills: "" })}
          >
            <Plus /> Добавить категорию
          </Button>
        </CardContent>
      </Card>

      {/* Experiences ------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle>Опыт работы</CardTitle>
          <CardDescription>
            Достижения — по одному в строке.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {experiences.fields.length === 0 ? (
            <p className="text-muted-foreground text-sm">Пока пусто.</p>
          ) : null}
          {experiences.fields.map((field, index) => (
            <div
              key={field.id}
              className="space-y-3 rounded-md border p-3"
            >
              <div className="flex items-center gap-2">
                <Input
                  placeholder="Компания"
                  {...register(`experiences.${index}.company` as const)}
                />
                <Input
                  placeholder="Должность"
                  {...register(`experiences.${index}.role` as const)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => experiences.remove(index)}
                  aria-label="Удалить опыт"
                >
                  <Trash2 />
                </Button>
              </div>
              <div className="flex flex-wrap gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Начало</Label>
                  <Input
                    type="date"
                    {...register(`experiences.${index}.start_date` as const)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">
                    Окончание{" "}
                    <span className="text-muted-foreground">(пусто = по н.в.)</span>
                  </Label>
                  <Input
                    type="date"
                    {...register(`experiences.${index}.end_date` as const)}
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Достижения (по одному в строке)</Label>
                <Textarea
                  className="min-h-20"
                  placeholder={"Снизил latency на 40%\nВнедрил CI/CD"}
                  {...register(`experiences.${index}.highlights` as const)}
                />
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              experiences.append({
                company: "",
                role: "",
                highlights: "",
                start_date: "",
                end_date: "",
              })
            }
          >
            <Plus /> Добавить место работы
          </Button>
        </CardContent>
      </Card>

      <CardFooter className="px-0">
        <Button type="submit" disabled={updateProfile.isPending}>
          {updateProfile.isPending ? "Сохранение..." : "Сохранить профиль"}
        </Button>
      </CardFooter>
    </form>
  );
}
