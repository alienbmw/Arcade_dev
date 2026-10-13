import hmac
import os
import re
from functools import wraps

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

# ---------- Configuración (variables de entorno en Render) ----------
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
ADMIN_KEY = os.environ["ADMIN_KEY"]
# Dominios que pueden usar la API, separados por coma. Ej:
# https://aliem-arcadedev.vercel.app,https://aliem-admin.vercel.app
ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

CORS(
    app,
    origins=ORIGINS,
    allow_headers=["Content-Type", "X-Admin-Key"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)

# Edita estas listas para cambiar categorías y tipos (el admin las lee de aquí)
CATEGORIES = ["Plataformas", "Acción", "Puzzle", "Arcade", "Aventura", "Otro"]
TYPES = {"gba": "GBA", "web": "Web", "pc": "PC"}

URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
# Las llaves antiguas (service_role) son JWT y también van en Authorization
if SUPABASE_KEY.startswith("eyJ"):
    SB_HEADERS["Authorization"] = f"Bearer {SUPABASE_KEY}"

PUBLIC_FIELDS = "id,title,description,category,type,cover_url,itch_url,play_url,created_at"


# ---------- Utilidades ----------
def sb(method, params=None, body=None):
    r = requests.request(
        method,
        f"{SUPABASE_URL}/rest/v1/games",
        params=params,
        json=body,
        headers=SB_HEADERS,
        timeout=15,
    )
    if not r.ok:
        app.logger.error("Supabase %s: %s", r.status_code, r.text)
        raise RuntimeError("supabase")
    return r.json() if r.text else []


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        sent = request.headers.get("X-Admin-Key", "")
        if not hmac.compare_digest(sent.encode(), ADMIN_KEY.encode()):
            return jsonify(error="Clave de admin incorrecta"), 401
        return fn(*args, **kwargs)

    return wrapper


def clean(data, partial=False):
    """Valida lo que manda el admin. Devuelve (datos, error)."""
    if not isinstance(data, dict):
        return None, "JSON inválido"
    out = {}

    for field, limit in (("title", 80), ("description", 500)):
        if field in data:
            value = str(data[field]).strip()
            if len(value) > limit:
                return None, f"{field} es muy largo (máximo {limit} caracteres)"
            out[field] = value

    if "category" in data:
        if data["category"] not in CATEGORIES:
            return None, "Categoría no válida"
        out["category"] = data["category"]

    if "type" in data:
        if data["type"] not in TYPES:
            return None, "Tipo no válido"
        out["type"] = data["type"]

    for field in ("cover_url", "itch_url", "play_url"):
        if field in data:
            value = str(data[field]).strip()
            if value and not (URL_RE.match(value) and len(value) <= 500):
                return None, f"{field} debe empezar con http:// o https://"
            out[field] = value

    if "published" in data:
        out["published"] = bool(data["published"])

    if not partial:
        for field in ("title", "category", "type"):
            if not out.get(field):
                return None, f"Falta el campo {field}"
    elif "title" in out and not out["title"]:
        return None, "El título no puede estar vacío"

    return out, None


@app.errorhandler(RuntimeError)
def db_error(_):
    return jsonify(error="No se pudo hablar con la base de datos"), 502


# ---------- Rutas públicas ----------
@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/meta")
def meta():
    return jsonify(
        categories=CATEGORIES,
        types=[{"id": k, "label": v} for k, v in TYPES.items()],
    )


@app.get("/games")
def public_games():
    rows = sb("GET", params={
        "select": PUBLIC_FIELDS,
        "published": "eq.true",
        "order": "created_at.desc",
    })
    return jsonify(rows)


# ---------- Rutas de admin (requieren X-Admin-Key) ----------
@app.get("/admin/games")
@admin_required
def admin_list():
    return jsonify(sb("GET", params={"select": "*", "order": "created_at.desc"}))


@app.post("/admin/games")
@admin_required
def admin_create():
    data, error = clean(request.get_json(silent=True))
    if error:
        return jsonify(error=error), 400
    return jsonify(sb("POST", body=data)[0]), 201


@app.put("/admin/games/<int:game_id>")
@admin_required
def admin_update(game_id):
    data, error = clean(request.get_json(silent=True), partial=True)
    if error:
        return jsonify(error=error), 400
    if not data:
        return jsonify(error="No hay nada que actualizar"), 400
    rows = sb("PATCH", params={"id": f"eq.{game_id}"}, body=data)
    if not rows:
        return jsonify(error="Juego no encontrado"), 404
    return jsonify(rows[0])


@app.delete("/admin/games/<int:game_id>")
@admin_required
def admin_delete(game_id):
    rows = sb("DELETE", params={"id": f"eq.{game_id}"})
    if not rows:
        return jsonify(error="Juego no encontrado"), 404
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
