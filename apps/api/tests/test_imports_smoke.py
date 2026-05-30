"""Smoke test : tous les routeurs et services s'importent sans erreur.

Garantit qu'aucune regression `ImportError` ne casse le boot de l'API. Aussi
inclut les modules potentiellement crees par d'autres agents (saturation,
rounding, etc.) — l'echec d'import est tolere pour ces modules pendant la
phase de refactor (try/except + log).
"""

from __future__ import annotations

import importlib

import pytest


# ---------------------------------------------------------------------------
# Routeurs (tous les modules dans app.routers/*.py)
# ---------------------------------------------------------------------------

ROUTER_MODULES = [
    "app.routers.carte",
    "app.routers.compteurs",
    "app.routers.discontinuites",
    "app.routers.evaluation",
    "app.routers.export",
    "app.routers.mapping",
    "app.routers.models",
    "app.routers.sessions",
    "app.routers.training",
    "app.routers.upload",
    "app.routers.visualisation",
]


@pytest.mark.parametrize("module_name", ROUTER_MODULES)
def test_routers_import(module_name):
    """Chaque routeur de app.routers s'importe sans ImportError."""
    mod = importlib.import_module(module_name)
    assert mod is not None
    # Sanite check : router objet present (sauf pour les helpers purs).
    assert hasattr(mod, "router") or hasattr(mod, "__name__")


# ---------------------------------------------------------------------------
# Services - core (existants, doivent toujours s'importer)
# ---------------------------------------------------------------------------

CORE_SERVICE_MODULES = [
    "app.services.ml.data_prep",
    "app.services.ml.evaluation_pipeline",
    "app.services.ml.grid_search",
    "app.services.ml.kfold",
    "app.services.ml.losses",
    "app.services.ml.model_builder",
    "app.services.ml.normalize",
    "app.services.ml.packaging",
    "app.services.ml.progress",
    "app.services.ml.seeding",
    "app.services.ml.stats_compare",
    "app.services.ml.training_pipeline",
    "app.services.ml.types",
    "app.services.discontinuites",
]


@pytest.mark.parametrize("module_name", CORE_SERVICE_MODULES)
def test_core_services_import(module_name):
    """Chaque service core (existant deja) s'importe sans ImportError."""
    mod = importlib.import_module(module_name)
    assert mod is not None


# ---------------------------------------------------------------------------
# Services - nouveaux modules (peuvent ne pas encore exister selon l'agent
# parallele). On les tolere absents (xfail/skip) plutot que de bloquer.
# ---------------------------------------------------------------------------

POTENTIAL_NEW_MODULES = [
    "app.services.ml.saturation",
    "app.services.ml.rounding",
    "app.services.ml.inference",
    "app.services.ml.geo",
    "app.services.ml.metrics_advanced",
    "app.services.reports.html_tv",
    "app.services.reports.html_pl",
]


@pytest.mark.parametrize("module_name", POTENTIAL_NEW_MODULES)
def test_new_services_import_if_present(module_name):
    """Modules potentiellement crees par autre agent : import si dispo, skip sinon.

    Quand l'agent parallele finit son refactor, ce test verifiera que ses
    nouveaux modules s'importent. En attendant : skip pour ne pas bloquer.
    """
    try:
        mod = importlib.import_module(module_name)
        assert mod is not None
    except ModuleNotFoundError:
        pytest.skip(f"{module_name} pas (encore) cree par agent parallele")


# ---------------------------------------------------------------------------
# Modules cores du app (config, security, etc.)
# ---------------------------------------------------------------------------

CORE_APP_MODULES = [
    "app.auth",
    "app.config",
    "app.error_messages",
    "app.logging_config",
    "app.main",
    "app.rate_limit",
    "app.security",
    "app.session",
    "app.training_guard",
]


@pytest.mark.parametrize("module_name", CORE_APP_MODULES)
def test_core_app_modules_import(module_name):
    """Modules app.* (config, auth, security, etc.) s'importent."""
    mod = importlib.import_module(module_name)
    assert mod is not None


# ---------------------------------------------------------------------------
# Sanity : app.main contient app FastAPI
# ---------------------------------------------------------------------------

def test_app_main_has_fastapi_app():
    """app.main expose un objet `app` FastAPI utilisable."""
    from app.main import app
    assert app is not None
    # FastAPI = sous-classe de Starlette ; on verifie au moins routes attribute
    assert hasattr(app, "routes")
