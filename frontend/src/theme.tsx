import { useEffect, useState } from "react";

/** Colour theme: dark by default, or light, or following the operating system. The choice is
 *  kept in this browser only (localStorage). */
export type ThemeChoice = "dark" | "light" | "system";

const KEY = "aos-theme";
const ORDER: ThemeChoice[] = ["dark", "light", "system"];
const LABELS: Record<ThemeChoice, string> = { dark: "Dark", light: "Light", system: "System" };
const ICONS: Record<ThemeChoice, string> = { dark: "☾", light: "☀", system: "◐" };

export function storedTheme(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY);
    if (value === "dark" || value === "light" || value === "system") return value;
  } catch {
    // Storage can be unavailable (private modes); the default applies.
  }
  return "dark";
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(choice: ThemeChoice): void {
  const resolved = choice === "system" ? (systemPrefersDark() ? "dark" : "light") : choice;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  useEffect(() => {
    applyTheme(choice);
    if (choice !== "system" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => applyTheme("system");
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, [choice]);
  const update = (next: ThemeChoice) => {
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Not remembered, but still applied for this page.
    }
    setChoice(next);
  };
  return [choice, update];
}

/** Cycles dark → light → system. */
export function ThemeToggle() {
  const [choice, setChoice] = useTheme();
  const next = ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length] ?? "dark";
  return (
    <button
      type="button"
      className="btn btn-ghost theme-toggle"
      onClick={() => setChoice(next)}
      aria-label={`Colour theme: ${LABELS[choice]}. Switch to ${LABELS[next]}`}
      title={`Colour theme: ${LABELS[choice]}`}
    >
      <span aria-hidden="true">{ICONS[choice]}</span>
    </button>
  );
}
