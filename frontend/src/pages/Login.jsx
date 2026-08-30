import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { FlaskConical } from "lucide-react";

export default function Login() {
  const { login, formatApiError } = useAuth();
  const { refresh } = useSystem();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const u = await login(email.trim(), password);
      await refresh();
      navigate(u.must_change_password ? "/cambia-password" : "/");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="dark min-h-screen bg-background text-foreground flex items-center justify-center relative overflow-hidden">
      <div className="absolute inset-0 grid-lines opacity-40" />
      <div className="absolute top-0 left-0 right-0 h-1 bg-amber-500" />
      <div className="relative w-full max-w-sm mx-4 bg-card border border-border/60 rounded-sm p-8">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-7 h-7 rounded-sm bg-primary text-primary-foreground grid place-items-center font-display font-bold">A</div>
          <span className="font-display font-semibold tracking-tight text-xl">ACTELYA 2</span>
        </div>
        <p className="text-sm text-muted-foreground mb-6">Sistema operativo AI per marketing e vendite.</p>

        <div className="flex items-center gap-2 rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-500 px-3 py-1.5 text-xs font-mono mb-6">
          <FlaskConical className="w-4 h-4" /> MODALITÀ SIMULAZIONE
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label-caps block mb-1.5">Email</label>
            <input
              data-testid="login-email"
              type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
              className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            />
          </div>
          <div>
            <label className="label-caps block mb-1.5">Password</label>
            <input
              data-testid="login-password"
              type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            />
          </div>
          {error && <div data-testid="login-error" className="text-sm text-red-400 border border-red-500/30 bg-red-500/10 rounded-sm px-3 py-2">{error}</div>}
          <button
            data-testid="login-submit"
            disabled={loading}
            className="w-full bg-primary text-primary-foreground rounded-sm px-3 py-2.5 text-sm font-medium hover:opacity-90 transition-colors duration-200 active:scale-[0.98] disabled:opacity-50"
          >
            {loading ? "Accesso…" : "Accedi"}
          </button>
        </form>
      </div>
    </div>
  );
}
