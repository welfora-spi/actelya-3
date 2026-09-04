import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { SystemProvider } from "@/context/SystemContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";

import Login from "@/pages/Login";
import Register from "@/pages/Register";
import Onboarding from "@/pages/Onboarding";
import ChangePassword from "@/pages/ChangePassword";
import Dashboard from "@/pages/Dashboard";
import SalaRiunioni from "@/pages/SalaRiunioni";
import NewGoal from "@/pages/NewGoal";
import Plans from "@/pages/Plans";
import PlanDetail from "@/pages/PlanDetail";
import Approvals from "@/pages/Approvals";
import Executions from "@/pages/Executions";
import Deliverables from "@/pages/Deliverables";
import Agents from "@/pages/Agents";
import Connections from "@/pages/Connections";
import ReelStudio from "@/pages/ReelStudio";
import OrgProfile from "@/pages/OrgProfile";
import Users from "@/pages/Users";
import Budget from "@/pages/Budget";
import Audit from "@/pages/Audit";
import Settings from "@/pages/Settings";

function Protected({ children, bare = false, roles = null }) {
  const { user, hasRole } = useAuth();
  const location = useLocation();
  if (user === undefined)
    return <div className="dark min-h-screen bg-background text-foreground grid place-items-center text-sm text-muted-foreground">Caricamento…</div>;
  if (user === null) return <Navigate to="/login" replace />;
  if (user.must_change_password && location.pathname !== "/cambia-password")
    return <Navigate to="/cambia-password" replace />;
  // roles: stessa lista usata per nascondere la voce in Layout.jsx (NAV
  // adminOnly) — qui si applica anche a un accesso diretto via URL, non
  // solo al menu, cosi' una pagina tecnica (M2/laboratorio/provider) resta
  // davvero fuori dal percorso cliente (item #9), non solo invisibile.
  if (roles && !hasRole(...roles)) return <Navigate to="/" replace />;
  // bare=true: la pagina fornisce la propria chrome (es. Sala Riunioni) e non va avvolta nel Layout generico.
  return bare ? children : <Layout>{children}</Layout>;
}

const ADMIN_ONLY = ["ADMIN"];

const routes = [
  ["/", <Dashboard />],
  ["/onboarding", <Onboarding />],
  ["/nuovo-obiettivo", <NewGoal />],
  ["/piani", <Plans />, ADMIN_ONLY],
  ["/piani/:id", <PlanDetail />, ADMIN_ONLY],
  ["/approvazioni", <Approvals />],
  ["/esecuzioni", <Executions />],
  ["/deliverable", <Deliverables />],
  ["/operatori", <Agents />, ADMIN_ONLY],
  ["/connessioni", <Connections />, ADMIN_ONLY],
  ["/reel", <ReelStudio />, ADMIN_ONLY],
  ["/profilo", <OrgProfile />, ADMIN_ONLY],
  ["/utenti", <Users />, ADMIN_ONLY],
  ["/budget", <Budget />, ADMIN_ONLY],
  ["/audit", <Audit />, ADMIN_ONLY],
  ["/impostazioni", <Settings />, ADMIN_ONLY],
];

function App() {
  return (
    <AuthProvider>
      <SystemProvider>
        <BrowserRouter>
          <Toaster position="top-right" theme="dark" />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/registrati" element={<Register />} />
            <Route path="/cambia-password" element={<ChangePassword />} />
            <Route path="/sala-riunioni" element={<Protected bare><SalaRiunioni /></Protected>} />
            {/* Anteprima solo sviluppo: stesso componente/dati demo della pagina reale, nessun login,
                esclusa dalla build di produzione (process.env.NODE_ENV e' sostituito a build time). */}
            {process.env.NODE_ENV === "development" && (
              <Route path="/sala-riunioni-preview" element={<SalaRiunioni />} />
            )}
            {routes.map(([path, el, roles]) => (
              <Route key={path} path={path} element={<Protected roles={roles}>{el}</Protected>} />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </SystemProvider>
    </AuthProvider>
  );
}

export default App;
