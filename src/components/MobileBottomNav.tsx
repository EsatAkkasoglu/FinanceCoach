/**
 * MobileBottomNav — fixed bottom tab bar shown only on small screens (md:hidden).
 * Shows the 5 most-used routes as icon+label tabs.
 * Main content gets pb-16 on mobile to avoid overlap.
 */
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LayoutDashboard, Briefcase, Compass, Target, MessageSquare } from "lucide-react";
import { cn } from "@/lib/cn";
import { buildLocalizedPath, getLanguageFromPath, isSupportedLanguage, stripLanguagePrefix } from "@/lib/routing";
import { useConversationStore } from "@/store";

const TABS = [
  { path: "/dashboard", icon: LayoutDashboard, labelKey: "nav.dashboard" as const },
  { path: "/portfolio", icon: Briefcase,       labelKey: "nav.portfolio" as const },
  { path: "/discover",  icon: Compass,         labelKey: "nav.discover"  as const },
  { path: "/goals",     icon: Target,          labelKey: "nav.goals"     as const },
  { path: "/chat",      icon: MessageSquare,   labelKey: null            },
] satisfies { path: string; icon: React.ElementType; labelKey: string | null }[];

interface Props {
  onChatPress: () => void; // new chat or navigate to active conv
}

export function MobileBottomNav({ onChatPress }: Props) {
  const { t, i18n } = useTranslation();

  // Resolve labels with proper static t() calls to satisfy i18n type checker
  const TAB_LABELS: Record<string, string> = {
    "/dashboard": t("nav.dashboard"),
    "/portfolio":  t("nav.portfolio"),
    "/discover":   t("nav.discover"),
    "/goals":      t("nav.goals"),
    "/chat":       "Coach",
  };
  const location = useLocation();
  const navigate = useNavigate();
  const { activeConversationId } = useConversationStore();
  const currentPath = stripLanguagePrefix(location.pathname);
  const lang = getLanguageFromPath(location.pathname) ?? (isSupportedLanguage(i18n.language) ? i18n.language : "en");

  function handleTab(path: string) {
    if (path === "/chat") {
      if (activeConversationId) {
        navigate(buildLocalizedPath(lang, `/chat/${activeConversationId}`));
      } else {
        onChatPress();
      }
      return;
    }
    navigate(buildLocalizedPath(lang, path));
  }

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-30 flex border-t border-line bg-surface/95 backdrop-blur-md md:hidden">
      {TABS.map(({ path, icon: Icon }) => {
        const active = currentPath === path || currentPath.startsWith(`${path}/`);
        return (
          <button
            key={path}
            onClick={() => handleTab(path)}
            className={cn(
              "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] transition-colors",
              active ? "text-accent" : "text-content-muted",
            )}
          >
            <Icon className={cn("h-5 w-5", active && "drop-shadow-[0_0_6px_rgba(31,181,122,0.6)]")} />
            <span className="font-medium">{TAB_LABELS[path] ?? path}</span>
          </button>
        );
      })}
    </nav>
  );
}
