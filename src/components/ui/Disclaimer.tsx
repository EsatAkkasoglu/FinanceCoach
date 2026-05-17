export function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <p className={`text-[10px] text-[hsl(var(--text-muted))] ${className}`}>
      AI-generated suggestions, not financial advice. Consult a licensed advisor.
    </p>
  );
}
