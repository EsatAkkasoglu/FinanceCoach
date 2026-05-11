import { AVATARS, type AvatarId } from "./data";
import { cn } from "@/lib/cn";

interface Props {
  name: string;
  avatar: AvatarId;
  onChange: (patch: { name?: string; avatar?: AvatarId }) => void;
}

export function StepWelcome({ name, avatar, onChange }: Props) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Welcome to FinCoach 👋</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          Your AI finance copilot. Let's get to know each other in under a minute.
        </p>
      </div>

      <label className="block">
        <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
          What should I call you?
        </span>
        <input
          autoFocus
          value={name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="Alex"
          className="mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none focus:border-accent"
        />
      </label>

      <div>
        <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
          Pick your spirit animal
        </span>
        <div className="mt-2 grid grid-cols-4 gap-3">
          {AVATARS.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => onChange({ avatar: a.id })}
              className={cn(
                "flex flex-col items-center gap-1 rounded-lg border p-3 transition",
                avatar === a.id
                  ? "border-accent bg-accent-muted shadow-glow"
                  : "border-[hsl(var(--border))] hover:border-accent"
              )}
              aria-label={a.label}
            >
              <span className="text-3xl leading-none">{a.emoji}</span>
              <span className="text-[10px] text-[hsl(var(--text-muted))]">{a.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
