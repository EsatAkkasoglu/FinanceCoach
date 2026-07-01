/**
 * PaymentBadges — the accepted-card + iyzico marks required by the payment
 * provider's merchant review. Shown on the pricing page and near checkout so
 * Visa / Mastercard / "iyzico ile Öde" logos are visible before payment.
 *
 * Logos are self-contained white chips (SVGs in /public/payments), so they read
 * correctly on both light and dark surfaces. Static, no motion.
 */
import { useTranslation } from "react-i18next";
import { Lock } from "lucide-react";

import { cn } from "@/lib/cn";

const BADGES = [
  { src: "/payments/visa.svg", alt: "Visa", w: "w-12" },
  { src: "/payments/mastercard.svg", alt: "Mastercard", w: "w-12" },
  { src: "/payments/iyzico.svg", alt: "iyzico ile Öde", w: "w-[104px]" },
] as const;

export function PaymentBadges({ className }: { className?: string }) {
  const { t } = useTranslation("billing");
  return (
    <div className={cn("flex flex-col items-center gap-3", className)}>
      <div className="flex flex-wrap items-center justify-center gap-2.5">
        {BADGES.map((b) => (
          <img
            key={b.alt}
            src={b.src}
            alt={b.alt}
            loading="lazy"
            className={cn("h-8 rounded-md shadow-sm", b.w)}
          />
        ))}
      </div>
      <p className="flex items-center gap-1.5 text-caption text-content-muted">
        <Lock className="h-3.5 w-3.5" aria-hidden="true" />
        {t("payments.secure")}
      </p>
    </div>
  );
}
