import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  MessageSquare, LayoutDashboard, Briefcase, Wallet, Target, FileText, Settings as SettingsIcon,
  Coins, Compass, Search, Brain,
  Circle, Plus, Trash2, Pencil, Check, X, LogOut, ChevronDown, ChevronRight,
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

  async function handleLogout() {
    await apiLogout();
    setAuthUser(null);
  }
  const [creating, setCreating] = useState(false);
  const [recentOpen, setRecentOpen] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<MemoryHit[] | null>(null);
  const [searching, setSearching] = useState(false);

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
    } finally {
      setCreating(false);
    }
  }

  async function handleNavClick(path: string) {
    if (!path.startsWith("/chat")) await pruneEmptyActive();
    navigate(buildLocalizedPath(currentLanguage, path));
  }

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
        "z-40 flex w-60 flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-4",
        "fixed inset-y-0 left-0 transition-transform duration-200 md:static md:translate-x-0",
        mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
      )}
    >
      {/* Logo + user identity */}
      <div className="mb-4 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent shadow-glow text-lg leading-none">
          {avatarMeta.emoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold tracking-tight">{t("appName")}</div>
          {(name || authUser?.username) && (
            <div className="truncate text-[10px] text-[hsl(var(--text-muted))]">
              {name || authUser?.username}
            </div>
          )}
        </div>
        <button
          onClick={handleLogout}
          title="Sign out"
          className="rounded-md p-1.5 text-[hsl(var(--text-muted))] transition hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
        >
          <LogOut className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Main nav — product spine */}
      <nav className="mb-4 flex flex-col gap-1">
        {NAV_PATHS.map(({ path, key, icon: Icon }) => {
          const active = currentPath === path || currentPath.startsWith(`${path}/`);
          return (
            <button
              key={path}
              onClick={() => void handleNavClick(path)}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                active
                  ? "bg-accent-muted text-accent"
                  : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
              )}
            >
              <Icon className="h-4 w-4" />
              {t(`nav.${key}`)}
            </button>
          );
        })}
      </nav>

      {/* Semantic memory search */}
      <div className="mb-3 px-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[hsl(var(--text-muted))]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("search")}
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] py-1 pl-7 pr-2 text-[11px] outline-none focus:border-accent"
          />
        </div>
        {searchResults && (
          <div className="mt-1.5 max-h-44 overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] p-1.5 text-[10px]">
            {searching && <div className="px-1 py-1 text-[hsl(var(--text-muted))]">{t("loading")}</div>}
            {!searching && searchResults.length === 0 && (
              <div className="px-1 py-1 text-[hsl(var(--text-muted))]">{t("noResults")}</div>
            )}
            {!searching && searchResults.map((h, i) => (
              <div key={i} className="flex items-start gap-1.5 rounded px-1 py-1 hover:bg-[hsl(var(--surface-2))]">
                <Brain className="mt-0.5 h-3 w-3 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                  <p className="line-clamp-2 leading-snug text-[hsl(var(--text))]">{h.text}</p>
                  {(h.metadata as { kind?: string }).kind && (
                    <p className="mt-0.5 uppercase tracking-wide text-[9px] text-[hsl(var(--text-muted))]">
                      {(h.metadata as { kind?: string }).kind}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent chats (collapsible) */}
      <div className="mb-4">
        <div className="mb-1 flex items-center justify-between px-2">
          <button
            onClick={() => setRecentOpen((v) => !v)}
            className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))] transition hover:text-[hsl(var(--text))]"
          >
            {recentOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {t("recent")}
          </button>
          <button
            onClick={handleNewChat}
            disabled={creating}
            title={tChat("newChat")}
            className="rounded-md p-1 text-[hsl(var(--text-muted))] transition hover:bg-[hsl(var(--surface-2))] hover:text-accent disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
        {recentOpen && conversations.length > 0 && (
          <div className="flex flex-col gap-0.5 overflow-y-auto max-h-52">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => onSelectConversation(conv)}
                className={cn(
                  "group flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs transition",
                  onChatRoute && activeConvId === conv.id
                    ? "bg-accent-muted text-accent"
                    : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
                )}
              >
                <MessageSquare className="h-3.5 w-3.5 shrink-0" />

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
                  <div className="flex gap-1 shrink-0">
                    <button onClick={(e) => { e.stopPropagation(); void commitEdit(conv); }}>
                      <Check className="h-3 w-3 text-gain" />
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); setEditingId(null); }}>
                      <X className="h-3 w-3 text-loss" />
                    </button>
                  </div>
                ) : (
                  <div className="hidden shrink-0 items-center gap-1 group-hover:flex">
                    <button
                      onClick={(e) => startEdit(e, conv)}
                      className="rounded p-0.5 hover:text-accent"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      onClick={(e) => void handleDelete(e, conv)}
                      className="rounded p-0.5 hover:text-loss"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {recentOpen && conversations.length === 0 && (
          <p className="px-2 text-[10px] text-[hsl(var(--text-muted))]">{t("noChatsYet")}</p>
        )}
      </div>

      {/* Status */}
      <div className="mt-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-3">
        <div className="flex items-center gap-2 text-xs">
          <Circle
            className={cn(
              "h-2 w-2 fill-current",
              healthy === true && "text-gain",
              healthy === false && "text-loss",
              healthy === null && "text-warning animate-pulse"
            )}
          />
          <span className="text-[hsl(var(--text-muted))]">
            {healthy === true ? tChat("coach") + " online" : healthy === false ? "Offline" : t("loading")}
          </span>
        </div>
      </div>
    </aside>
    </>
  );
}
