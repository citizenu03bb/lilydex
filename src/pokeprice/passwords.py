"""Password hashing and account creation for the web application's users."""

import hashlib
import hmac
import secrets

from .inventory import now


# OWASP scrypt minimum in its low-memory form (16 MiB per hash, five passes):
# the small server stays usable when several logins arrive at once.
SCRYPT = {"n": 2**14, "r": 8, "p": 5}
# Bare "salt:key" hashes written before October 2026, upgraded at login.
LEGACY_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def scrypt_key(password, salt, n, r, p):
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=256 * r * n, dklen=32
    )


def password_hash(password):
    salt = secrets.token_bytes(16)
    params = ",".join(f"{k}={v}" for k, v in SCRYPT.items())
    return f"scrypt${params}${salt.hex()}${scrypt_key(password, salt, **SCRYPT).hex()}"


def hash_parts(encoded):
    if "$" not in encoded:
        salt, key = encoded.split(":")
        return LEGACY_SCRYPT, salt, key
    algorithm, params, salt, key = encoded.split("$")
    if algorithm != "scrypt":
        raise ValueError("Format de mot de passe inconnu.")
    cost = {k: int(v) for k, v in (item.split("=") for item in params.split(","))}
    return cost, salt, key


def password_valid(password, encoded):
    params, salt, key = hash_parts(encoded)
    actual = scrypt_key(password, bytes.fromhex(salt), **params)
    return hmac.compare_digest(actual, bytes.fromhex(key))


def password_outdated(encoded):
    return hash_parts(encoded)[0] != SCRYPT


def has_admin(db):
    return bool(db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone())


def add_user(db, values):
    import uuid

    user = {"id": str(uuid.uuid4()), "username": values.username, "role": values.role}
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (
            user["id"],
            user["username"],
            password_hash(values.password),
            user["role"],
            now(),
        ),
    )
    return user
