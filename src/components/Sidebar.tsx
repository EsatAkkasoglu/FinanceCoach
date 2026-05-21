import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  MessageSquare, LayoutDashboard, Briefcase, Wallet, Target, FileText, Settings as SettingsIcon,
  Coins, Compass, Search, Brain,
  Plus, Trash2, Pencil, Check, X, LogOut, ChevronDown, ChevronRight, ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { buildLocalizedPath, getLanguageFromPath, isSupportedLanguage, stripLanguagePrefix } from "@/lib/routing";
import {
  listConversations, createConversation, deleteConversation, updateConversationTitle,
  logout as apiLogout, searchMemory,
  type Conversation, type MemoryHit,
} from "@/lib/api";
import { useAuthStore, useConversationStore, useChatStore, useUserStore } from "@/store";
import { AVATARS } from "@/components/onboarding/data";

const NAV_PATHS: { path: string; key: keyof typeof import("../i18n/locales/en/common.json")["nav"]; icon: typeof MessageSquare }[] = [
  { path: "/dashboard", key: "dashboard", icon: LayoutDashboard },
  { path: "/portfolio", key: "portfolio", icon: Briefcase },
  { path: "/budget", key: "budget", icon: Wallet },
  { path: "/funds", key: "funds", icon: Coins },
  { path: "/discover", key: "discover", icon: Compass },
  { path: "/goals", key: "goals", icon: Target },
  { path: "/documents", key: "documents", icon: FileText },
  { path: "/settings", key: "settings", icon: SettingsIcon },
];

interface Props {
  healthy: boolean | null;
  onSelectConversation: (conv: Conversation) => void;
  activeConvId: string | null;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

// Inline brand mark — a stylized forward "F" matching design system preview/brand-logo.html.
function BrandMark({ size = 18 }: { size?: number }) {
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

export function Sidebar({ healthy, onSelectConversation, activeConvId, mobileOpen = false, onMobileClose }: Props) {
  const { t, i18n } = useTranslation();
  const { t: tChat } = useTranslation("chat");
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = stripLanguagePrefix(location.pathname);
  const currentLanguage = getLanguageFromPath(location.pathname) ?? (isSupportedLanguage(i18n.language) ? i18n.language : "en");
  const onChatRoute = currentPath.startsWith("/chat");
  const { conversations, setConversations, addConversation, removeConversation, updateTitle } =
    useConversationStore();
  const resetConv = useChatStore((s) => s.resetConv);
  const { avatar, name } = useUserStore();
  const authUser = useAuthStore((s) => s.user);
  const setAuthUser = useAuthStore((s) => s.setUser);

  const [creating, setCreating] = useState(false);
  const [recentOpen, setRecentOpen] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<MemoryHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileWrapRef = useRef<HTMLDivElement | null>(null);

  async function handleLogout() {
    await apiLogout();
    setAuthUser(null);
  }

  useEffect(() => {
    const q = search.trim();
    if (q.length < 2) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const hits = await searchMemory(q, 5);
        setSearchResults(hits);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
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
        const empty = all.filter((c) => c.title === null);
        const valid = all.filter((c) => c.title !== null);
        setConversations(valid);
        empty.forEach((c) => deleteConversation(c.id).catch(() => {}));
      })
      .catch(() => {});
  }, [setConversations]);

  async function pruneEmptyActive() {
    if (!activeConvId) return;
    const active = conversations.find((c) => c.id === activeConvId);
    if (active && active.title === null) {
      removeConversation(active.id);
      resetConv(active.id);
      deleteConversation(active.id).catch(() => {});
    }
  }

  async function handleNewChat() {
    if (creating) return;
    setCreating(true);
    try {
      await pruneEmptyActive();
      const conv = await createConversation();
      addConversation(conv);
      onSelectConversation(conv);
      onMobileClose?.();
    } finally {
      setCreating(false);
    }
  }

  async function handleNavClick(path: string) {
    if (!path.startsWith("/chat")) await pruneEmptyActive();
    navigate(buildLocalizedPath(currentLanguage, path));
    onMobileClose?.();
  }

  function handleConvSelect(conv: Conversation) {
    onSelectConversation(conv);
    onMobileClose?.();
  }

  const searchQuery = search.trim().toLowerCase();
  const matchedConvs =
    searchQuery.length >= 2
      ? conversations.filter((c) => (c.title ?? "").toLowerCase().includes(searchQuery)).slice(0, 6)
      : [];

  async function handleDelete(e: React.MouseEvent, conv: Conversation) {
    e.stopPropagation();
    if (!window.confirm(`Delete "${conv.title ?? "Untitled"}"?`)) return;
    await deleteConversation(conv.id);
    removeConversation(conv.id);
    resetConv(conv.id);
  }

  function startEdit(e: React.MouseEvent, conv: Conversation) {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title ?? "");
  }

  async function commitEdit(conv: Conversation) {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== conv.title) {
      await updateConversationTitle(conv.id, trimmed);
      updateTitle(conv.id, trimmed);
    }
    setEditingId(null);
  }

  const displayName = name || authUser?.username || "You";
  const visibleConvs = conversations.slice(0, 6);
  const hiddenCount = Math.max(0, conversations.length - visibleConvs.length);

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}
      <aside
        className={cn(
          "z-40 flex w-60 flex-col border-r border-line bg-surface px-3 pt-4 pb-3.5",
          "fixed inset-y-0 left-0 transition-transform duration-200 md:static md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        )}
      >
        {/* Brand row — logo tile + wordmark, separated from profile */}
        <div className="mb-3.5 flex items-center gap-2.5 px-1.5">
          <div className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[9px] bg-accent shadow-glow">
            <BrandMark size={18} />
          </div>
          <div className="flex-1 text-[15px] font-bold leading-none tracking-tight">{t("appName")}</div>
          <button
            type="button"
            onClick={onMobileClose}
            className="rounded-md p-1 text-content-muted hover:bg-surface-raised hover:text-content md:hidden"
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Search row — semantic memory search disguised as a chats search */}
        <div className="mb-3">
          <div className="flex items-center gap-2 rounded-[10px] border border-line bg-surface-raised px-2.5 py-[7px] focus-within:border-accent">
            <Search className="h-3 w-3 shrink-0 text-content-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("search")}
              className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-content-muted"
            />
            <span className="rounded border border-line bg-bg px-1.5 py-0.5 font-mono text-[10px] text-content-muted">
              ⌘K
            </span>
          </div>
          {(searchResults || matchedConvs.length > 0) && (
            <div className="mt-1.5 max-h-60 overflow-y-auto rounded-md border border-line bg-bg p-1.5 text-[10px]">
              {matchedConvs.length > 0 && (
                <>
                  <div className="px-1 py-0.5 uppercase tracking-wide text-[9px] text-content-muted">
                    {t("recent")}
                  </div>
                  {matchedConvs.map((conv) => (
                    <button
                      key={conv.id}
                      onClick={() => handleConvSelect(conv)}
                      className="flex w-full items-start gap-1.5 rounded px-1 py-1 text-left hover:bg-surface-raised"
                    >
                      <MessageSquare className="mt-0.5 h-3 w-3 shrink-0 text-content-muted" />
                      <span className="min-w-0 flex-1 truncate text-content">
                        {conv.title ?? "Untitled"}
                      </span>
                    </button>
                  ))}
                </>
              )}
              {searchResults && searchResults.length > 0 && (
                <div className="mt-1 px-1 py-0.5 uppercase tracking-wide text-[9px] text-content-muted">
                  Memory
                </div>
              )}
              {searching && <div className="px-1 py-1 text-content-muted">{t("loading")}</div>}
              {!searching && searchResults && searchResults.length === 0 && matchedConvs.length === 0 && (
                <div className="px-1 py-1 text-content-muted">{t("noResults")}</div>
              )}
              {!searching && searchResults?.map((h, i) => (
                <div key={i} className="flex items-start gap-1.5 rounded px-1 py-1 hover:bg-surface-raised">
                  <Brain className="mt-0.5 h-3 w-3 shrink-0 text-accent" />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 leading-snug text-content">{h.text}</p>
                    {(h.metadata as { kind?: string }).kind && (
                      <p className="mt-0.5 uppercase tracking-wide text-[9px] text-content-muted">
                        {(h.metadata as { kind?: string }).kind}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Main nav */}
        <nav className="mb-3.5 flex flex-col gap-0.5">
          {NAV_PATHS.map(({ path, key, icon: Icon }) => {
            const active = currentPath === path || currentPath.startsWith(`${path}/`);
            return (
              <button
                key={path}
                onClick={() => void handleNavClick(path)}
                className={cn(
                  "flex items-center gap-3 rounded-[10px] px-3 py-2 text-[13px] transition",
                  active
                    ? "bg-accent-muted text-accent"
                    : "text-content-muted hover:bg-surface-raised hover:text-content",
                )}
              >
                <Icon className="h-[15px] w-[15px]" />
                {t(`nav.${key}`)}
              </button>
            );
          })}
        </nav>

        {/* Recent eyebrow + new chat */}
        <div className="mb-1.5 flex items-center justify-between px-2">
          <button
            onClick={() => setRecentOpen((v) => !v)}
            className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-content-muted transition hover:text-content"
          >
            {recentOpen ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
            {t("recent")}
          </button>
          <button
            onClick={handleNewChat}
            disabled={creating}
            title={tChat("newChat")}
            className="rounded p-1 text-content-muted transition hover:bg-surface-raised hover:text-accent disabled:opacity-40"
          >
            <Plus className="h-3 w-3" />
          </button>
        </div>

        {recentOpen && visibleConvs.length > 0 && (
          <div className="flex max-h-44 flex-col gap-px overflow-y-auto">
            {visibleConvs.map((conv) => (
              <div
                key={conv.id}
                onClick={() => handleConvSelect(conv)}
                className={cn(
                  "group flex cursor-pointer items-center gap-2 rounded-[10px] px-3 py-2 text-xs transition",
                  onChatRoute && activeConvId === conv.id
                    ? "bg-accent-muted text-accent"
                    : "text-content-muted hover:bg-surface-raised hover:text-content",
                )}
              >
                <MessageSquare className="h-3 w-3 shrink-0" />

                {editingId === conv.id ? (
                  <input
                    autoFocus
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void commitEdit(conv);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="min-w-0 flex-1 truncate bg-transparent outline-none"
                  />
                ) : (
                  <span className="min-w-0 flex-1 truncate">
                    {conv.title ?? "Untitled"}
                  </span>
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
              <div className="px-3 py-1.5 text-[11px] text-content-muted">
                +{hiddenCount} more
              </div>
            )}
          </div>
        )}
        {recentOpen && conversations.length === 0 && (
          <p className="px-3 text-[10px] text-content-muted">{t("noChatsYet")}</p>
        )}

        {/* Spacer pushes status + profile to bottom */}
        <div className="flex-1" />

        {/* Status pill */}
        <div className="mb-2 flex items-center gap-2 rounded-[10px] border border-line bg-surface-raised px-3 py-2 text-[11px]">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              healthy === true && "bg-gain shadow-[0_0_6px_rgba(34,197,94,0.7)]",
              healthy === false && "bg-loss",
              healthy === null && "bg-warning animate-pulse",
            )}
          />
          <span className="flex-1 font-medium">
            {healthy === true ? tChat("coach") + " online" : healthy === false ? "Offline" : t("loading")}
          </span>
        </div>

        {/* Profile chip with expandable menu */}
        <div className="relative" ref={profileWrapRef}>
          <button
            onClick={() => setProfileOpen((v) => !v)}
            className="flex w-full items-center gap-2.5 rounded-[12px] border border-line bg-surface-raised p-2 text-left transition hover:border-content-muted"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-accent/30 bg-accent-muted text-lg leading-none">
              {avatarMeta.emoji}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold">{displayName}</div>
              <div className="mt-0.5 text-[10px] text-content-muted">Personal account</div>
            </div>
            {profileOpen ? (
              <ChevronDown className="h-3 w-3 shrink-0 text-content-muted" />
            ) : (
              <ChevronUp className="h-3 w-3 shrink-0 text-content-muted" />
            )}
          </button>
          {profileOpen && (
            <div className="absolute bottom-full left-0 right-0 z-50 mb-1.5 flex flex-col gap-0.5 rounded-[12px] border border-line bg-surface p-1 shadow-[0_8px_24px_rgba(0,0,0,0.5)]">
              <button
                onClick={() => { setProfileOpen(false); void handleNavClick("/settings"); }}
                className="flex items-center gap-2 rounded-[8px] px-2.5 py-2 text-xs text-content-muted transition hover:bg-surface-raised hover:text-content"
              >
                <SettingsIcon className="h-3.5 w-3.5" />
                <span className="flex-1 text-left">{t("nav.settings")}</span>
              </button>
              <button
                onClick={() => { setProfileOpen(false); void handleLogout(); }}
                className="flex items-center gap-2 rounded-[8px] px-2.5 py-2 text-xs text-loss transition hover:bg-loss/10"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span className="flex-1 text-left">Sign out</span>
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
