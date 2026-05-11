import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput, Select } from "@/components/ui/Field";
import { addHolding, updateHolding, type Holding, type HoldingInput } from "@/lib/api";

const ASSET_OPTIONS = [
  { value: "stock", label: "Stock" },
  { value: "etf", label: "ETF" },
  { value: "crypto", label: "Crypto" },
  { value: "bond", label: "Bond" },
  { value: "cash", label: "Cash" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  /** When set, the modal runs in edit mode and prefills from the holding. */
  editing?: Holding | null;
}

const EMPTY: HoldingInput = {
  ticker: "",
  quantity: 0,
  cost_basis: 0,
  asset_class: "stock",
};

export function HoldingFormModal({ open, onClose, onSaved, editing }: Props) {
  const isEdit = Boolean(editing?.id);
  const [form, setForm] = useState<HoldingInput>(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof HoldingInput, string>>>({});

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        ticker: editing.ticker,
        quantity: editing.quantity,
        cost_basis: editing.cost_basis,
        asset_class: editing.asset_class,
      });
    } else {
      setForm(EMPTY);
    }
    setErrors({});
  }, [open, editing]);

  function validate(): boolean {
    const next: typeof errors = {};
    if (!form.ticker.trim()) next.ticker = "Required";
    if (!(form.quantity > 0)) next.quantity = "Must be greater than 0";
    if (form.cost_basis < 0) next.cost_basis = "Cannot be negative";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setSubmitting(true);
    try {
      if (isEdit && editing?.id != null) {
        await updateHolding(editing.id, form);
        toast.success(`${form.ticker.toUpperCase()} updated`);
      } else {
        await addHolding(form);
        toast.success(`${form.ticker.toUpperCase()} added`);
      }
      onSaved();
      onClose();
    } catch (err) {
      toast.error((err as Error).message || "Save failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit holding" : "Add a holding"}
      description={isEdit ? "Update the position details." : "Enter what you own. Prices come from live market data."}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">Cancel</Button>
          <Button onClick={handleSubmit} loading={submitting} type="submit">
            {isEdit ? "Save changes" : "Add holding"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Ticker" hint="e.g. AAPL, BTC-USD, VOO" error={errors.ticker}>
          <TextInput
            autoFocus
            value={form.ticker}
            onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
            placeholder="AAPL"
            spellCheck={false}
            autoComplete="off"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" error={errors.quantity}>
            <TextInput
              inputMode="decimal"
              value={form.quantity || ""}
              onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) || 0 })}
              placeholder="10"
            />
          </Field>
          <Field label="Avg cost / unit" hint="Optional" error={errors.cost_basis}>
            <TextInput
              inputMode="decimal"
              value={form.cost_basis || ""}
              onChange={(e) => setForm({ ...form, cost_basis: Number(e.target.value) || 0 })}
              placeholder="150.50"
            />
          </Field>
        </div>

        <Field label="Asset class">
          <Select
            options={ASSET_OPTIONS}
            value={form.asset_class}
            onChange={(e) => setForm({ ...form, asset_class: e.target.value as HoldingInput["asset_class"] })}
          />
        </Field>

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
