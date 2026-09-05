"""Lead Generation — deduplica ed entity resolution deterministica e
spiegabile.

Due livelli, MAI confusi fra loro:
- duplicati ESATTI (stessa chiave forte: dominio/email/telefono normalizzati,
  o stesso identificativo esterno) -> merge proponibile, sempre tracciato;
- duplicati PROBABILI (nome azienda simile, stessa citta') -> SEMPRE
  'review manuale', mai un merge automatico, indipendentemente da quanto
  alta sia la similarita' (vincolo esplicito: non fondere persone o aziende
  sulla sola somiglianza del nome).

Il merge non sceglie mai silenziosamente un valore quando i due record sono
in disaccordo su uno stesso campo: lo marca CONTRADDITTORIO e lascia la
decisione a un umano. Ogni merge e' registrato con motivo e regola
applicata, cosi' la provenienza resta sempre ricostruibile."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

FUZZY_NOME_SOGLIA = 0.86
CHIAVI_FORTI = ("dominio", "email", "telefono")


def _valore(record: dict, campo: str) -> Optional[str]:
    cella = record.get(campo)
    if not isinstance(cella, dict):
        return None
    return cella.get("value") or None


def find_exact_duplicates(records: list[dict]) -> list[dict]:
    """Raggruppa per chiave forte normalizzata (dominio/email/telefono):
    O(n), nessun confronto pairwise. Un identificativo esterno condiviso
    (external_ids) e' trattato allo stesso modo, quando presente."""
    gruppi: dict[tuple[str, str], list[str]] = {}
    for r in records:
        rid = r.get("id")
        if not rid:
            continue
        for campo in CHIAVI_FORTI:
            valore = _valore(r, campo)
            if valore:
                gruppi.setdefault((campo, valore), []).append(rid)
        for ext in r.get("external_ids") or []:
            if ext:
                gruppi.setdefault(("external_id", str(ext)), []).append(rid)
    return [
        {"tipo": tipo, "chiave": valore, "record_ids": sorted(set(ids)), "match_type": "ESATTO"}
        for (tipo, valore), ids in gruppi.items() if len(set(ids)) > 1
    ]


def _similarita_nome(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_probable_duplicates(records: list[dict], *, soglia: float = FUZZY_NOME_SOGLIA) -> list[dict]:
    """Confronta solo record con la STESSA citta' dichiarata (riduce i
    confronti pairwise da O(n^2) sull'intero dataset a O(n^2) per singola
    citta'): sufficiente per import di dimensioni tipiche di una campagna.
    Ritorna SEMPRE 'REVIEW_MANUALE': nessun esito di questa funzione e' mai
    applicabile automaticamente."""
    per_citta: dict[str, list[tuple[str, str]]] = {}
    for r in records:
        rid = r.get("id")
        nome = _valore(r, "ragione_sociale")
        if not rid or not nome:
            continue
        citta = _valore(r, "citta") or ""
        per_citta.setdefault(citta, []).append((rid, nome))

    risultati = []
    for citta, gruppo in per_citta.items():
        for i in range(len(gruppo)):
            for j in range(i + 1, len(gruppo)):
                id_a, nome_a = gruppo[i]
                id_b, nome_b = gruppo[j]
                sim = _similarita_nome(nome_a, nome_b)
                if sim >= soglia:
                    risultati.append({
                        "tipo": "nome_simile", "match_type": "PROBABILE", "esito": "REVIEW_MANUALE",
                        "record_a": id_a, "record_b": id_b, "similarita": round(sim, 3), "citta": citta or None,
                    })
    return risultati


@dataclass
class MergeResult:
    merged: dict
    contraddizioni: list[str] = field(default_factory=list)
    campi_adottati: list[str] = field(default_factory=list)

    def come_dict(self) -> dict:
        return {"merged": self.merged, "contraddizioni": self.contraddizioni, "campi_adottati": self.campi_adottati}


def apply_merge(primario: dict, secondario: dict, *, actor: str, now_iso: str) -> MergeResult:
    """Unisce 'secondario' in 'primario' (che resta il record superstite):
    - campo assente nel primario ma presente nel secondario -> adottato,
      method preservato (mai declassato a un metodo piu' forte di quello
      reale);
    - campo presente in ENTRAMBI con lo STESSO valore -> resta invariato;
    - campo presente in entrambi con valore DIVERSO -> CONTRADDITTORIO,
      il valore del primario resta quello attivo ma la discrepanza e'
      registrata esplicitamente, mai risolta in silenzio.
    Non modifica gli oggetti originali (ritorna una copia)."""
    unito = {k: dict(v) if isinstance(v, dict) else v for k, v in primario.items()}
    contraddizioni: list[str] = []
    adottati: list[str] = []

    for campo, cella_sec in secondario.items():
        if not isinstance(cella_sec, dict) or "value" not in cella_sec:
            continue
        valore_sec = cella_sec.get("value")
        if not valore_sec:
            continue
        cella_prim = unito.get(campo)
        valore_prim = (cella_prim or {}).get("value") if isinstance(cella_prim, dict) else None
        if not valore_prim:
            unito[campo] = dict(cella_sec)
            adottati.append(campo)
        elif str(valore_prim).strip().lower() != str(valore_sec).strip().lower():
            unito[campo] = {**cella_prim, "method": "CONTRADDITTORIO",
                            "conflicting_value": valore_sec, "conflicting_source_id": secondario.get("id")}
            contraddizioni.append(campo)

    cronologia = list(unito.get("merge_history") or [])
    cronologia.append({
        "at": now_iso, "by": actor, "merged_record_id": secondario.get("id"),
        "campi_adottati": adottati, "contraddizioni": contraddizioni,
    })
    unito["merge_history"] = cronologia
    unito["merged_from_ids"] = list(dict.fromkeys((unito.get("merged_from_ids") or []) + [secondario.get("id")]))

    return MergeResult(merged=unito, contraddizioni=contraddizioni, campi_adottati=adottati)
