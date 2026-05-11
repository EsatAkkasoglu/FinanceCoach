import { useRef } from "react";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { AVATARS, type AvatarId } from "./data";
import { cn } from "@/lib/cn";

interface Props {
  name: string;
  avatar: AvatarId;
  onChange: (patch: { name?: string; avatar?: AvatarId }) => void;
}

export function StepWelcome({ name, avatar, onChange }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedMeta = AVATARS.find((a) => a.id === avatar) ?? AVATARS[0];
  const displayName = name.trim() || "You";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="h-4 w-4 text-accent" />
          <span className="text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
            Welcome to FinCoach
          </span>
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">
          Let's set up your profile
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          Takes under a minute — I'll personalize everything for you.
        </p>
      </div>

      {/* Live preview card */}
      <motion.div
        layout
        className="flex items-center gap-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-5 py-4"
      >
        <motion.div
          key={avatar}
          initial={{ scale: 0.7, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 400, damping: 20 }}
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-accent/20 text-3xl leading-none shadow-glow"
        >
          {selectedMeta.emoji}
        </motion.div>
        <div className="min-w-0">
          <motion.p
            key={displayName}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="truncate text-base font-semibold"
          >
            {displayName}
          </motion.p>
          <p className="text-xs text-[hsl(var(--text-muted))]">
            {selectedMeta.label} · FinCoach member
          </p>
        </div>
      </motion.div>

      {/* Name input */}
      <label className="block">
        <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
          What should I call you?
        </span>
        <input
          ref={inputRef}
          autoFocus
          value={name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="Alex"
          maxLength={40}
          className="mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none transition focus:border-accent focus:ring-1 focus:ring-accent/30"
        />
        {name.trim().length > 0 && (
          <span className="mt-1 block text-xs text-gain">
            Nice to meet you, {name.trim()} 👋
          </span>
        )}
      </label>

      {/* Avatar picker */}
      <div>
        <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
          Pick your spirit animal
        </span>
        <div className="mt-3 grid grid-cols-4 gap-2">
          {AVATARS.map((a) => {
            const isSelected = avatar === a.id;
            return (
              <button
                key={a.id}
                type="button"
                onClick={() => onChange({ avatar: a.id })}
                aria-label={a.label}
                aria-pressed={isSelected}
                className={cn(
                  "relative flex flex-col items-center gap-1.5 rounded-xl border py-3 transition-all duration-150",
                  isSelected
                    ? "border-accent bg-accent/10 shadow-glow scale-[1.04]"
                    : "border-[hsl(var(--border))] hover:border-accent/50 hover:bg-[hsl(var(--surface-2))]"
                )}
              >
                <span className="text-3xl leading-none">{a.emoji}</span>
                <span className="text-[10px] text-[hsl(var(--text-muted))]">{a.label}</span>
                {isSelected && (
                  <motion.span
                    layoutId="avatar-ring"
                    className="absolute inset-0 rounded-xl border-2 border-accent"
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
