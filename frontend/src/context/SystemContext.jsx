import { createContext, useContext, useState, useCallback } from "react";
import api from "@/lib/api";

const SystemContext = createContext(null);

export function SystemProvider({ children }) {
  const [settings, setSettings] = useState(null);
  const [budget, setBudget] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([api.get("/settings"), api.get("/budget")]);
      setSettings(s.data);
      setBudget(b.data);
    } catch { /* not authenticated yet */ }
  }, []);

  const mode = settings?.ai_real_mode ? "REALE" : "SIMULAZIONE";
  return (
    <SystemContext.Provider value={{ settings, budget, mode, refresh }}>
      {children}
    </SystemContext.Provider>
  );
}

export const useSystem = () => useContext(SystemContext);
