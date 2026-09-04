import logging
import os
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from app.config import (ADMIN_EMAIL, ADMIN_PASSWORD, FRONTEND_URL, DEFAULT_ORG_ID,
                        JWT_SECRET, MASTER_KEY)
from app.db import db, client
from app.security import hash_password, verify_password, vault_available
from app.models import now_iso
from app.domains import (auth, org, users_mgmt, connections, engine, approvals, settings, budget, stats,
                         tenant, onboarding, knowledge, discovery, reel, video_connections, flyer,
                         social_publishing, meta_connections)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("actelya")

app = FastAPI(title="ACTELYA 3 API", version="0.1.0",
              description="Sistema operativo AI per marketing e vendite. Milestone 1 (SIMULAZIONE).")

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"app": "ACTELYA 3", "milestone": 1, "mode_default": "SIMULAZIONE"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "vault": vault_available()}


for module in (auth, org, users_mgmt, connections, engine, approvals, settings, budget, stats,
              tenant, onboarding, knowledge, discovery, reel, video_connections, flyer,
              social_publishing, meta_connections):
    api_router.include_router(module.router)
api_router.include_router(meta_connections.status_router)

from app.m2 import engine as m2_engine
api_router.include_router(m2_engine.router)

from app.brain import router as brain_router
api_router.include_router(brain_router.router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    if not JWT_SECRET:
        logger.warning("JWT_SECRET non configurato: autenticazione non disponibile.")
    if not vault_available():
        logger.warning("MASTER_KEY assente/non valida: gestione credenziali bloccata in modo sicuro.")

    await db.users.create_index("email", unique=True)
    await db.login_attempts.create_index("identifier")
    await db.executions.create_index("approval_id", unique=True, sparse=True)
    await db.goals.create_index("id", unique=True)
    await db.approvals.create_index("id", unique=True)
    await db.audit_logs.create_index("at")
    await db.organizations.create_index("id", unique=True)

    # Company knowledge (registration, onboarding, Fact Ledger, Discovery) — additive.
    await db.facts.create_index("id", unique=True)
    await db.facts.create_index([("organization_id", 1), ("field", 1), ("state", 1)])
    await db.discovery_runs.create_index("id", unique=True)
    await db.discovery_runs.create_index([("organization_id", 1), ("status", 1)])

    # Reel agent (Requesty reale + video Runway reale) — indici additivi, non distruttivi.
    await db.reel_projects.create_index("id", unique=True)
    await db.reel_projects.create_index([("organization_id", 1), ("status", 1)])
    await db.reel_video_jobs.create_index("id", unique=True)
    await db.reel_video_jobs.create_index([("reel_project_id", 1), ("version", 1)], unique=True)
    await db.video_connections.create_index("id", unique=True)
    await db.video_connections.create_index([("organization_id", 1), ("provider_type", 1)])
    await db.flyer_projects.create_index("id", unique=True)
    await db.flyer_projects.create_index([("organization_id", 1), ("status", 1)])
    await db.flyer_media_assets.create_index("id", unique=True)
    await db.flyer_media_assets.create_index([("organization_id", 1), ("flyer_project_id", 1)])
    await db.reel_content_versions.create_index("id", unique=True)
    await db.reel_content_versions.create_index([("reel_project_id", 1), ("version", 1)], unique=True)
    await db.flyer_content_versions.create_index("id", unique=True)
    await db.flyer_content_versions.create_index([("flyer_project_id", 1), ("version", 1)], unique=True)

    # Social Media Manager — memoria persistente e pubblicazione (indici additivi).
    await db.social_memory_entries.create_index("id", unique=True)
    await db.social_memory_entries.create_index([("organization_id", 1), ("type", 1), ("created_at", -1)])
    await db.social_publishing_packages.create_index("id", unique=True)
    await db.social_publishing_packages.create_index([("organization_id", 1), ("status", 1)])
    await db.social_publishing_packages.create_index([("status", 1), ("scheduled_at", 1)])
    await db.social_analytics_snapshots.create_index("id", unique=True)
    await db.social_analytics_snapshots.create_index([("publishing_package_id", 1), ("created_at", -1)])
    await db.social_analytics_snapshots.create_index([("organization_id", 1), ("source_kind", 1)])
    await db.meta_connections.create_index("id", unique=True)
    await db.meta_connections.create_index([("organization_id", 1), ("active", 1)])

    # Brain (CEO Agent) — persistenza audit trail e snapshot sessione
    await db.brain_audit_events.create_index("event_id", unique=True)
    await db.brain_audit_events.create_index([("organization_id", 1), ("session_id", 1)])
    await db.brain_audit_events.create_index([("organization_id", 1), ("plan_id", 1)])
    await db.brain_sessions.create_index("session_id", unique=True)
    await db.brain_sessions.create_index([("organization_id", 1), ("plan_id", 1)])

    # Milestone 2 (SIMULAZIONE) — indici additivi, non distruttivi
    from app.m2.models import create_m2_indexes
    await create_m2_indexes(db)

    # Milestone 2 — validazione contratti agenti allo startup (blocco sicuro se invalidi)
    from app.m2.agents_registry import validate_registry, ContractError, REGISTRY_VERSION
    try:
        cap_map = validate_registry()
        logger.info("Registro agenti M2 valido (%s): %s capability operative", REGISTRY_VERSION, len(cap_map))
    except ContractError as e:
        logger.error("Registro agenti M2 INVALIDO: %s — funzioni M2 in blocco sicuro", e)

    # Seed single organization
    if not await db.organizations.find_one({"id": DEFAULT_ORG_ID}):
        await db.organizations.insert_one({
            "id": DEFAULT_ORG_ID, "ragione_sociale": "", "nome_commerciale": "",
            "created_at": now_iso(), "updated_at": now_iso(), "change_history": [],
        })

    # Seed admin (hash only; credentials come from env, never source/logs)
    if ADMIN_EMAIL and ADMIN_PASSWORD:
        email = ADMIN_EMAIL.lower().strip()
        existing = await db.users.find_one({"email": email})
        if not existing:
            await db.users.insert_one({
                "email": email, "password_hash": hash_password(ADMIN_PASSWORD),
                "first_name": "Admin", "last_name": "ACTELYA", "role": "ADMIN",
                "active": True, "must_change_password": True,
                "organization_id": DEFAULT_ORG_ID, "permissions": [],
                "notification_prefs": {"email": True, "in_app": True},
                "last_login": None, "created_at": now_iso(), "updated_at": now_iso(),
                "created_by": "system", "updated_by": "system", "change_history": [],
            })
            logger.info("Admin seed creato per %s", email)
        elif os.environ.get("FORCE_RESET_ADMIN", "").lower() == "true" and \
                not verify_password(ADMIN_PASSWORD, existing.get("password_hash", "")):
            # Idempotent by default: only reset the admin password when explicitly forced.
            # This ensures user-initiated password changes survive restarts.
            await db.users.update_one({"email": email},
                                      {"$set": {"password_hash": hash_password(ADMIN_PASSWORD),
                                                "must_change_password": True}})
            logger.info("Admin password reset forzato per %s", email)

    await engine.recover_on_startup()
    engine.start_worker()

    await discovery.recover_on_startup()
    discovery.start_worker()

    # Milestone 2 — recovery idempotente protetto da lock (leader election)
    await m2_engine.recover_m2(db)

    # Social Media Manager — recovery + scheduler pubblicazioni (item 15/21: resiste a un riavvio del backend)
    await social_publishing.recover_on_startup()
    social_publishing.start_scheduler_worker()
    # Adapter reale Meta: la sola registrazione non abilita nulla da sola
    # (servono ANCHE REAL_EXTERNAL_ACTIONS + CONNECTOR_MODE='real' + una
    # connessione Meta configurata e verificata per l'organizzazione, vedi
    # domains/social_publishing.py::_meta_readiness) — ma senza di essa il
    # percorso reale resterebbe irraggiungibile anche a tutto il resto
    # correttamente configurato.
    social_publishing.register_meta_adapters()

    logger.info("ACTELYA 3 avviato.")


@app.on_event("shutdown")
async def shutdown():
    client.close()
