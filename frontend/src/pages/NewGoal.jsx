import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";

// Collegata esclusivamente a POST /brain/plans (mai al vecchio /goals di M1):
// triage + selezione dinamica degli agenti + creazione del piano M2 sono
// un'unica chiamata. Nessuna azione viene mai avviata da questa pagina:
// per READY si mostra solo il riepilogo, l'approvazione/esecuzione resta
// sulla pagina del piano (/piani/:id, gia' presidiata da ruoli e conferme
// esplicite).
const EXAMPLES = [
  "Fammi un Reel per promuovere le focaccine questo weekend",
  "Crea un reel per Instagram per pubblicizzare i panini del Bakery & Coffee di Merate",
  "Voglio 10 appuntamenti per consulenza assicurativa",
  "Pubblica immediatamente il reel su Instagram",
];

const STATUS_LABEL = {
  READY: "Pronto",
  NEEDS_CLARIFICATION: "Serve un chiarimento",
  UNSUPPORTED: "Non gestibile",
  BLOCKED_RISK: "Bloccato",
};

export default function NewGoal() {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");

  // Stato del pannello di chiarimento: effectiveText e' il testo (originale +
  // risposte gia' incorporate nei giri precedenti) da usare come base del
  // prossimo /brain/plans — "text" invece resta SEMPRE quello scritto
  // dall'utente, mostrato cosi' com'e' nel pannello (mai da riscrivere).
  const [effectiveText, setEffectiveText] = useState("");
  const [answers, setAnswers] = useState([]);
  const [clarifyLoading, setClarifyLoading] = useState(false);
  const [clarifyError, setClarifyError] = useState("");

  const currentQuestions = (result?.questions || result?.clarifying_questions || []);

  const startClarification = (data) => {
    setAnswers(new Array((data.questions || data.clarifying_questions || []).length).fill(""));
    setEffectiveText(data.normalized_goal || text);
    setClarifyError("");
  };

  const submit = async () => {
    if (!text.trim()) return;
    setLoading(true); setResult(null); setClarifyError("");
    try {
      const { data } = await api.post("/brain/plans", { text });
      setResult(data);
      if (data.status === "NEEDS_CLARIFICATION") startClarification(data);
      if (data.status !== "READY") {
        toast.warning(STATUS_LABEL[data.status] || data.status);
      }
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  };

  const updateAnswer = (i, value) => {
    setAnswers((prev) => {
      const next = [...prev];
      next[i] = value;
      return next;
    });
    setClarifyError("");
  };

  const submitClarification = async () => {
    if (!result || clarifyLoading) return;
    if (answers.length !== currentQuestions.length || answers.some((a) => !a || !a.trim())) {
      setClarifyError("Rispondi a tutte le domande prima di inviare: nessun campo può restare vuoto.");
      return;
    }
    setClarifyLoading(true);
    try {
      const { data } = await api.post("/brain/plans", {
        text: effectiveText,
        session_id: result.session_id,
        clarification: {
          missing_information: result.missing_information || [],
          questions: currentQuestions,
          answers,
        },
      });
      setResult(data);
      if (data.status === "NEEDS_CLARIFICATION") startClarification(data);
      else setAnswers([]);
      if (data.status !== "READY") {
        toast.warning(STATUS_LABEL[data.status] || data.status);
      } else {
        toast.success("Informazioni sufficienti: piano creato.");
      }
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setClarifyLoading(false); }
  };

  const goToRoom = () => {
    if (result?.plan?.id) navigate(`/sala-riunioni?planId=${result.plan.id}`);
  };

  return (
    <div>
      <PageHeader title="Nuovo Obiettivo"
        subtitle="Il brain classifica l'obiettivo, seleziona SOLO gli agenti necessari e — se pronto — crea un piano M2. Nessuna azione esterna, nessuna approvazione automatica." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <label className="label-caps block mb-2">Obiettivo</label>
          <textarea
            data-testid="goal-input"
            value={text} onChange={(e) => setText(e.target.value)} rows={5}
            placeholder="Es: Crea un reel per Instagram per pubblicizzare…"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none resize-none"
          />
          <div className="mt-3 space-y-1.5">
            <div className="label-caps">Esempi</div>
            {EXAMPLES.map((ex, i) => (
              <button key={i} data-testid={`goal-example-${i}`} onClick={() => setText(ex)}
                className="block text-left text-xs text-muted-foreground hover:text-foreground border border-border/60 rounded-sm px-2 py-1.5 w-full transition-colors duration-200">
                {ex}
              </button>
            ))}
          </div>
          <button data-testid="goal-classify" onClick={submit} disabled={loading || !text.trim()}
            className="mt-4 bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-50">
            {loading ? "Analisi…" : "Analizza con il brain"}
          </button>
        </Card>

        <Card className="p-5">
          <h2 className="font-display text-lg font-medium mb-3">Esito</h2>
          {!result && <p className="text-sm text-muted-foreground">Inserisci un obiettivo: nessuna chiamata reale, nessun piano finché non invii.</p>}

          {result && (
            <div className="space-y-4" data-testid="goal-result">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="label-caps">Stato</span>
                <StatusBadge status={result.status} testid="goal-status" />
                {result.risk_flags?.map((r) => (
                  <span key={r} className="text-[10px] font-mono border border-red-500/30 bg-red-500/10 text-red-400 rounded-sm px-1.5 py-0.5">{r}</span>
                ))}
              </div>

              {result.status === "NEEDS_CLARIFICATION" && (
                <div data-testid="goal-clarify" className="border border-violet-500/30 bg-violet-500/10 rounded-sm p-3 sm:p-4 space-y-3 w-full max-w-full overflow-hidden">
                  <div>
                    <p className="text-sm font-medium text-violet-300">
                      Servono alcune informazioni prima di procedere. <span className="font-semibold">Nessun piano è stato creato.</span>
                    </p>
                    <p className="text-xs text-muted-foreground mt-1 break-words">
                      Richiesta originale: <span className="italic">"{text}"</span> — non serve riscriverla, rispondi solo qui sotto.
                    </p>
                  </div>

                  <div className="space-y-3" data-testid="clarify-questions">
                    {currentQuestions.map((q, i) => (
                      <div key={i}>
                        <label htmlFor={`clarify-answer-${i}`} className="block text-xs font-medium text-foreground mb-1">
                          {q}
                        </label>
                        <input
                          id={`clarify-answer-${i}`}
                          data-testid={`clarify-answer-${i}`}
                          type="text"
                          value={answers[i] || ""}
                          onChange={(e) => updateAnswer(i, e.target.value)}
                          disabled={clarifyLoading}
                          className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:opacity-50"
                        />
                      </div>
                    ))}
                  </div>

                  {clarifyError && (
                    <p data-testid="clarify-error" className="text-xs text-red-400">{clarifyError}</p>
                  )}

                  <button
                    data-testid="clarify-submit"
                    onClick={submitClarification}
                    disabled={clarifyLoading}
                    className="w-full bg-primary text-primary-foreground rounded-sm px-4 py-2.5 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-50"
                  >
                    {clarifyLoading ? "Riesame in corso…" : "Invia risposte e riesamina"}
                  </button>
                </div>
              )}

              {result.status === "UNSUPPORTED" && (
                <div data-testid="goal-unsupported" className="text-sm border border-border bg-muted/30 text-muted-foreground rounded-sm px-3 py-2.5 space-y-1.5">
                  <p className="font-medium text-foreground">Richiesta non gestibile da ACTELYA 3. Nessun piano è stato creato.</p>
                  {result.unavailable_capabilities?.length > 0 && (
                    <p>Capability non disponibili: {result.unavailable_capabilities.join(", ")}.</p>
                  )}
                  {result.execution_warnings?.map((w, i) => <p key={i}>{w}</p>)}
                </div>
              )}

              {result.status === "BLOCKED_RISK" && (
                <div data-testid="goal-blocked" className="text-sm border border-red-500/30 bg-red-500/10 text-red-400 rounded-sm px-3 py-2.5">
                  <p className="font-medium">Richiesta bloccata: implica un'azione esterna reale o un intento non consentito. Nessun piano creato, nessuna azione eseguita.</p>
                </div>
              )}

              {result.status === "READY" && (
                <div className="space-y-4" data-testid="goal-ready">
                  <div>
                    <div className="label-caps mb-1">Agenti selezionati</div>
                    <div className="flex flex-wrap gap-1.5">
                      {result.activeAgentIds.map((a) => (
                        <span key={a} className="text-[11px] font-mono border border-border rounded-sm px-2 py-0.5">{a}</span>
                      ))}
                    </div>
                  </div>

                  {result.selected_agents?.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="label-caps">Motivazione selezione</div>
                      {result.selected_agents.map((a) => (
                        <div key={a.agent_id} className="text-xs text-muted-foreground border-l-2 border-border/60 pl-2.5">
                          <span className="text-foreground font-medium">{a.agent_id}</span> — {a.reason}
                        </div>
                      ))}
                    </div>
                  )}

                  {result.plan ? (
                    <>
                      <div className="text-sm border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 rounded-sm px-3 py-2.5">
                        UN SOLO piano <b>{result.plan.objective_type}</b> creato in bozza — {result.tasks?.length ?? 0} attività, in attesa di approvazione. Nessuna azione è stata eseguita.
                        {result.reel_project && (
                          <> Include un task <b>reel</b> collegato a un progetto reale (testo via Requesty, video via Runway — sempre con conferma esplicita prima di ogni chiamata a pagamento).</>
                        )}
                      </div>
                      <button data-testid="goal-go-to-room" onClick={goToRoom}
                        className="w-full flex items-center justify-center gap-1.5 bg-emerald-600 text-white rounded-sm px-4 py-2.5 text-sm font-medium hover:bg-emerald-500 active:scale-[0.98] transition-colors duration-200">
                        Apri in Sala Riunioni <ArrowRight className="w-4 h-4" />
                      </button>
                      {isAdmin && (
                        <button onClick={() => navigate(`/piani/${result.plan.id}`)}
                          className="w-full text-xs text-muted-foreground hover:text-foreground transition-colors duration-200">
                          oppure apri la vista tecnica del piano (Piani M2)
                        </button>
                      )}
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">Selezione pronta, ma il piano non è stato ancora creato.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
