/**
 * Goals — savings/target tracker.
 *
 * Backed by the existing /goals CRUD endpoints. Onboarding seeds at least
 * one goal; this page surfaces it (and any added later) with progress bars,
 * inline current-amount editing, and quick contribute / withdraw actions.
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Target, Calendar, Loader2 } from "lucide-react";

import {
  listGoals,
  createGoal,
  updateGoal,
  deleteGoal,
  type Goal,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";

const ICON_CHOICES = ["🎯", "🏠", "🚗", "✈️", "🎓", "💍", "💼", "🛟", "📈"];

export function Goals() {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Goal | null>(null);
  const [creating, setCreating] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setGoals(await listGoals());
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function handleContribute(goal: Goal, delta: number) {
    const next = Math.max(0, (goal.current_amount ?? 0) + delta);
    try {
      const updated = await updateGoal(goal.id, { current_amount: next });
      setGoals((prev) => prev?.map((g) => (g.id === goal.id ? updated : g)) ?? null);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleDelete(goal: Goal) {
    if (!window.confirm(`Delete "${goal.title}"?`)) return;
    try {
      await deleteGoal(goal.id);
      setGoals((prev) => prev?.filter((g) => g.id !== goal.id) ?? null);
      toast.success("Goal deleted");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Goals</h1>
          <p className="text-sm text-[hsl(var(--text-muted))]">
            Track what you're saving toward. Edit a contribution any time.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> Add goal
        </Button>
      </header>

      {loading ? (
        <div className="card flex h-32 items-center justify-center text-[hsl(var(--text-muted))]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : goals && goals.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {goals.map((g) => (
            <GoalCard
              key={g.id}
              goal={g}
              onEdit={() => setEditing(g)}
              onContribute={(amt) => handleContribute(g, amt)}
              onDelete={() => handleDelete(g)}
            />
          ))}
        </div>
      ) : (
        <div className="card flex flex-col items-center text-center py-12">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent-muted">
            <Target className="h-6 w-6 text-accent" />
          </div>
          <h2 className="text-base font-semibold">No goals yet</h2>
          <p className="mt-1 max-w-md text-sm text-[hsl(var(--text-muted))]">
            Set a target — a down payment, an emergency fund, a trip — and we'll track progress.
          </p>
          <Button className="mt-4" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> Create first goal
          </Button>
        </div>
      )}

      <GoalFormModal
        open={creating || editing != null}
        editing={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSaved={() => { setCreating(false); setEditing(null); void refresh(); }}
      />
    </div>
  );
}

function GoalCard({
  goal, onEdit, onContribute, onDelete,
}: {
  goal: Goal;
  onEdit: () => void;
  onContribute: (delta: number) => void;
  onDelete: () => void;
}) {
  const pct = goal.target_amount > 0
    ? Math.min(100, ((goal.current_amount ?? 0) / goal.target_amount) * 100)
    : 0;
  const remaining = Math.max(0, goal.target_amount - (goal.current_amount ?? 0));
  const daysLeft = useMemo(() => {
    if (!goal.target_date) return null;
    const target = new Date(goal.target_date + "T00:00:00");
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  }, [goal.target_date]);

  return (
    <section className="card">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-muted text-xl leading-none">
            {goal.icon || "🎯"}
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{goal.title}</h2>
            <p className="text-[11px] text-[hsl(var(--text-muted))]">
              {goal.target_date && daysLeft != null && (
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {daysLeft < 0
                    ? `${Math.abs(daysLeft)}d past target`
                    : daysLeft === 0 ? "due today"
                    : `${daysLeft}d to go`}
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          <button onClick={onEdit} className="rounded p-1 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]" aria-label="Edit">
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button onClick={onDelete} className="rounded p-1 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-loss" aria-label="Delete">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      <div className="mt-4">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-semibold tabular-nums">
            {(goal.current_amount ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
          <span className="text-[hsl(var(--text-muted))]">
            / {goal.target_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              pct >= 100 ? "bg-gain" : "bg-accent",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-1 text-[11px] text-[hsl(var(--text-muted))]">
          {pct.toFixed(0)}% reached
          {remaining > 0 && ` · ${remaining.toLocaleString(undefined, { maximumFractionDigits: 0 })} to go`}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {[100, 500, 1000].map((amt) => (
          <button
            key={amt}
            onClick={() => onContribute(amt)}
            className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2.5 py-1 text-xs text-[hsl(var(--text-muted))] transition hover:border-accent hover:text-accent"
          >
            +{amt}
          </button>
        ))}
        <button
          onClick={() => onContribute(-100)}
          className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2.5 py-1 text-xs text-[hsl(var(--text-muted))] transition hover:border-loss hover:text-loss"
        >
          −100
        </button>
      </div>
    </section>
  );
}

interface GoalForm {
  title: string;
  target_amount: number;
  current_amount: number;
  target_date: string;
  icon: string;
}

const EMPTY_FORM: GoalForm = {
  title: "",
  target_amount: 0,
  current_amount: 0,
  target_date: "",
  icon: "🎯",
};

function GoalFormModal({
  open, editing, onClose, onSaved,
}: {
  open: boolean;
  editing: Goal | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<GoalForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        title: editing.title,
        target_amount: editing.target_amount,
        current_amount: editing.current_amount ?? 0,
        target_date: editing.target_date ?? "",
        icon: editing.icon || "🎯",
      });
    } else {
      setForm(EMPTY_FORM);
    }
  }, [open, editing]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !(form.target_amount > 0)) {
      toast.error("Title and a positive target amount are required.");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        title: form.title.trim(),
        target_amount: form.target_amount,
        current_amount: form.current_amount,
        target_date: form.target_date || null,
        icon: form.icon,
      };
      if (editing) {
        await updateGoal(editing.id, payload);
        toast.success("Goal updated");
      } else {
        await createGoal(payload);
        toast.success("Goal created");
      }
      onSaved();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Edit goal" : "New goal"}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">Cancel</Button>
          <Button onClick={handleSubmit} loading={submitting} type="submit">
            {editing ? "Save changes" : "Create"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Title">
          <TextInput
            autoFocus
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Emergency fund"
          />
        </Field>

        <Field label="Icon">
          <div className="flex flex-wrap gap-1.5">
            {ICON_CHOICES.map((emoji) => (
              <button
                key={emoji}
                type="button"
                onClick={() => setForm({ ...form, icon: emoji })}
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-lg border text-lg transition",
                  form.icon === emoji
                    ? "border-accent bg-accent-muted"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] hover:border-[hsl(var(--text-muted))]",
                )}
              >
                {emoji}
              </button>
            ))}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Target amount">
            <TextInput
              inputMode="decimal"
              value={form.target_amount || ""}
              onChange={(e) => setForm({ ...form, target_amount: Number(e.target.value) || 0 })}
              placeholder="10000"
            />
          </Field>
          <Field label="Current amount" hint="Optional">
            <TextInput
              inputMode="decimal"
              value={form.current_amount || ""}
              onChange={(e) => setForm({ ...form, current_amount: Number(e.target.value) || 0 })}
              placeholder="0"
            />
          </Field>
        </div>

        <Field label="Target date" hint="Optional">
          <TextInput
            type="date"
            value={form.target_date}
            onChange={(e) => setForm({ ...form, target_date: e.target.value })}
          />
        </Field>

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
