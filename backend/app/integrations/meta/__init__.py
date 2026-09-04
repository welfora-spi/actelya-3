"""Meta Graph API — adapter reale per Facebook Page e Instagram Business
(DECISIONE UFFICIALE "100% REALE"). Nessun import da qui verso
app/brain/gateways/connector_gateway.py: e' il gateway a importare (in
domains/social_publishing.py, mai in connector_gateway.py stesso) le
funzioni di dispatch di questo pacchetto e a registrarle come adapter reale.

Nessuna chiamata di rete viene mai fatta all'import di questo pacchetto:
`requests` e' importato solo dentro le funzioni che lo usano davvero
(stesso principio di integrations/runway_gateway.py)."""
