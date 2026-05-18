import { useTranslation } from "react-i18next";

export function Disclaimer({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <p className={`text-[10px] text-[hsl(var(--text-muted))] ${className}`}>
      {t("disclaimer")}
    </p>
  );
}
