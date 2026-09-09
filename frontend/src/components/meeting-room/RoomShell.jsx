import { useEffect } from "react";
import { NavLink } from "react-router-dom";
import { Users, BarChart3, CheckSquare, Presentation, ArrowLeft, Sparkles } from "lucide-react";
import { useSystem } from "@/context/SystemContext";
import { cn } from "@/lib/utils";

// Chrome dedicata alla Sala Riunioni: sidebar minimale a 4 voci, fedele al
// riferimento di composizione. Non sostituisce components/Layout.jsx (che
// resta invariato per tutte le altre pagine): questa è una "chrome"
// alternativa usata SOLO da questa pagina.
const NAV = [
  { to: "/sala-riunioni", label: "Sala riunioni", icon: Presentation, end: true },
  { to: "/operatori", label: "La tua squadra", icon: Users },
  { to: "/deliverable", label: "Risultati", icon: BarChart3 },
  { to: "/approvazioni", label: "Approvazioni", icon: CheckSquare },
];

export default function RoomShell({ children }) {
  const { mode, refresh } = useSystem();

  // Layout.jsx (usato da ogni altra pagina) e' l'UNICO altro punto che
  // chiama refresh() al mount: RoomShell e' una chrome alternativa che non
  // passa mai da li'. Senza questo effetto, chi arriva direttamente in
  // Sala Riunioni (link diretto, refresh, nuova scheda) vede sempre lo
  // stato di default di SystemContext (settings=null -> "SIMULAZIONE"),
  // indipendentemente dalla modalità reale davvero attiva per
  // l'organizzazione — non un'etichetta sbagliata, un dato mai caricato.
  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="dark min-h-screen lg:h-screen lg:overflow-hidden bg-background text-foreground flex" translate="no">
      <aside className="w-44 shrink-0 border-r border-border/60 flex flex-col bg-[#0b0f15] sticky top-0 h-screen">
        <div className="h-14 flex items-center px-4 border-b border-border/60 gap-2">
          <div className="w-6 h-6 rounded-sm bg-primary text-primary-foreground grid place-items-center shrink-0">
            <Sparkles className="w-3.5 h-3.5" strokeWidth={2} />
          </div>
          <span className="font-display font-semibold tracking-tight text-lg">ACTELYA 3</span>
        </div>

        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              data-testid={`room-nav-${n.to.replace(/\//g, "")}`}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors duration-200",
                  isActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                )
              }
            >
              <n.icon className="w-4 h-4 shrink-0" strokeWidth={1.75} />
              <span className="truncate">{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-border/60 space-y-2">
          <NavLink to="/" className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft className="w-3.5 h-3.5" strokeWidth={1.75} /> Torna alla vista operativa
          </NavLink>
          <div className="rounded-md border border-border/60 px-3 py-2" data-testid="room-system-status">
            <div className="label-caps mb-1">Stato sistema</div>
            <div className="flex items-center gap-1.5 text-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              Operativo
            </div>
            <div className="text-[10px] text-muted-foreground font-mono mt-0.5">{mode}</div>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 lg:h-screen lg:overflow-y-auto">
        <main className="p-4 sm:p-5 lg:p-5 max-w-[1800px] mx-auto lg:h-full lg:flex lg:flex-col">{children}</main>
      </div>
    </div>
  );
}
