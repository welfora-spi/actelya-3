"""Brain — validazione/normalizzazione della proposta LLM (CEO Agent 100%
reale, blocchi 6/7/9/10/11).

Prende una CeoLLMProposal (o None, percorso deterministico puro) e la
riconcilia con lo stato REALE del sistema — mai il contrario. Ogni
suggerimento del modello e' verificato contro i registry reali
(agent_map.py) prima di essere usato: una capability/agente che il modello
propone ma che non fa parte della selezione deterministica gia' calcolata
da planning/agent_selector.py viene SEMPRE scartata (mai aggiunta al piano),
e la correzione viene registrata per l'audit. I rischi proposti vengono
normalizzati (risk_registry.py) e aggregati SOLO come segnale aggiuntivo di
cautela: la funzione non decide mai da sola di bloccare/sbloccare una
richiesta, ritorna un esito che il chiamante (service.py) applica sopra
alla decisione deterministica gia' presa, mai al posto sua."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .agents.agent_map import EXECUTION_MODE_UNAVAILABLE, mapping_by_capability
from .llm_schema import CeoLLMProposal
from .risk_registry import AZIONE_NONE, RiskDecision, azione_piu_severa, resolve_risk_action

_PATTERN_BUDGET_EURO = re.compile(
    r"(?:€\s*([\d.]+(?:,\d+)?)|([\d.]+(?:,\d+)?)\s*(?:€|euro))", re.IGNORECASE
)


def estrai_budget_deterministico(testo: str) -> Optional[float]:
    """Estrazione regex, indipendente da qualunque LLM: garantisce che il
    rilevamento di un budget dichiarato ('ho 2000 euro di budget') funzioni
    anche quando nessun provider AI e' configurato."""
    m = _PATTERN_BUDGET_EURO.search(testo or "")
    if not m:
        return None
    grezzo = (m.group(1) or m.group(2) or "").replace(".", "").replace(",", ".")
    try:
        return float(grezzo)
    except ValueError:
        return None


@dataclass
class Correzione:
    tipo: str
    dettaglio: str

    def come_dict(self) -> dict:
        return {"tipo": self.tipo, "dettaglio": self.dettaglio}


@dataclass
class NormalizedCeoPlan:
    origine: str                                   # "LLM" | "DETERMINISTICO"
    provider_effettivo: Optional[str] = None
    modello_effettivo: Optional[str] = None
    priorita: str = "MEDIA"
    urgenza: str = "MEDIA"
    scadenza: Optional[str] = None
    budget_totale: Optional[float] = None
    budget_allocato: Optional[float] = None
    allocazioni_budget: list = field(default_factory=list)         # list[{"etichetta": str, "importo": float}] per task/canale
    # Budget OPERATIVO residuo dell'organizzazione (domains/budget.py: cap
    # sulla spesa reale AI, NON il budget di marketing dell'utente sopra) —
    # informativo: NON usato per bloccare/consentire la creazione del piano
    # (quel gate resta a valle, per-chiamata, nei laboratori Reel/Flyer).
    budget_residuo_operativo: Optional[float] = None
    budget_status: str = "NON_APPLICABILE"          # OK | ASSENTE_INDISPENSABILE | CONTRADDITTORIO | RIDOTTO_PER_RISPETTARE_LIMITE | NON_APPLICABILE
    richiede_chiarimento_budget: bool = False
    pubblico: Optional[str] = None
    canali: list = field(default_factory=list)
    capability_validate: list = field(default_factory=list)
    capability_extra_scartate: list = field(default_factory=list)
    task_proposti_validati: list = field(default_factory=list)   # list[dict]
    kpi: list = field(default_factory=list)
    rischi_valutati: list = field(default_factory=list)          # list[dict] (RiskDecision.__dict__)
    azione_rischio_aggregata: str = AZIONE_NONE
    domande_aggiuntive: list = field(default_factory=list)
    assunzioni: list = field(default_factory=list)
    approvazioni_necessarie: list = field(default_factory=list)
    strategia_proposta: str = ""
    confidence: Optional[float] = None
    correzioni: list = field(default_factory=list)               # list[Correzione]

    def come_dict(self) -> dict:
        return {
            "origine": self.origine, "provider_effettivo": self.provider_effettivo,
            "modello_effettivo": self.modello_effettivo, "priorita": self.priorita, "urgenza": self.urgenza,
            "scadenza": self.scadenza, "budget_totale": self.budget_totale, "budget_allocato": self.budget_allocato,
            "allocazioni_budget": self.allocazioni_budget, "budget_residuo_operativo": self.budget_residuo_operativo,
            "budget_status": self.budget_status, "richiede_chiarimento_budget": self.richiede_chiarimento_budget,
            "pubblico": self.pubblico, "canali": self.canali, "capability_validate": self.capability_validate,
            "capability_extra_scartate": self.capability_extra_scartate,
            "task_proposti_validati": self.task_proposti_validati, "kpi": self.kpi,
            "rischi_valutati": self.rischi_valutati, "azione_rischio_aggregata": self.azione_rischio_aggregata,
            "domande_aggiuntive": self.domande_aggiuntive, "assunzioni": self.assunzioni,
            "approvazioni_necessarie": self.approvazioni_necessarie, "strategia_proposta": self.strategia_proposta,
            "confidence": self.confidence, "correzioni": [c.come_dict() for c in self.correzioni],
        }


def _dedup_semantico(candidate: list, gia_note: set) -> list:
    out, viste = [], set(gia_note)
    for c in candidate:
        norm = re.sub(r"\s+", " ", (c or "").strip().lower())
        if not norm or norm in viste:
            continue
        viste.add(norm)
        out.append(c)
    return out


def validate_capabilities_against_registry(capabilities: list) -> tuple[list, list]:
    """Verifica OGNUNA delle capability proposte direttamente contro il
    registry reale (agent_map.py), MAI contro un elenco di capability gia'
    rilevate da parola chiave: e' esattamente questo il cambio richiesto
    dalla correzione architetturale (il guardrail valida contro il registry
    e le policy, non limita l'LLM a confermare solo cio' che le keyword
    avevano gia' trovato). Valida = esiste in agent_map E il suo
    execution_mode non e' UNAVAILABLE. Ritorna (valide, correzioni)."""
    valide: list[str] = []
    correzioni: list[Correzione] = []
    for c in capabilities:
        if c in valide:
            continue
        m = mapping_by_capability(c)
        if m is None:
            correzioni.append(Correzione("capability_scartata", f"'{c}' non esiste nel registry (agent_map.py): proposta dal modello ma mai eseguita."))
        elif m.execution_mode == EXECUTION_MODE_UNAVAILABLE:
            correzioni.append(Correzione("capability_scartata", f"'{c}' esiste nel registry ma non e' oggi eseguibile (nessun agente M2 operativo ne' producer): scartata."))
        else:
            valide.append(c)
    return valide, correzioni


def validate_and_normalize(
    proposta: Optional[CeoLLMProposal], *,
    goal_text: str,
    detected_intents: list,
    provider_effettivo: Optional[str] = None,
    modello_effettivo: Optional[str] = None,
    chiarimenti_gia_dati: Optional[set] = None,
    budget_operativo_residuo: Optional[float] = None,
) -> NormalizedCeoPlan:
    """detected_intents: fallback deterministico a keyword (detect_capabilities()),
    usato SOLO quando proposta e' None (nessun provider disponibile/riuscito)
    — MAI come filtro che restringe le capability proposte dall'LLM: quelle
    sono validate direttamente contro il registry reale
    (validate_capabilities_against_registry sopra), cosi' una capability
    genuina ma non rilevata da alcuna parola chiave (es. "voglio aumentare i
    clienti" -> 'strategy'/'leadgen') puo' comunque entrare nel piano."""
    correzioni: list[Correzione] = []
    chiarimenti_gia_dati = chiarimenti_gia_dati or set()
    intents_set = set(detected_intents or [])

    budget_regex = estrai_budget_deterministico(goal_text)

    if proposta is None:
        piano = NormalizedCeoPlan(origine="DETERMINISTICO", budget_residuo_operativo=budget_operativo_residuo)
        richiede_budget = "ads" in intents_set
        if budget_regex is not None:
            piano.budget_totale = budget_regex
            piano.budget_status = "OK"
        elif richiede_budget:
            piano.budget_status = "ASSENTE_INDISPENSABILE"
            piano.richiede_chiarimento_budget = True
        else:
            piano.budget_status = "NON_APPLICABILE"
        piano.capability_validate = list(detected_intents or [])
        return piano

    # ---- Agenti/capability: validate DIRETTAMENTE contro il registry reale ----
    # Ogni capability menzionata OVUNQUE nella proposta (agenti suggeriti,
    # capability richieste, task proposti) entra nello STESSO controllo
    # unico: un task che nomina una capability valida ma assente dagli
    # 'agenti_suggeriti' non deve mai essere scartato solo per questo.
    proposte_capability = list(dict.fromkeys(
        [a.capability for a in proposta.agenti_suggeriti] + list(proposta.capability_richieste)
        + [t.capability for t in proposta.task_proposti]
    ))
    capability_validate, correzioni_capability = validate_capabilities_against_registry(proposte_capability)
    correzioni.extend(correzioni_capability)
    capability_extra_scartate = [c for c in proposte_capability if c not in capability_validate]

    # ---- Task proposti: stesso registry, MAI un task su una capability non validata ----
    task_validati = []
    for t in sorted(proposta.task_proposti, key=lambda x: x.ordine):
        if t.capability not in capability_validate:
            correzioni.append(Correzione("task_scartato", f"Task '{t.nome}' scartato: capability '{t.capability}' non valida contro il registry."))
            continue
        task_validati.append({
            "nome": t.nome, "capability": t.capability, "ordine": t.ordine,
            "dipende_da": t.dipende_da, "deliverable_type": t.deliverable_type,
            "priorita": t.priorita, "scadenza": t.scadenza,
        })

    # ---- Rischi: normalizzati e aggregati, mai applicati direttamente qui ----
    rischi_valutati: list[RiskDecision] = [resolve_risk_action(r.categoria, r.severita) for r in proposta.rischi]
    azione_aggregata = AZIONE_NONE
    for d in rischi_valutati:
        azione_aggregata = azione_piu_severa(azione_aggregata, d.azione)

    # ---- Budget ----
    budget_status = "NON_APPLICABILE"
    richiede_chiarimento_budget = False
    budget_totale = proposta.budget_totale
    if budget_regex is not None and budget_totale is not None and abs(budget_regex - budget_totale) > max(50.0, 0.25 * max(budget_regex, budget_totale)):
        budget_status = "CONTRADDITTORIO"
        richiede_chiarimento_budget = True
        correzioni.append(Correzione("budget_contraddittorio", f"Il testo indica {budget_regex}, il modello propone {budget_totale}: valori in disaccordo."))
    elif budget_totale is None and budget_regex is not None:
        budget_totale = budget_regex
        budget_status = "OK"
    elif budget_totale is None and ("ads" in intents_set or "ads" in capability_validate):
        budget_status = "ASSENTE_INDISPENSABILE"
        richiede_chiarimento_budget = True
    elif budget_totale is not None:
        budget_status = "OK"

    allocazioni_budget = [{"etichetta": a.etichetta, "importo": a.importo} for a in proposta.allocazioni_budget]
    budget_allocato = sum((a["importo"] for a in allocazioni_budget), 0.0) if allocazioni_budget else None
    if budget_totale is not None and budget_allocato is not None and budget_allocato > budget_totale > 0:
        fattore = budget_totale / budget_allocato
        allocazioni_budget = [{"etichetta": a["etichetta"], "importo": round(a["importo"] * fattore, 2)} for a in allocazioni_budget]
        budget_allocato = round(budget_totale, 2)
        budget_status = "RIDOTTO_PER_RISPETTARE_LIMITE"
        correzioni.append(Correzione("budget_ridotto", f"Le allocazioni proposte superavano il budget totale: ridotte proporzionalmente (fattore {fattore:.2f})."))

    domande_aggiuntive = _dedup_semantico(proposta.dati_mancanti, chiarimenti_gia_dati)

    return NormalizedCeoPlan(
        origine="LLM", provider_effettivo=provider_effettivo, modello_effettivo=modello_effettivo,
        priorita=proposta.priorita, urgenza=proposta.urgenza, scadenza=proposta.scadenza,
        budget_totale=budget_totale, budget_allocato=budget_allocato, allocazioni_budget=allocazioni_budget,
        budget_residuo_operativo=budget_operativo_residuo,
        budget_status=budget_status,
        richiede_chiarimento_budget=richiede_chiarimento_budget,
        pubblico=proposta.pubblico, canali=proposta.canali,
        capability_validate=capability_validate, capability_extra_scartate=capability_extra_scartate,
        task_proposti_validati=task_validati, kpi=proposta.kpi,
        rischi_valutati=[{"categoria": d.categoria, "severita": d.severita, "azione": d.azione, "motivo": d.motivo} for d in rischi_valutati],
        azione_rischio_aggregata=azione_aggregata, domande_aggiuntive=domande_aggiuntive,
        assunzioni=proposta.assunzioni, approvazioni_necessarie=proposta.approvazioni_necessarie,
        strategia_proposta=proposta.strategia_proposta, confidence=proposta.confidence,
        correzioni=correzioni,
    )
