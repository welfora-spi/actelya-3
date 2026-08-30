import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function ChangePassword() {
  const { loadMe } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (next.length < 8) { setError("La nuova password deve avere almeno 8 caratteri."); return; }
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      toast.success("Password aggiornata");
      await loadMe();
      navigate("/");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    }
  };

  return (
    <div className="dark min-h-screen bg-background text-foreground flex items-center justify-center">
      <div className="w-full max-w-sm mx-4 bg-card border border-border/60 rounded-sm p-8">
        <h1 className="font-display text-xl font-semibold tracking-tight mb-1">Cambio password obbligatorio</h1>
        <p className="text-sm text-muted-foreground mb-6">Al primo accesso devi impostare una nuova password.</p>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label-caps block mb-1.5">Password attuale</label>
            <input data-testid="cp-current" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required
              className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
          </div>
          <div>
            <label className="label-caps block mb-1.5">Nuova password</label>
            <input data-testid="cp-new" type="password" value={next} onChange={(e) => setNext(e.target.value)} required
              className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
          </div>
          {error && <div className="text-sm text-red-400">{error}</div>}
          <button data-testid="cp-submit" className="w-full bg-primary text-primary-foreground rounded-sm px-3 py-2.5 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200">
            Aggiorna password
          </button>
        </form>
      </div>
    </div>
  );
}
