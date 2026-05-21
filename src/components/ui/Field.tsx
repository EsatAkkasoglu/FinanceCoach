import { type InputHTMLAttributes, type ReactNode, forwardRef } from "react";
import { cn } from "@/lib/cn";

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}

export function Field({ label, hint, error, children }: FieldProps) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-content-muted">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-loss">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-content-muted">{hint}</span>
      ) : null}
    </label>
  );
}

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function TextInput({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "w-full rounded-lg border border-line bg-surface-raised px-3 py-2 text-sm text-content placeholder:text-content-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent",
          className,
        )}
        {...rest}
      />
    );
  },
);

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  options: { value: string; label: string }[];
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  function Select({ options, className, ...rest }, ref) {
    return (
      <select
        ref={ref}
        className={cn(
          "w-full rounded-lg border border-line bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent",
          className,
        )}
        {...rest}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    );
  },
);
