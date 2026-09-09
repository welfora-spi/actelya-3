import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import api from "@/lib/api";
import { ContentItemDeliverablePreview, ContentItemDeliverableItemsList } from "@/components/content-items/ContentItemDeliverablePreview";

// Dati reali (letti dal database, non reinventati) del deliverable prodotto
// dal piano plan-9d6c1fe7d3104729bb14: tre content_item distinti, due
// CONTESTATI dalla verifica semantica, uno no — usati qui per verificare la
// correzione senza ripetere alcuna generazione reale.
const ITEM_1 = {
  content_item_id: "content-58e18ff2b95d486dbc2d", content_type: "contenuto_informativo",
  status: "IN_ATTESA_APPROVAZIONE",
  content: {
    titolo: "La tecnologia al servizio del tuo business",
    corpo: "Nel mondo digitale di oggi, affidarsi a partner affidabili per i servizi informatici può fare la differenza.",
    cta: "Visita www.spitool.it",
    hashtags: ["#ServiziInformatici", "#SPITool"],
    varianti: ["Investire nei giusti servizi informatici significa investire nel futuro della tua attività."],
  },
  semantic_check: {
    status: "CONTESTATO",
    affermazioni_contestate: [{ categoria: "benefici_generici", campo: "corpo", frase: "affidabili", parola_chiave: "affidabili" }],
  },
};
const ITEM_2 = {
  content_item_id: "content-c79136099a964d2dac48", content_type: "contenuto_informativo",
  status: "IN_ATTESA_APPROVAZIONE",
  content: {
    titolo: "Tecnologia al servizio della tua operatività",
    corpo: "Quando i sistemi informatici funzionano in modo fluido, la tua attività può concentrarsi su ciò che conta davvero.",
    cta: "Visita www.spitool.it",
    hashtags: ["#ServiziInformatici", "#IT"],
    varianti: ["I sistemi informatici sono il motore invisibile di ogni attività moderna."],
  },
  semantic_check: {
    status: "CONTESTATO",
    affermazioni_contestate: [{ categoria: "benefici_generici", campo: "varianti[1]", frase: "Scegliere partner affidabili nel settore IT", parola_chiave: "affidabili" }],
  },
};
const ITEM_3 = {
  content_item_id: "content-a39b551603a74431a157", content_type: "contenuto_informativo",
  status: "IN_ATTESA_APPROVAZIONE",
  content: {
    titolo: "Tecnologia e persone: il giusto equilibrio",
    corpo: "Nel settore informatico, il vero valore non sta solo negli strumenti.",
    cta: "Visita www.spitool.it",
    hashtags: ["#ServiziInformatici", "#SPITool"],
    varianti: ["La tecnologia è uno strumento potente.", "Tecnologia sì, ma al servizio di chi?"],
  },
  semantic_check: { status: "OK", affermazioni_contestate: [] },
};

function realDeliverable(overrides = {}) {
  return {
    id: "deliv-2d82d60ef94f4958bb26", deliverable_type: "content_item", status: "COMPLETATO_CON_AVVISI",
    mode: "REALE", version: 1,
    warnings: [
      "3/3 bozze generate: in attesa di approvazione editoriale umana nel laboratorio Content Creator (non approvate automaticamente).",
      "2 contenuto/i con affermazioni contestate dalla verifica semantica (content-58e18ff2b95d486dbc2d, content-c79136099a964d2dac48): verificare prima di approvare.",
    ],
    content: {
      content_item_ids: ["content-58e18ff2b95d486dbc2d", "content-c79136099a964d2dac48", "content-a39b551603a74431a157"],
      mode: "REALE", requested_quantity: 3, produced_count: 3,
      contested_ids: ["content-58e18ff2b95d486dbc2d", "content-c79136099a964d2dac48"],
      items: [ITEM_1, ITEM_2, ITEM_3],
    },
    ...overrides,
  };
}

jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() }, formatApiError: (d) => d || "" }));

function renderAsAdmin(ui) {
  api.get.mockImplementation((url) => {
    if (url === "/auth/me") return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    return Promise.reject({ response: { status: 404 } });
  });
  return render(
    <MemoryRouter initialEntries={["/deliverable"]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>
  );
}

describe("ContentItemDeliverablePreview / ContentItemDeliverableItemsList", () => {
  it("mostra i tre contenuti come elementi distinti, mai le varianti come post separati", async () => {
    renderAsAdmin(<ContentItemDeliverablePreview d={realDeliverable()} />);
    expect(await screen.findByTestId(`content-item-${ITEM_1.content_item_id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`content-item-${ITEM_2.content_item_id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`content-item-${ITEM_3.content_item_id}`)).toBeInTheDocument();
    // titolo/corpo/CTA/hashtag leggibili
    expect(screen.getByText("La tecnologia al servizio del tuo business")).toBeInTheDocument();
    // ogni post ha la propria CTA leggibile (il conteggio esatto non si fa sul
    // testo intero della pagina: il dettaglio tecnico JSON collassato ripete
    // lo stesso testo e non va confuso con la presentazione principale)
    const item1 = screen.getByTestId(`content-item-${ITEM_1.content_item_id}`);
    const item2 = screen.getByTestId(`content-item-${ITEM_2.content_item_id}`);
    const item3 = screen.getByTestId(`content-item-${ITEM_3.content_item_id}`);
    expect(item1).toHaveTextContent("Visita www.spitool.it");
    expect(item2).toHaveTextContent("Visita www.spitool.it");
    expect(item3).toHaveTextContent("Visita www.spitool.it");
    // le varianti stanno in una sezione separata, sotto lo stesso elemento — non sono un quarto/quinto post
    expect(item1.querySelector('[data-testid="content-item-variants"]')).toBeInTheDocument();
  });

  it("segnala chiaramente lo stato editoriale e le contestazioni con il motivo leggibile", async () => {
    renderAsAdmin(<ContentItemDeliverablePreview d={realDeliverable()} />);
    const item1 = await screen.findByTestId(`content-item-${ITEM_1.content_item_id}`);
    expect(item1.querySelector(`[data-testid="content-item-status-${ITEM_1.content_item_id}"]`)).toHaveTextContent("IN_ATTESA_APPROVAZIONE");
    expect(item1.querySelector(`[data-testid="content-item-contested-badge-${ITEM_1.content_item_id}"]`)).toBeInTheDocument();
    expect(item1.querySelector('[data-testid="content-item-contested-notice"]')).toHaveTextContent("affidabili");

    const item3 = screen.getByTestId(`content-item-${ITEM_3.content_item_id}`);
    expect(item3.querySelector(`[data-testid="content-item-contested-badge-${ITEM_3.content_item_id}"]`)).not.toBeInTheDocument();
  });

  it("mostra un collegamento diretto al laboratorio per ogni contenuto, verso l'id corretto", async () => {
    renderAsAdmin(<ContentItemDeliverablePreview d={realDeliverable()} />);
    const link1 = await screen.findByTestId(`content-item-open-lab-${ITEM_1.content_item_id}`);
    expect(link1).toHaveAttribute("href", `/content-creator?item=${ITEM_1.content_item_id}`);
    const link3 = screen.getByTestId(`content-item-open-lab-${ITEM_3.content_item_id}`);
    expect(link3).toHaveAttribute("href", `/content-creator?item=${ITEM_3.content_item_id}`);
  });

  it("un content_item referenziato ma assente dal payload mostra un avviso esplicito, mai una scheda vuota/approvata", async () => {
    const d = realDeliverable();
    d.content = { ...d.content, content_item_ids: [...d.content.content_item_ids, "content-mancante"], items: [ITEM_1, ITEM_2, ITEM_3] };
    renderAsAdmin(<ContentItemDeliverablePreview d={d} />);
    const notice = await screen.findByTestId("content-item-unavailable");
    expect(notice).toHaveTextContent("content-mancante");
    expect(notice).toHaveTextContent("Non è né vuoto né approvato");
  });

  it("un item senza campo 'content' mostra un messaggio esplicito con lo stato, mai vuoto o completato", async () => {
    const d = realDeliverable();
    const bloccato = { ...ITEM_2, content: null, status: "BLOCCATO" };
    d.content = { ...d.content, items: [ITEM_1, bloccato, ITEM_3] };
    renderAsAdmin(<ContentItemDeliverablePreview d={d} />);
    const notice = await screen.findByTestId(`content-item-no-content-${ITEM_2.content_item_id}`);
    expect(notice).toHaveTextContent("BLOCCATO");
  });

  it("mantiene il JSON solo come dettaglio tecnico opzionale (collassato), non come presentazione principale", async () => {
    renderAsAdmin(<ContentItemDeliverablePreview d={realDeliverable()} />);
    await screen.findByTestId(`content-item-${ITEM_1.content_item_id}`);
    const details = document.querySelector("details");
    expect(details).toBeInTheDocument();
    expect(details.querySelector("summary")).toHaveTextContent("Dettaglio tecnico");
    expect(details.open).toBeFalsy();
  });

  it("il collegamento al laboratorio resta nascosto per un utente senza ruolo ADMIN", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: { id: "u2", email: "op@b.it", role: "OPERATORE", organization_id: "org-1" } } });
      return Promise.reject({ response: { status: 404 } });
    });
    render(
      <MemoryRouter initialEntries={["/deliverable"]}>
        <AuthProvider><ContentItemDeliverablePreview d={realDeliverable()} /></AuthProvider>
      </MemoryRouter>
    );
    await screen.findByTestId(`content-item-${ITEM_1.content_item_id}`);
    expect(screen.queryByTestId(`content-item-open-lab-${ITEM_1.content_item_id}`)).not.toBeInTheDocument();
  });

  it("ContentItemDeliverableItemsList (usata nel dettaglio piano) non duplica l'intestazione stato/modalità", async () => {
    renderAsAdmin(<ContentItemDeliverableItemsList d={realDeliverable()} />);
    await screen.findByTestId(`content-item-${ITEM_1.content_item_id}`);
    expect(screen.queryByTestId("deliverable-status-badge")).not.toBeInTheDocument();
  });
});
