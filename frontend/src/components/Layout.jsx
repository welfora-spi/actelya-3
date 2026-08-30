import { NavLink, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard, Target, CheckSquare, PlayCircle, FileText, Bot, Plug,
  Building2, Users, Wallet, ScrollText, Settings as SettingsIcon, LogOut, ShieldAlert, FlaskConical, Network
} from "lucide-react";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/nuovo-obiettivo", label: "Nuovo Obiettivo", icon: Target },
  { to: "/piani", label: "Piani (M2)", icon: Network },
  { to: "/approvazioni", label: "Centro Approvazioni", icon: CheckSquare },
  { to: "/esecuzioni", label: "Esecuzioni", icon: PlayCircle },
  { to: "/deliverable", label: "Deliverable", icon: FileText },
  { to: "/operatori", label: "Operatori AI", icon: Bot },
  { to: "/connessioni", label: "Connessioni e API", icon: Plug },
  { to: "/profilo", label: "Profilo aziendale", icon: Building2 },
  { to: "/utenti", label: "Utenti e ruoli", icon: Users },
  { to: "/budget", label: "Budget e costi", icon: Wallet },
  { to: "/audit", label: "Audit Log", icon: ScrollText },
  { to: "/impostazioni", label: "Impostazioni", icon: SettingsIcon },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const { mode, budget, refresh } = useSystem();
  const navigate = useNavigate();
  const real = mode === "REALE";

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="dark min-h-screen bg-background text-foreground flex">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-border/60 flex flex-col bg-[#0b0b0d] sticky top-0 h-screen">
        <div className="h-14 flex items-center px-4 border-b border-border/60">
          <div className="w-6 h-6 rounded-sm bg-primary text-primary-foreground grid place-items-center font-display font-bold text-sm">A</div>
          <span className="ml-2 font-display font-semibold tracking-tight text-lg">ACTELYA<span className="text-muted-foreground"> 2</span></span>
        </div>
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              data-testid={`nav-${n.to === "/" ? "dashboard" : n.to.slice(1)}`}
              className={({ isActive }) => cn(
                "flex items-center gap-2.5 rounded-sm px-3 py-2 text-sm transition-colors duration-200",
                isActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
            >
              <n.icon className="w-4 h-4 shrink-0" strokeWidth={1.75} />
              <span className="truncate">{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-border/60">
          <div className="label-caps mb-1">Utente</div>
          <div className="text-sm truncate">{user?.email}</div>
          <div className="text-xs text-muted-foreground font-mono">{user?.role}</div>
          <button
            data-testid="logout-btn"
            onClick={async () => { await logout(); navigate("/login"); }}
            className="mt-3 w-full flex items-center justify-center gap-2 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200 active:scale-[0.98]"
          >
            <LogOut className="w-4 h-4" strokeWidth={1.75} /> Esci
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Mode top border */}
        <div className={cn("h-1 w-full", real ? "bg-red-500" : "bg-amber-500")} />
        {/* Topbar */}
        <header className="h-13 sticky top-1 z-20 backdrop-blur-xl bg-background/70 border-b border-border/60 flex items-center justify-between px-6 py-2">
          <div className={cn(
            "flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-mono font-semibold tracking-wide",
            real ? "bg-red-500/10 border-red-500/30 text-red-500" : "bg-amber-500/10 border-amber-500/30 text-amber-500"
          )} data-testid="mode-banner">
            {real ? <ShieldAlert className="w-4 h-4" /> : <FlaskConical className="w-4 h-4" />}
            MODALITÀ {mode}
            {real ? " — chiamate reali possibili" : " — nessuna chiamata AI reale"}
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="label-caps">Budget residuo</div>
              <div className="font-mono text-sm">
                ${(budget?.residual ?? 0).toFixed(4)}<span className="text-muted-foreground"> / ${(budget?.general_limit ?? 0).toFixed(2)}</span>
              </div>
            </div>
          </div>
        </header>

        <main className="flex-1 p-6 md:p-8 max-w-[1600px] w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
