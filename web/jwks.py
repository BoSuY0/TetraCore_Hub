"""JWKS endpoint and key management for JWT (RS/ES/EdDSA)."""

from typing import Dict, Any
import base64
import os
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/.well-known", tags=["jwks"])


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _parse_pem_public_key(pem: str) -> Dict[str, Any]:
    """Very light parser for RSA public key in PEM to JWKS (RS256).
    For EdDSA/ES256 this should be extended accordingly.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    try:
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
        if isinstance(pub, rsa.RSAPublicKey):
            numbers = pub.public_numbers()
            n = _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big"))
            e = _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big"))
            return {"kty": "RSA", "n": n, "e": e}
        else:
            # Non-RSA not yet implemented in this minimal JWKS
            raise ValueError("Unsupported key type for JWKS")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid public key: {e}")


@router.get("/jwks.json")
async def jwks() -> Dict[str, Any]:
    """Return JWKS set for current signing keys.
    Reads JWT_PUBLIC_KEY_PEM and JWT_KEY_ID from environment.
    """
    kid = os.getenv("JWT_KEY_ID")
    pub_pem = os.getenv("JWT_PUBLIC_KEY_PEM")
    alg = os.getenv("JWT_ALGORITHM", "RS256").upper()

    if not pub_pem:
        raise HTTPException(status_code=404, detail="JWKS not configured")

    jwk = _parse_pem_public_key(pub_pem)
    jwk.update(
        {
            "alg": alg,
            "use": "sig",
        }
    )
    if kid:
        jwk["kid"] = kid

    return {"keys": [jwk]}
