/**
 * Sidebar — collapsible navigation rail.
 *
 * Changes from previous version:
 * - `collapsed` + `onToggleCollapse` lifted to App.tsx (shared state for main content sync)
 * - Removed internal localStorage management (App.tsx handles it)
 * - Real ⌘K / Ctrl+K global shortcut: expands sidebar if collapsed, then focuses search
 * - Removed `style={{ minWidth }}` — only `animate={{ width }}` drives sizing for smooth flex sync
 * - `effectiveCollapsed = mobileOpen ? false : collapsed` so mobile overlay always shows full panel
 * - Proper nav label lookup (no `t as Function` cast)
 * - Removed invalid `w-60!` Tailwind hack
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  MessageSquare, LayoutDashboard, Briefcase, Wallet, Target, FileText,
  Settings as SettingsIcon, Coins, Compass, Search, Brain,
  Plus, Trash2, Pencil, Check, X, LogOut, ChevronDown, ChevronRight,
  ChevronLeft, Zap,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { isNavEnabled } from "@/lib/features";
import { buildLocalizedPath, getLanguageFromPath, isSupportedLanguage, stripLanguagePrefix } from "@/lib/routing";
import {
  listConversations, createConversation, deleteConversation, updateConversationTitle,
  logout as apiLogout, searchMemory,
  type Conversation, type MemoryHit,
} from "@/lib/api";
import { useAuthStore, useConversationStore, useChatStore, useUserStore } from "@/store";
import { AVATARS } from "@/components/onboarding/data";

// ── Nav structure ─────────────────────────────────────────────────────────────

type NavItem = { path: string; key: string; icon: React.ElementType };

const NAV_SECTIONS: { label: string | null; items: NavItem[] }[] = [
  {
    label: null,
    items: [
      { path: "/chat",      key: "coach",     icon: MessageSquare   },
      { path: "/dashboard", key: "dashboard", icon: LayoutDashboard },
    ],
  },
  {
    label: "Finance",
    items: [
      { path: "/portfolio", key: "portfolio", icon: Briefcase },
      { path: "/budget",    key: "budget",    icon: Wallet    },
      { path: "/funds",     key: "funds",     icon: Coins     },
      { path: "/goals",     key: "goals",     icon: Target    },
    ],
  },
  {
    label: "Research",
    items: [
      { path: "/discover",  key: "discover",  icon: Compass  },
      { path: "/documents", key: "documents", icon: FileText },
    ],
  },
];

// ── Brand SVG ─────────────────────────────────────────────────────────────────

function BrandMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <g stroke="#FFFFFF" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 50 L20 16 L42 16 L52 6" />
        <path d="M46 6 L52 6 L52 12" />
        <path d="M20 32 L36 32" />
      </g>
    </svg>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

interface Props {
  healthy: boolean | null;
  onSelectConversation: (conv: Conversation) => void;
  activeConvId: string | null;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  /** Collapse state managed by App.tsx so main content can sync its margin */
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({
  healthy, onSelectConversation, activeConvId,
  mobileOpen = false, onMobileClose,
  collapsed, onToggleCollapse,
}: Props) {
  const { t, i18n } = useTranslation();
  const { t: tChat } = useTranslation("chat");
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = stripLanguagePrefix(location.pathname);
  const currentLanguage = getLanguageFromPath(location.pathname) ?? (isSupportedLanguage(i18n.language) ? i18n.language : "en");
  const onChatRoute = currentPath.startsWith("/chat");

  const { conversations, setConversations, addConversation, removeConversation, updateTitle } = useConversationStore();
  const resetConv = useChatStore((s) => s.resetConv);
  const { avatar, name } = useUserStore();
  const authUser = useAuthStore((s) => s.user);
  const setAuthUser = useAuthStore((s) => s.setUser);

  // Mobile overlay always shows full sidebar regardless of desktop collapsed state
  const effectiveCollapsed = mobileOpen ? false : collapsed;

  const [creating, setCreating] = useState(false);
  const [recentOpen, setRecentOpen] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<MemoryHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileWrapRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // ── Proper i18n nav label lookup (no cast needed) ──────────────────────────
  const navLabel = (key: string): string => {
    const labels: Record<string, string> = {
      coach:     t("nav.coach"),
      dashboard: t("nav.dashboard"),
      portfolio: t("nav.portfolio"),
      budget:    t("nav.budget"),
      funds:     t("nav.funds"),
      discover:  t("nav.discover"),
      goals:     t("nav.goals"),
      documents: t("nav.documents"),
      settings:  t("nav.settings"),
    };
    return labels[key] ?? key;
  };

  // ── Global ⌘K / Ctrl+K shortcut ───────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (collapsed && !mobileOpen) {
          // Expand first, then focus after spring settles
          onToggleCollapse();
          setTimeout(() => {
            searchRef.current?.focus();
            searchRef.current?.select();
          }, 380);
        } else {
          searchRef.current?.focus();
          searchRef.current?.select();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [collapsed, mobileOpen, onToggleCollapse]);

  async function handleLogout() { await apiLogout(); setAuthUser(null); }

  // Debounced semantic search
  useEffect(() => {
    const q = search.trim();
    if (q.length < 2) { setSearchResults(null); return; }
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try { setSearchResults(await searchMemory(q, 5)); }
      catch { setSearchResults([]); }
      finally { setSearching(false); }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  // Close profile menu on outside click
  useEffect(() => {
    if (!profileOpen) return;
    function onDoc(e: MouseEvent) {
      if (!profileWrapRef.current?.contains(e.target as Node)) setProfileOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [profileOpen]);

  const avatarMeta = AVATARS.find((a) => a.id === avatar) ?? AVATARS[0];

  useEffect(() => {
    listConversations()
      .then((all) => {
        setConversations(all.filter((c) => c.title !== null));
        all.filter((c) => c.title === null).forEach((c) => deleteConversation(c.id).catch(() => {}));
      })
      .catch(() => {});
  }, [setConversations]);

  async function pruneEmptyActive() {
    if (!activeConvId) return;
    const active = conversations.find((c) => c.id === activeConvId);
    if (active?.title === null) {
      removeConversation(active.id); resetConv(active.id);
      deleteConversation(active.id).catch(() => {});
    }
  }

  async function handleNewChat() {
    if (creating) return;
    setCreating(true);
    try {
      await pruneEmptyActive();
      const conv = await createConversation();
      addConversation(conv); onSelectConversation(conv); onMobileClose?.();
    } finally { setCreating(false); }
  }

  async function handleNavClick(path: string) {
    if (path === "/chat") {
      // Resume the active conversation if there is one; otherwise let
      // ChatRoute auto-create a fresh one. Avoids spawning a new conv per click.
      const target = activeConvId ? `/chat/${activeConvId}` : "/chat";
      navigate(buildLocalizedPath(currentLanguage, target));
      onMobileClose?.();
      return;
    }
    await pruneEmptyActive();
    navigate(buildLocalizedPath(currentLanguage, path));
    onMobileClose?.();
  }

  function handleConvSelect(conv: Conversation) { onSelectConversation(conv); onMobileClose?.(); }

  const searchQuery = search.trim().toLowerCase();
  const matchedConvs = searchQuery.length >= 2
    ? conversations.filter((c) => (c.title ?? "").toLowerCase().includes(searchQuery)).slice(0, 6)
    : [];

  async function handleDelete(e: React.MouseEvent, conv: Conversation) {
    e.stopPropagation();
    if (!window.confirm(`Delete "${conv.title ?? "Untitled"}"?`)) return;
    await deleteConversation(conv.id);
    removeConversation(conv.id); resetConv(conv.id);
  }

  function startEdit(e: React.MouseEvent, conv: Conversation) {
    e.stopPropagation(); setEditingId(conv.id); setEditTitle(conv.title ?? "");
  }

  async function commitEdit(conv: Conversation) {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== conv.title) {
      await updateConversationTitle(conv.id, trimmed); updateTitle(conv.id, trimmed);
    }
    setEditingId(null);
  }

  const displayName = name || authUser?.username || "You";
  // Only list conversations that have a real title — never show empty/"Untitled"
  // placeholder conversations created when Coach is opened without a message.
  const titledConvs = conversations.filter((c) => c.title);
  const visibleConvs = titledConvs.slice(0, 6);
  const hiddenCount = Math.max(0, titledConvs.length - visibleConvs.length);

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={onMobileClose} aria-hidden="true" />
      )}

      {/* ── Sidebar panel ── */}
      <motion.aside
        initial={false}
        animate={{ width: effectiveCollapsed ? 72 : 240 }}
        transition={{ type: "spring", stiffness: 340, damping: 32 }}
        className={cn(
          "z-40 flex flex-col border-r border-line/70 bg-surface/70 backdrop-blur-xl overflow-hidden shrink-0",
          // Desktop: static (in flex flow so main content syncs)
          // Mobile: fixed overlay, toggled via translate
          "fixed inset-y-0 left-0 md:static md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        )}
      >
        {/* ── Brand row ── */}
        <div className={cn(
          "flex items-center border-b border-line/50",
          effectiveCollapsed ? "justify-center gap-0 px-0 py-4" : "gap-2.5 px-3 py-4",
        )}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-accent shadow-glow">
            <BrandMark size={16} />
          </div>
          <AnimatePresence>
            {!effectiveCollapsed && (
              <motion.div
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="flex flex-1 items-center justify-between overflow-hidden"
              >
                <span className="whitespace-nowrap text-base font-bold tracking-tight">{t("appName")}</span>
                <button onClick={onMobileClose}
                  className="rounded-md p-1 text-content-muted hover:bg-surface-raised hover:text-content md:hidden"
                  aria-label="Close menu">
                  <X className="h-4 w-4" />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Desktop collapse toggle */}
          <button
            onClick={onToggleCollapse}
            title={effectiveCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "hidden md:flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
              "text-content-muted hover:bg-surface-raised hover:text-content transition-colors",
            )}
          >
            {effectiveCollapsed
              ? <ChevronRight className="h-3.5 w-3.5" />
              : <ChevronLeft className="h-3.5 w-3.5" />}
          </button>
        </div>

        {/* ── Search ── */}
        <div className={cn("pt-3 pb-2", effectiveCollapsed ? "px-2" : "px-2.5")}>
          {effectiveCollapsed ? (
            <button
              title={`${t("search")} (⌘K)`}
              onClick={() => { onToggleCollapse(); setTimeout(() => searchRef.current?.focus(), 380); }}
              className="flex h-9 w-full items-center justify-center rounded-[10px] border border-line bg-surface-raised text-content-muted transition hover:border-accent/50 hover:text-content"
            >
              <Search className="h-3.5 w-3.5" />
            </button>
          ) : (
            <>
              <div className="flex items-center gap-2 rounded-[10px] border border-line bg-surface-raised px-2.5 py-[7px] focus-within:border-accent transition-colors">
                <Search className="h-3 w-3 shrink-0 text-content-muted" />
                <input
                  ref={searchRef}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("search")}
                  className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-content-muted"
                />
                <span className="rounded border border-line bg-bg px-1.5 py-0.5 font-mono text-[10px] text-content-muted">⌘K</span>
              </div>

              {/* Search results dropdown */}
              {(searchResults || matchedConvs.length > 0) && (
                <div className="mt-1.5 max-h-60 overflow-y-auto rounded-xl border border-line bg-bg p-1.5 shadow-xl text-[10px]">
                  {matchedConvs.length > 0 && (
                    <>
                      <div className="px-1 py-0.5 text-overline uppercase text-content-muted">{t("recent")}</div>
                      {matchedConvs.map((conv) => (
                        <button key={conv.id} onClick={() => handleConvSelect(conv)}
                          className="flex w-full items-start gap-1.5 rounded-lg px-1.5 py-1 text-left hover:bg-surface-raised">
                          <MessageSquare className="mt-0.5 h-3 w-3 shrink-0 text-content-muted" />
                          <span className="min-w-0 flex-1 truncate text-content">{conv.title ?? "Untitled"}</span>
                        </button>
                      ))}
                    </>
                  )}
                  {searchResults && searchResults.length > 0 && (
                    <div className="mt-1 px-1 py-0.5 text-overline uppercase text-content-muted">Memory</div>
                  )}
                  {searching && <div className="px-1 py-1 text-content-muted">{t("loading")}</div>}
                  {!searching && searchResults && searchResults.length === 0 && matchedConvs.length === 0 && (
                    <div className="px-1 py-1 text-content-muted">{t("noResults")}</div>
                  )}
                  {!searching && searchResults?.map((h, i) => (
                    <div key={i} className="flex items-start gap-1.5 rounded-lg px-1.5 py-1 hover:bg-surface-raised">
                      <Brain className="mt-0.5 h-3 w-3 shrink-0 text-accent" />
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 leading-snug text-content">{h.text}</p>
                        {(h.metadata as { kind?: string }).kind && (
                          <p className="mt-0.5 text-overline uppercase text-content-muted">
                            {(h.metadata as { kind?: string }).kind}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Main nav ── */}
        <nav className="flex flex-col gap-0.5 px-2 pb-2">
          {NAV_SECTIONS.map((section, si) => {
            // Hide deferred surfaces (Budget/Documents) from the primary nav per
            // docs/URUN_ODAK.md; routes stay deep-linkable. Drop now-empty sections.
            const items = section.items.filter(({ path }) => isNavEnabled(path));
            if (items.length === 0) return null;
            return (
            <div key={si} className={si > 0 ? "mt-1" : ""}>
              <AnimatePresence>
                {!effectiveCollapsed && section.label && (
                  <motion.p
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.15 }}
                    className="mb-1 overflow-hidden px-2.5 pt-1 text-overline uppercase text-content-muted/60"
                  >
                    {section.label}
                  </motion.p>
                )}
              </AnimatePresence>

              {items.map(({ path, key, icon: Icon }) => {
                const active = currentPath === path || currentPath.startsWith(`${path}/`);
                return (
                  <button
                    key={path}
                    onClick={() => void handleNavClick(path)}
                    title={effectiveCollapsed ? navLabel(key) : undefined}
                    className={cn(
                      "relative flex w-full items-center gap-3 rounded-[10px] transition-colors",
                      effectiveCollapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
                      active ? "text-accent" : "text-content-muted hover:bg-surface-raised hover:text-content",
                    )}
                  >
                    {active && (
                      <motion.div
                        layoutId="nav-active-pill"
                        className="absolute inset-0 rounded-[10px] bg-accent-muted"
                        transition={{ type: "spring", stiffness: 380, damping: 34 }}
                      />
                    )}
                    <Icon className="relative z-10 h-[15px] w-[15px] shrink-0" />
                    <AnimatePresence>
                      {!effectiveCollapsed && (
                        <motion.span
                          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                          transition={{ duration: 0.12 }}
                          className="relative z-10 whitespace-nowrap text-sm"
                        >
                          {navLabel(key)}
                        </motion.span>
                      )}
                    </AnimatePresence>
                  </button>
                );
              })}
            </div>
            );
          })}

          {/* Settings — Account section */}
          <div className="mt-1">
            <AnimatePresence>
              {!effectiveCollapsed && (
                <motion.p
                  initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.15 }}
                  className="mb-1 overflow-hidden px-2.5 pt-1 text-overline uppercase text-content-muted/60"
                >
                  Account
                </motion.p>
              )}
            </AnimatePresence>
            {(() => {
              const active = currentPath === "/settings";
              return (
                <button
                  onClick={() => void handleNavClick("/settings")}
                  title={effectiveCollapsed ? navLabel("settings") : undefined}
                  className={cn(
                    "relative flex w-full items-center gap-3 rounded-[10px] transition-colors",
                    effectiveCollapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
                    active ? "text-accent" : "text-content-muted hover:bg-surface-raised hover:text-content",
                  )}
                >
                  {active && (
                    <motion.div layoutId="nav-active-pill"
                      className="absolute inset-0 rounded-[10px] bg-accent-muted"
                      transition={{ type: "spring", stiffness: 380, damping: 34 }}
                    />
                  )}
                  <SettingsIcon className="relative z-10 h-[15px] w-[15px] shrink-0" />
                  <AnimatePresence>
                    {!effectiveCollapsed && (
                      <motion.span
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                        transition={{ duration: 0.12 }}
                        className="relative z-10 whitespace-nowrap text-sm"
                      >
                        {navLabel("settings")}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </button>
              );
            })()}
          </div>
        </nav>

        {/* ── Recent conversations (hidden when collapsed) ── */}
        <AnimatePresence>
          {!effectiveCollapsed && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="border-t border-line/50 px-2 pt-3 pb-2"
            >
              <div className="mb-1.5 flex items-center justify-between px-1.5">
                <button
                  onClick={() => setRecentOpen((v) => !v)}
                  className="flex items-center gap-1.5 text-overline uppercase text-content-muted transition hover:text-content"
                >
                  {recentOpen ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
                  {t("recent")}
                </button>
                <button onClick={handleNewChat} disabled={creating} title={tChat("newChat")}
                  className="rounded-md p-1 text-content-muted transition hover:bg-surface-raised hover:text-accent disabled:opacity-40">
                  <Plus className="h-3 w-3" />
                </button>
              </div>

              {recentOpen && visibleConvs.length > 0 && (
                <div className="flex max-h-40 flex-col gap-px overflow-y-auto">
                  {visibleConvs.map((conv) => (
                    <div key={conv.id} onClick={() => handleConvSelect(conv)}
                      className={cn(
                        "group flex cursor-pointer items-center gap-2 rounded-[10px] px-3 py-1.5 text-xs transition",
                        onChatRoute && activeConvId === conv.id
                          ? "bg-accent-muted text-accent"
                          : "text-content-muted hover:bg-surface-raised hover:text-content",
                      )}
                    >
                      <MessageSquare className="h-3 w-3 shrink-0" />
                      {editingId === conv.id ? (
                        <input autoFocus value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void commitEdit(conv);
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          onClick={(e) => e.stopPropagation()}
                          className="min-w-0 flex-1 truncate bg-transparent outline-none"
                        />
                      ) : (
                        <span className="min-w-0 flex-1 truncate">{conv.title ?? "Untitled"}</span>
                      )}
                      {editingId === conv.id ? (
                        <div className="flex shrink-0 gap-1">
                          <button onClick={(e) => { e.stopPropagation(); void commitEdit(conv); }}>
                            <Check className="h-3 w-3 text-gain" />
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); setEditingId(null); }}>
                            <X className="h-3 w-3 text-loss" />
                          </button>
                        </div>
                      ) : (
                        <div className="hidden shrink-0 items-center gap-1 group-hover:flex">
                          <button onClick={(e) => startEdit(e, conv)} className="rounded p-0.5 hover:text-accent">
                            <Pencil className="h-3 w-3" />
                          </button>
                          <button onClick={(e) => void handleDelete(e, conv)} className="rounded p-0.5 hover:text-loss">
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                  {hiddenCount > 0 && (
                    <div className="px-3 py-1 text-[10px] text-content-muted">+{hiddenCount} more</div>
                  )}
                </div>
              )}
              {recentOpen && titledConvs.length === 0 && (
                <p className="px-3 py-1 text-caption text-content-muted">{t("noChatsYet")}</p>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex-1" />

        {/* ── Status pill ── */}
        <div className={cn(
          "mx-2 mb-2 flex items-center gap-2 rounded-[10px] border border-line bg-surface-raised",
          effectiveCollapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
        )}>
          <span
            className={cn(
              "h-2 w-2 shrink-0 rounded-full",
              healthy === true  && "bg-gain shadow-[0_0_6px_rgba(34,197,94,0.7)]",
              healthy === false && "bg-loss",
              healthy === null  && "bg-warning animate-pulse",
            )}
            title={healthy === true ? "Coach online" : healthy === false ? "Offline" : "Connecting…"}
          />
          <AnimatePresence>
            {!effectiveCollapsed && (
              <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="whitespace-nowrap text-[11px] font-medium">
                {healthy === true
                  ? <><span className="text-gain">{tChat("coach")}</span> {t("online")}</>
                  : healthy === false ? t("offline") : t("reconnecting")}
              </motion.span>
            )}
          </AnimatePresence>
          {!effectiveCollapsed && healthy === true && <Zap className="ml-auto h-3 w-3 text-gain/60" />}
        </div>

        {/* ── Profile chip ── */}
        <div className="relative mx-2 mb-2" ref={profileWrapRef}>
          <button
            onClick={() => setProfileOpen((v) => !v)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-[12px] border border-line bg-surface-raised transition",
              "hover:border-accent/40 hover:shadow-[0_0_12px_rgba(31,181,122,0.1)]",
              effectiveCollapsed ? "justify-center p-2" : "p-2",
            )}
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-accent/30 bg-accent-muted text-lg leading-none">
              {avatarMeta.emoji}
            </div>
            <AnimatePresence>
              {!effectiveCollapsed && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="min-w-0 flex-1 overflow-hidden text-left">
                  <div className="truncate text-xs font-semibold">{displayName}</div>
                  <div className="mt-0.5 text-[10px] text-content-muted">Personal account</div>
                </motion.div>
              )}
            </AnimatePresence>
            <AnimatePresence>
              {!effectiveCollapsed && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <ChevronDown className={cn(
                    "h-3 w-3 shrink-0 text-content-muted transition-transform",
                    profileOpen && "rotate-180",
                  )} />
                </motion.div>
              )}
            </AnimatePresence>
          </button>

          <AnimatePresence>
            {profileOpen && (
              <motion.div
                initial={{ opacity: 0, y: 6, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 4, scale: 0.97 }}
                transition={{ duration: 0.14 }}
                className="absolute bottom-full left-0 right-0 z-50 mb-1.5 flex flex-col gap-0.5 rounded-[12px] border border-line bg-surface p-1 shadow-[0_8px_32px_rgba(0,0,0,0.6)]"
              >
                <button
                  onClick={() => { setProfileOpen(false); void handleNavClick("/settings"); }}
                  className="flex items-center gap-2 rounded-[8px] px-2.5 py-2 text-xs text-content-muted transition hover:bg-surface-raised hover:text-content"
                >
                  <SettingsIcon className="h-3.5 w-3.5" />
                  <span className="flex-1 text-left">{t("nav.settings")}</span>
                </button>
                <div className="my-0.5 h-px bg-line/60" />
                <button
                  onClick={() => { setProfileOpen(false); void handleLogout(); }}
                  className="flex items-center gap-2 rounded-[8px] px-2.5 py-2 text-xs text-loss transition hover:bg-loss/10"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  <span className="flex-1 text-left">Sign out</span>
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.aside>
    </>
  );
}
