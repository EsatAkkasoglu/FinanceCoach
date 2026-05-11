import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput, Select } from "@/components/ui/Field";
import { createAccount, updateAccount, type Account, type AccountKind, type AccountInput } from "@/lib/api";

const KIND_OPTIONS: { value: AccountKind; label: string }[] = [
  { value: "checking", label: "Checking" },
  { value: "savings", label: "Savings" },
  { value: "cash", label: "Cash / wallet" },
  { value: "credit_card", label: "Credit card" },
];

const CURRENCIES = ["TRY", "USD", "EUR", "GBP"];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  editing?: Account | null;
}

const EMPTY: AccountInput = {
  name: "",
  kind: "checking",
  balance: 0,
  currency: "TRY",
  institution: "",
};

export function AccountFormModal({ open, onClose, onSaved, editing }: Props) {
  const isEdit = Boolean(editing);
  const [form, setForm] = useState<AccountInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        name: editing.name,
        kind: editing.kind,
        balance: editing.balance,
        currency: editing.currency,
        institution: editing.institution ?? "",
      });
    } else {
      setForm(EMPTY);
    }
    setErrors({});
  }, [open, editing]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const err: Record<string, string> = {};
    if (!form.name.trim()) err.name = "Required";
    if (Object.keys(err).length) { setErrors(err); return; }
    setSaving(true);
    try {
      if (isEdit && editing) {
        await updateAccount(editing.id, form);
        toast.success("Account updated");
      } else {
        await createAccount(form);
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

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit account" : "Add an account"}
      description="Each account tracks its own balance — bank, wallet, or credit card."
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} loading={saving}>
            {isEdit ? "Save" : "Add account"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Name" hint="Whatever helps you recognise it." error={errors.name}>
          <TextInput
            autoFocus
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Ziraat checking"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            <Select
              options={KIND_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as AccountKind })}
            />
          </Field>
          <Field label="Currency">
            <Select
              options={CURRENCIES.map((c) => ({ value: c, label: c }))}
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
            />
          </Field>
        </div>
        <Field
          label={form.kind === "credit_card" ? "Outstanding balance" : "Current balance"}
          hint={form.kind === "credit_card" ? "What you currently owe." : undefined}
        >
          <TextInput
            inputMode="decimal"
            value={form.balance || ""}
            onChange={(e) => setForm({ ...form, balance: Number(e.target.value) || 0 })}
            placeholder="0"
          />
        </Field>
        <Field label="Institution" hint="Optional — bank or card issuer.">
          <TextInput
            value={form.institution ?? ""}
            onChange={(e) => setForm({ ...form, institution: e.target.value })}
            placeholder="Garanti BBVA"
          />
        </Field>
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
