import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { SystemProvider } from "@/context/SystemContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";

import Login from "@/pages/Login";
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
import OrgProfile from "@/pages/OrgProfile";
import Users from "@/pages/Users";
import Budget from "@/pages/Budget";
import Audit from "@/pages/Audit";
import Settings from "@/pages/Settings";

function Protected({ children, bare = false }) {
  const { user } = useAuth();
  const location = useLocation();
  if (user === undefined)
    return <div className="dark min-h-screen bg-background text-foreground grid place-items-center text-sm text-muted-foreground">Caricamento…</div>;
  if (user === null) return <Navigate to="/login" replace />;
  if (user.must_change_password && location.pathname !== "/cambia-password")
    return <Navigate to="/cambia-password" replace />;
  // bare=true: la pagina fornisce la propria chrome (es. Sala Riunioni) e non va avvolta nel Layout generico.
  return bare ? children : <Layout>{children}</Layout>;
}

const routes = [
  ["/", <Dashboard />],
  ["/nuovo-obiettivo", <NewGoal />],
  ["/piani", <Plans />],
  ["/piani/:id", <PlanDetail />],
  ["/approvazioni", <Approvals />],
  ["/esecuzioni", <Executions />],
  ["/deliverable", <Deliverables />],
  ["/operatori", <Agents />],
  ["/connessioni", <Connections />],
  ["/profilo", <OrgProfile />],
  ["/utenti", <Users />],
  ["/budget", <Budget />],
  ["/audit", <Audit />],
  ["/impostazioni", <Settings />],
];

function App() {
  return (
    <AuthProvider>
      <SystemProvider>
        <BrowserRouter>
          <Toaster position="top-right" />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/cambia-password" element={<ChangePassword />} />
            <Route path="/sala-riunioni" element={<Protected bare><SalaRiunioni /></Protected>} />
            {routes.map(([path, el]) => (
              <Route key={path} path={path} element={<Protected>{el}</Protected>} />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </SystemProvider>
    </AuthProvider>
  );
}

export default App;
