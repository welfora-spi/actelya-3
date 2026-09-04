import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";

const FIELD_CLASS = "w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary";

export default function Register() {
  const { register, formatApiError } = useAuth();
  const { refresh } = useSystem();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    company_name: "", sector: "", website: "", social_links: "", primary_goal: "",
    first_name: "", last_name: "", email: "", password: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const body = {
        ...form,
        social_links: form.social_links.split(",").map((s) => s.trim()).filter(Boolean),
      };
      await register(body);
      await refresh();
      navigate("/onboarding");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="dark min-h-screen bg-background text-foreground flex items-center justify-center relative overflow-hidden py-10">
      <div className="absolute inset-0 grid-lines opacity-40" />
      <div className="absolute top-0 left-0 right-0 h-1 bg-amber-500" />
      <div className="relative w-full max-w-lg mx-4 bg-card border border-border/60 rounded-sm p-8">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-7 h-7 rounded-sm bg-primary text-primary-foreground grid place-items-center font-display font-bold">A</div>
          <span className="font-display font-semibold tracking-tight text-xl">ACTELYA 3</span>
        </div>
        <p className="text-sm text-muted-foreground mb-6">Registra la tua azienda: pochi dati, il resto lo scopriamo noi.</p>

        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-caps block mb-1.5">Nome azienda</label>
              <input data-testid="reg-company" required value={form.company_name} onChange={set("company_name")} className={FIELD_CLASS} />
            </div>
            <div>
              <label className="label-caps block mb-1.5">Settore</label>
              <input data-testid="reg-sector" value={form.sector} onChange={set("sector")} className={FIELD_CLASS} />
            </div>
          </div>
          <div>
            <label className="label-caps block mb-1.5">Sito web</label>
            <input data-testid="reg-website" type="url" placeholder="https://…" value={form.website} onChange={set("website")} className={FIELD_CLASS} />
          </div>
          <div>
            <label className="label-caps block mb-1.5">Social aziendali (separati da virgola)</label>
            <input data-testid="reg-social" placeholder="https://instagram.com/…, https://facebook.com/…" value={form.social_links} onChange={set("social_links")} className={FIELD_CLASS} />
          </div>
          <div>
            <label className="label-caps block mb-1.5">Obiettivo principale</label>
            <input data-testid="reg-goal" value={form.primary_goal} onChange={set("primary_goal")} className={FIELD_CLASS} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-caps block mb-1.5">Nome</label>
              <input data-testid="reg-firstname" required value={form.first_name} onChange={set("first_name")} className={FIELD_CLASS} />
            </div>
            <div>
              <label className="label-caps block mb-1.5">Cognome</label>
              <input data-testid="reg-lastname" required value={form.last_name} onChange={set("last_name")} className={FIELD_CLASS} />
            </div>
          </div>
          <div>
            <label className="label-caps block mb-1.5">Email</label>
            <input data-testid="reg-email" type="email" required value={form.email} onChange={set("email")} className={FIELD_CLASS} />
          </div>
          <div>
            <label className="label-caps block mb-1.5">Password</label>
            <input data-testid="reg-password" type="password" required minLength={8} value={form.password} onChange={set("password")} className={FIELD_CLASS} />
          </div>
          {error && <div data-testid="reg-error" className="text-sm text-red-400 border border-red-500/30 bg-red-500/10 rounded-sm px-3 py-2">{error}</div>}
          <button
            data-testid="reg-submit"
            disabled={loading}
            className="w-full bg-primary text-primary-foreground rounded-sm px-3 py-2.5 text-sm font-medium hover:opacity-90 transition-colors duration-200 active:scale-[0.98] disabled:opacity-50"
          >
            {loading ? "Creazione account…" : "Crea la tua azienda su ACTELYA"}
          </button>
          <p className="text-xs text-muted-foreground text-center">
            Hai già un account? <Link to="/login" className="text-primary hover:underline">Accedi</Link>
          </p>
        </form>
      </div>
    </div>
  );
}
