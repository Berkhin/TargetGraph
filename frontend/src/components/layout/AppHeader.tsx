import { NavLink } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  // `end` so the index route ("/") isn't marked active on every path.
  end?: boolean;
};

const NAV: NavItem[] = [
  { to: "/", label: "Лента вакансий", end: true },
  { to: "/cover-letters", label: "Отклики" },
  { to: "/profile", label: "Настройки профиля" },
];

export function AppHeader() {
  return (
    <header className="border-b">
      <div className="mx-auto flex items-center justify-between px-4 py-3">
        <span className="text-lg font-semibold tracking-tight">TargetGraph</span>
        <nav className="flex gap-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  buttonVariants({
                    variant: isActive ? "default" : "ghost",
                    size: "sm",
                  }),
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
