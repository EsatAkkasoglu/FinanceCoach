import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput, Select } from "@/components/ui/Field";
import {
  createTransaction, updateTransaction,
  type Transaction, type TransactionInput, type TxType, type Account,
} from "@/lib/api";

const TYPE_OPTIONS = [
  { value: "expense", label: "Expense" },
  { value: "income", label: "Income" },
  { value: "transfer", label: "Transfer" },
];

// Common categories — these are suggestions, not enforced. Free-text allowed.
export const COMMON_CATEGORIES = [
  "groceries", "dining", "transport", "rent", "utilities", "subscriptions",
  "shopping", "health", "entertainment", "salary", "transfer", "other",
];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  editing?: Transaction | null;
  accounts: Account[];
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const EMPTY: TransactionInput = {
  occurred_on: todayISO(),
  type: "expense",
  amount: 0,
  currency: "TRY",
  category: "uncategorized",
  description: "",
  source: "manual",
  account_id: null,
};

export function TransactionFormModal({ open, onClose, onSaved, editing, accounts }: Props) {
  const isEdit = Boolean(editing);
  const [form, setForm] = useState<TransactionInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        occurred_on: editing.occurred_on,
        type: editing.type,
        amount: editing.amount,
        currency: editing.currency,
        category: editing.category,
        description: editing.description,
        source: editing.source,
        account_id: editing.account_id,
      });
    } else {
      // Pre-select first account for convenience.
      setForm({ ...EMPTY, account_id: accounts[0]?.id ?? null, currency: accounts[0]?.currency ?? "TRY" });
    }
    setErrors({});
  }, [open, editing, accounts]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const err: Record<string, string> = {};
    if (!(form.amount > 0)) err.amount = "Must be greater than 0";
    if (!form.category.trim()) err.category = "Required";
    if (Object.keys(err).length) { setErrors(err); return; }
    setSaving(true);
    try {
      if (isEdit && editing) {
        await updateTransaction(editing.id, form);
        toast.success("Transaction updated");
      } else {
        await createTransaction(form);
        toast.success("Transaction added");
      }
      onSaved();
      onClose();
    } catch (err) {
      toast.error((err as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit transaction" : "Add transaction"}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} loading={saving}>
            {isEdit ? "Save" : "Add"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            <Select
              options={TYPE_OPTIONS}
              value={form.type}
              onChange={(e) => setForm({ ...form, type: e.target.value as TxType })}
            />
          </Field>
          <Field label="Date">
            <TextInput
              type="date"
              value={form.occurred_on}
              onChange={(e) => setForm({ ...form, occurred_on: e.target.value })}
            />
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Field label="Amount" error={errors.amount}>
              <TextInput
                autoFocus
                inputMode="decimal"
                value={form.amount || ""}
                onChange={(e) => setForm({ ...form, amount: Number(e.target.value) || 0 })}
                placeholder="0.00"
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

        <Field label="Category" hint="Type or pick from suggestions." error={errors.category}>
          <input
            list="tx-categories"
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            className="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <datalist id="tx-categories">
            {COMMON_CATEGORIES.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>

        {accounts.length > 0 && (
          <Field label="Account" hint="Linking updates the balance automatically.">
            <Select
              options={[
                { value: "", label: "— none —" },
                ...accounts.map((a) => ({ value: String(a.id), label: `${a.name} (${a.currency})` })),
              ]}
              value={form.account_id == null ? "" : String(form.account_id)}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : null;
                const acc = accounts.find((a) => a.id === id);
                setForm({
                  ...form,
                  account_id: id,
                  currency: acc?.currency ?? form.currency,
                });
              }}
            />
          </Field>
        )}

        <Field label="Description" hint="Optional note.">
          <TextInput
            value={form.description ?? ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Migros run"
          />
        </Field>

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
