import api, { handleAuthRetry, setSessionExpiredHandler } from "@/lib/api";

function make401(url) {
  return { config: { url }, response: { status: 401 } };
}

describe("handleAuthRetry (recupero sessione su 401)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    setSessionExpiredHandler(null);
  });

  it("refresh riuscito: ripete la richiesta originale una sola volta", async () => {
    const postSpy = jest.spyOn(api, "post").mockResolvedValue({ data: {} });
    const requestSpy = jest.spyOn(api, "request").mockResolvedValue({ data: { ok: true } });
    const err = make401("/m2/plans/plan-1");

    const result = await handleAuthRetry(err);

    expect(postSpy).toHaveBeenCalledTimes(1);
    expect(postSpy).toHaveBeenCalledWith("/auth/refresh");
    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith(err.config);
    expect(result).toEqual({ data: { ok: true } });
  });

  it("più 401 contemporanei condividono un solo tentativo di refresh", async () => {
    let resolveRefresh;
    const postSpy = jest.spyOn(api, "post").mockImplementation(
      () => new Promise((resolve) => { resolveRefresh = resolve; })
    );
    const requestSpy = jest.spyOn(api, "request").mockResolvedValue({ data: {} });

    const p1 = handleAuthRetry(make401("/m2/plans/plan-1"));
    const p2 = handleAuthRetry(make401("/m2/plans/plan-1/deliverables"));
    const p3 = handleAuthRetry(make401("/m2/plans/plan-1/reviews"));

    resolveRefresh({ data: {} });
    await Promise.all([p1, p2, p3]);

    expect(postSpy).toHaveBeenCalledTimes(1); // un solo refresh condiviso
    expect(requestSpy).toHaveBeenCalledTimes(3); // ogni richiesta originale ripetuta
  });

  it("refresh fallito: nessun loop, errore originale propagato, sessione segnalata scaduta", async () => {
    jest.spyOn(api, "post").mockRejectedValue({ response: { status: 401 } });
    const requestSpy = jest.spyOn(api, "request");
    const onExpired = jest.fn();
    setSessionExpiredHandler(onExpired);
    const err = make401("/m2/plans/plan-1");

    await expect(handleAuthRetry(err)).rejects.toBe(err);

    expect(requestSpy).not.toHaveBeenCalled(); // nessun retry dopo un refresh fallito
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("esclude login e refresh dal recupero (evita il loop)", async () => {
    const postSpy = jest.spyOn(api, "post");

    await expect(handleAuthRetry(make401("/auth/login"))).rejects.toBeDefined();
    await expect(handleAuthRetry(make401("/auth/refresh"))).rejects.toBeDefined();

    expect(postSpy).not.toHaveBeenCalled();
  });

  it("errori diversi da 401 restano invariati (nessuna regressione)", async () => {
    const postSpy = jest.spyOn(api, "post");
    const requestSpy = jest.spyOn(api, "request");
    const err500 = { config: { url: "/m2/plans/plan-1" }, response: { status: 500 } };
    const errNetwork = { config: { url: "/m2/plans/plan-1" }, response: undefined };

    await expect(handleAuthRetry(err500)).rejects.toBe(err500);
    await expect(handleAuthRetry(errNetwork)).rejects.toBe(errNetwork);

    expect(postSpy).not.toHaveBeenCalled();
    expect(requestSpy).not.toHaveBeenCalled();
  });
});
