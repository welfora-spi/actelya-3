import { NavLink, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { cn } from "@/lib/utils";
import { formatBudgetLine } from "@/lib/budget";
import {
  LayoutDashboard, Target, CheckSquare, PlayCircle, FileText, Bot, Plug,
  Building2, Users, Wallet, ScrollText, Settings as SettingsIcon, LogOut, ShieldAlert, FlaskConical, Network, Presentation,
  BookOpen, Clapperboard, UserSearch, CalendarClock, Wrench, PenSquare, Handshake, LineChart,
} from "lucide-react";

// "Esecuzioni" e "Centro Approvazioni" (vecchio flusso M1) sono rimaste
// nascoste dal menu: i nuovi obiettivi passano esclusivamente dal brain
// (Nuovo Obiettivo -> /brain/plans -> Sala Riunioni). File e route restano
// attivi per compatibilita' con dati storici gia' esistenti, vedi App.js.
//
// Correzione item #9 (DECISIONE UFFICIALE) + correzione regressione (vs
// ACTELYA 2): il percorso CLIENTE puro (SOLA_LETTURA) converge SOLO su
// Dashboard, Sala riunioni, Nuovo Obiettivo, Risultati, Conoscenza azienda —
// mai un riferimento tecnico al laboratorio Reel o alle pagine provider.
// "Piani (M2)" e' pero' un ruolo OPERATIVO reale per APPROVATORE/OPERATORE
// (approvare/rifiutare/eseguire, vedi PlanDetail.jsx e la RBAC di
// m2/engine.py, identiche): nasconderlo a questi due ruoli era una
// regressione, non la decisione originale — resta invece riservato ad ADMIN
// tutto cio' che e' supervisione tecnica pura (operatori AI, connessioni,
// laboratori Reel/Lead Generation, profilo, utenti, budget, audit,
// impostazioni). adminOnly=true = nascosto in nav a chi non ha ruolo ADMIN;
// roles=[...] = visibile solo a chi ha uno di quei ruoli (entrambi i
// meccanismi lasciano comunque la route attiva in App.js: un accesso
// diretto via URL segue le stesse regole, non solo il menu).
const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/sala-riunioni", label: "Sala riunioni", icon: Presentation },
  { to: "/nuovo-obiettivo", label: "Nuovo Obiettivo", icon: Target },
  { to: "/onboarding", label: "Conoscenza azienda", icon: BookOpen },
  { to: "/deliverable", label: "Risultati", icon: FileText },
  { to: "/piani", label: "Piani (M2)", icon: Network, roles: ["ADMIN", "APPROVATORE", "OPERATORE"] },
  { to: "/operatori", label: "Operatori AI", icon: Bot, adminOnly: true },
  { to: "/connessioni", label: "Connessioni e API", icon: Plug, adminOnly: true },
  { to: "/reel", label: "Reel — laboratorio", icon: Clapperboard, adminOnly: true },
  { to: "/lead-generation", label: "Lead Generation — laboratorio", icon: UserSearch, adminOnly: true },
  { to: "/appointment-setter", label: "Appointment Setter — laboratorio", icon: CalendarClock, adminOnly: true },
  { to: "/content-creator", label: "Content Creator — laboratorio", icon: PenSquare, adminOnly: true },
  { to: "/sales", label: "Sales — laboratorio", icon: Handshake, adminOnly: true },
  { to: "/analyst", label: "Analyst — laboratorio", icon: LineChart, adminOnly: true },
  { to: "/strumenti", label: "Registro strumenti", icon: Wrench, adminOnly: true },
  { to: "/profilo", label: "Profilo aziendale", icon: Building2, adminOnly: true },
  { to: "/utenti", label: "Utenti e ruoli", icon: Users, adminOnly: true },
  { to: "/budget", label: "Budget e costi", icon: Wallet, adminOnly: true },
  { to: "/audit", label: "Audit Log", icon: ScrollText, adminOnly: true },
  { to: "/impostazioni", label: "Impostazioni", icon: SettingsIcon, adminOnly: true },
];

export default function Layout({ children }) {
  const { user, logout, hasRole } = useAuth();
  const { mode, budget, refresh } = useSystem();
  const navigate = useNavigate();
  const real = mode === "REALE";
  const isAdmin = hasRole("ADMIN");
  const visibleNav = NAV.filter((n) => (n.roles ? hasRole(...n.roles) : !n.adminOnly || isAdmin));

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="dark min-h-screen bg-background text-foreground flex">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-border/60 flex flex-col bg-[#0b0b0d] sticky top-0 h-screen">
        <div className="h-14 flex items-center px-4 border-b border-border/60">
          <div className="w-6 h-6 rounded-sm bg-primary text-primary-foreground grid place-items-center font-display font-bold text-sm">A</div>
          <span className="ml-2 font-display font-semibold tracking-tight text-lg">ACTELYA<span className="text-muted-foreground"> 3</span></span>
        </div>
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {visibleNav.map((n) => (
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
        {/* Mode top border + badge: informazione tecnica sulla modalita' di
            esecuzione (SIMULAZIONE/REALE) — riservata ad ADMIN (item #9:
            il percorso cliente non deve mai vedere terminologia tecnica
            "modalita'/simulazione", ne' un banner che suggerisca una scelta
            operativa: il sistema opera sempre nel solo flusso reale). */}
        {isAdmin && <div className={cn("h-1 w-full", real ? "bg-red-500" : "bg-amber-500")} />}
        {/* Topbar */}
        <header className="h-13 sticky top-1 z-20 backdrop-blur-xl bg-background/70 border-b border-border/60 flex items-center justify-between px-6 py-2">
          {isAdmin ? (
            <div className={cn(
              "flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-mono font-semibold tracking-wide",
              real ? "bg-red-500/10 border-red-500/30 text-red-500" : "bg-amber-500/10 border-amber-500/30 text-amber-500"
            )} data-testid="mode-banner">
              {real ? <ShieldAlert className="w-4 h-4" /> : <FlaskConical className="w-4 h-4" />}
              MODALITÀ {mode}
              {real ? " — chiamate reali possibili" : " — nessuna chiamata AI reale"}
            </div>
          ) : <div />}
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="label-caps">Budget residuo</div>
              <div className="font-mono text-sm">
                {formatBudgetLine(budget?.general_limit, budget?.residual)}
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
