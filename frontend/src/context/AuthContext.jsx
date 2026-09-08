import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { formatApiError, setSessionExpiredHandler } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined=loading, null=guest, obj=auth

  const loadMe = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data.user);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => { loadMe(); }, [loadMe]);

  // Il refresh automatico (lib/api.js) tenta di rinnovare la sessione da
  // solo; se anche il refresh fallisce (refresh_token scaduto/assente),
  // qui si passa a "ospite": le route protette reindirizzano al login
  // ricordando la pagina corrente, invece di restare bloccate a interrogare
  // endpoint autenticati in silenzio.
  useEffect(() => {
    setSessionExpiredHandler?.(() => setUser(null));
    return () => setSessionExpiredHandler?.(null);
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    setUser(data.user);
    return data.user;
  };

  const register = async (body) => {
    const { data } = await api.post("/tenant/register", body);
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    setUser(null);
  };

  const hasRole = (...roles) => user && roles.includes(user.role);

  return (
    <AuthContext.Provider value={{ user, setUser, login, register, logout, loadMe, hasRole, formatApiError }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
