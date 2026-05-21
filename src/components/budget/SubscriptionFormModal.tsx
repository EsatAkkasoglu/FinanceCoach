import { useEffect, useState, type FormEvent } from "react";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput, Select } from "@/components/ui/Field";
import {
  createSubscription, updateSubscription,
  type Subscription, type SubscriptionInput, type SubCycle, type SubDirection,
} from "@/lib/api";
import { cn } from "@/lib/cn";

const CYCLE_OPTIONS: { value: SubCycle; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "yearly", label: "Yearly" },
];

// Quick-pick presets — tap one and the form's filled in. Amounts are placeholders;
// the user always confirms before save.
const EXPENSE_PRESETS = [
  { name: "Netflix",    amount: 149.99, currency: "TRY", category: "streaming",     icon: "🎬" },
  { name: "Spotify",    amount: 79.99,  currency: "TRY", category: "streaming",     icon: "🎵" },
  { name: "YouTube Premium", amount: 89.99, currency: "TRY", category: "streaming", icon: "▶️" },
  { name: "Disney+",    amount: 79.99,  currency: "TRY", category: "streaming",     icon: "✨" },
  { name: "ChatGPT Plus", amount: 20,   currency: "USD", category: "software",      icon: "🤖" },
  { name: "Apple iCloud", amount: 19.99, currency: "TRY", category: "software",     icon: "☁️" },
  { name: "Adobe CC",   amount: 59.99,  currency: "USD", category: "software",      icon: "🅰️" },
  { name: "Gym",        amount: 600,    currency: "TRY", category: "fitness",       icon: "💪" },
];

const INCOME_PRESETS = [
  { name: "Salary",     amount: 0, currency: "TRY", category: "salary",     icon: "💼" },
  { name: "Freelance",  amount: 0, currency: "USD", category: "freelance",  icon: "🧑‍💻" },
  { name: "Rental",     amount: 0, currency: "TRY", category: "rental",     icon: "🏠" },
  { name: "Dividends",  amount: 0, currency: "USD", category: "investments",icon: "📈" },
  { name: "Side gig",   amount: 0, currency: "TRY", category: "side",       icon: "🛠️" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  editing?: Subscription | null;
  /** Initial direction when creating. Defaults to "expense". */
  defaultDirection?: SubDirection;
  /** Optional prefill for "mark transaction as recurring" flow. */
  prefill?: Partial<SubscriptionInput> | null;
}

function defaultNextCharge(): string {
  const d = new Date();
  d.setMonth(d.getMonth() + 1);
  return d.toISOString().slice(0, 10);
}

function emptyForm(direction: SubDirection): SubscriptionInput {
  return {
    name: "",
    amount: 0,
    currency: "TRY",
    cycle: "monthly",
    direction,
    next_charge_on: defaultNextCharge(),
    category: direction === "income" ? "salary" : "subscriptions",
    icon: direction === "income" ? "💼" : "💳",
  };
}

export function SubscriptionFormModal({
  open, onClose, onSaved, editing, defaultDirection = "expense", prefill,
}: Props) {
  const isEdit = Boolean(editing);
  const [form, setForm] = useState<SubscriptionInput>(() => emptyForm(defaultDirection));
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        name: editing.name,
        amount: editing.amount,
        currency: editing.currency,
        cycle: editing.cycle,
        direction: editing.direction,
        next_charge_on: editing.next_charge_on ?? defaultNextCharge(),
        category: editing.category,
        icon: editing.icon ?? (editing.direction === "income" ? "💼" : "💳"),
      });
    } else {
      setForm({ ...emptyForm(defaultDirection), ...(prefill ?? {}) });
    }
    setErrors({});
  }, [open, editing, defaultDirection, prefill]);

  const direction: SubDirection = form.direction ?? defaultDirection;
  const presets = direction === "income" ? INCOME_PRESETS : EXPENSE_PRESETS;

  function applyPreset(p: typeof EXPENSE_PRESETS[number]) {
    setForm((f) => ({
      ...f,
      name: p.name,
      amount: p.amount || f.amount,  // keep typed amount if preset is 0
      currency: p.currency,
      category: p.category,
      icon: p.icon,
    }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const err: Record<string, string> = {};
    if (!form.name.trim()) err.name = "Required";
    if (!(form.amount > 0)) err.amount = "Must be greater than 0";
    if (Object.keys(err).length) { setErrors(err); return; }
    setSaving(true);
    try {
      if (isEdit && editing) {
        await updateSubscription(editing.id, form);
        toast.success("Subscription updated");
      } else {
        await createSubscription(form);
        toast.success(`${form.name} added`);
      }
      onSaved();
      onClose();
    } catch (err) {
      toast.error((err as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const title = isEdit
    ? `Edit ${direction === "income" ? "income source" : "subscription"}`
    : direction === "income" ? "Add recurring income" : "Add subscription";
  const description = direction === "income"
    ? "Salary, freelance gigs, rent — anything that lands in your account on a schedule."
    : "Track recurring charges so nothing surprises you.";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} loading={saving}>
            {isEdit ? "Save" : direction === "income" ? "Add income source" : "Add subscription"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Direction toggle (only when creating) */}
        {!isEdit && (
          <div className="flex gap-2">
            <DirectionToggle
              active={direction === "expense"}
              onClick={() => setForm({ ...form, direction: "expense", icon: "💳", category: "subscriptions" })}
              icon={<ArrowUpRight className="h-3.5 w-3.5" />}
              label="Outgoing"
              hint="Subscription / bill"
            />
            <DirectionToggle
              active={direction === "income"}
              onClick={() => setForm({ ...form, direction: "income", icon: "💼", category: "salary" })}
              icon={<ArrowDownLeft className="h-3.5 w-3.5" />}
              label="Incoming"
              hint="Salary / rental / dividends"
            />
          </div>
        )}

        {!isEdit && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
              Quick add
            </p>
            <div className="flex flex-wrap gap-1.5">
              {presets.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  onClick={() => applyPreset(p)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-full border border-line bg-surface-raised px-2.5 py-1 text-xs transition",
                    "hover:border-accent hover:bg-accent-muted",
                  )}
                >
                  <span>{p.icon}</span>
                  <span>{p.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-[80px_1fr] gap-3">
          <Field label="Icon">
            <TextInput
              value={form.icon ?? ""}
              maxLength={4}
              onChange={(e) => setForm({ ...form, icon: e.target.value })}
              className="text-center text-xl"
            />
          </Field>
          <Field label="Name" error={errors.name}>
            <TextInput
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Netflix"
            />
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Field label="Amount" error={errors.amount}>
              <TextInput
                inputMode="decimal"
                value={form.amount || ""}
                onChange={(e) => setForm({ ...form, amount: Number(e.target.value) || 0 })}
                placeholder="149.99"
              />
            </Field>
          </div>
          <Field label="Currency">
            <Select
              options={["TRY", "USD", "EUR", "GBP"].map((c) => ({ value: c, label: c }))}
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
            />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Billing cycle">
            <Select
              options={CYCLE_OPTIONS}
              value={form.cycle}
              onChange={(e) => setForm({ ...form, cycle: e.target.value as SubCycle })}
            />
          </Field>
          <Field label={direction === "income" ? "Next payment" : "Next charge"}>
            <TextInput
              type="date"
              value={form.next_charge_on ?? ""}
              onChange={(e) => setForm({ ...form, next_charge_on: e.target.value || null })}
            />
          </Field>
        </div>

        <Field label="Category" hint="e.g. streaming, software, fitness">
          <TextInput
            value={form.category ?? ""}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
          />
        </Field>

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}

function DirectionToggle({
  active, onClick, icon, label, hint,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex-1 rounded-lg border px-3 py-2.5 text-left transition",
        active
          ? "border-accent bg-accent-muted"
          : "border-line bg-surface-raised hover:border-content-muted",
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className={cn(active ? "text-accent" : "text-content-muted")}>{icon}</span>
        <span className={cn("text-sm font-medium", active ? "text-accent" : "")}>{label}</span>
      </div>
      <p className="mt-0.5 text-[11px] text-content-muted">{hint}</p>
    </button>
  );
}
