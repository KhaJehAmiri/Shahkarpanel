import click
import logging
import os
import ssl

import uvicorn
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from config import (DEBUG, UVICORN_HOST, UVICORN_PORT, UVICORN_SSL_CERTFILE,
                    UVICORN_SSL_KEYFILE, UVICORN_SSL_CA_TYPE, UVICORN_UDS,
                    UVICORN_WORKERS)

logger = logging.getLogger("uvicorn.error")


def validate_cert_and_key(cert_file_path, key_file_path, ca_type):
    if ca_type == "private":
        logger.warning(f"""
{click.style('IMPORTANT!', blink=True, bold=True, fg="yellow")} 
You're running Shahkar with: {click.style('UVICORN_SSL_CA_TYPE', italic=True, fg="magenta")}: {click.style(f'{ca_type}', bold=True, fg="yellow")}. 
Self-signed CAs are useful in testing or internal use cases, they’re not suitable for secure public internet communications.
        """)
        return

    if not os.path.isfile(cert_file_path):
        raise ValueError(f"SSL certificate file '{cert_file_path}' does not exist.")
    if not os.path.isfile(key_file_path):
        raise ValueError(f"SSL key file '{key_file_path}' does not exist.")

    try:
        context = ssl.create_default_context()
        context.load_cert_chain(certfile=cert_file_path, keyfile=key_file_path)
    except ssl.SSLError as e:
        raise ValueError(f"SSL Error: {e}")

    try:
        with open(cert_file_path, 'rb') as cert_file:
            cert_data = cert_file.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())

        if cert.issuer == cert.subject:
            raise ValueError("The certificate is self-signed and not issued by a trusted CA.")

    except Exception as e:
        raise ValueError(f"Certificate verification failed: {e}")


def _http_workers() -> int:
    """Multi-process HTTP is only safe when this process does not own Xray/scheduler."""
    if DEBUG:
        return 1
    role = (os.environ.get("SHAHKAR_ROLE") or "all").strip().lower()
    if role != "api":
        return 1
    return max(1, min(int(UVICORN_WORKERS or 1), 8))


if __name__ == "__main__":
    bind_args = {}
    ssl_ca_type = UVICORN_SSL_CA_TYPE
    if ssl_ca_type not in ["public", "private"]:
        ssl_ca_type = "public"

    if UVICORN_SSL_CERTFILE and UVICORN_SSL_KEYFILE and ssl_ca_type:
        validate_cert_and_key(UVICORN_SSL_CERTFILE, UVICORN_SSL_KEYFILE, ssl_ca_type)

        bind_args['ssl_certfile'] = UVICORN_SSL_CERTFILE
        bind_args['ssl_keyfile'] = UVICORN_SSL_KEYFILE

        if UVICORN_UDS:
            bind_args['uds'] = UVICORN_UDS
        else:
            bind_args['host'] = UVICORN_HOST
            bind_args['port'] = UVICORN_PORT

    else:
        if UVICORN_UDS:
            bind_args['uds'] = UVICORN_UDS
        else:
            bind_args['host'] = UVICORN_HOST
            bind_args['port'] = UVICORN_PORT
            if UVICORN_HOST in ("0.0.0.0", "::"):
                logger.info(
                    "Shahkar listening on %s:%s (no TLS — use a reverse proxy for HTTPS in production).",
                    UVICORN_HOST,
                    UVICORN_PORT,
                )
            else:
                logger.warning(
                    "Shahkar listening on %s:%s without TLS. Set UVICORN_HOST=0.0.0.0 for external access "
                    "or terminate TLS with Nginx/Caddy.",
                    UVICORN_HOST,
                    UVICORN_PORT,
                )

    if DEBUG:
        bind_args['uds'] = None
        bind_args['host'] = '0.0.0.0'

    workers = _http_workers()
    logger.info("uvicorn workers=%s role=%s", workers, os.environ.get("SHAHKAR_ROLE") or "all")

    try:
        uvicorn.run(
            "app:app",
            **bind_args,
            workers=workers,
            reload=DEBUG and workers == 1,
            log_level=logging.DEBUG if DEBUG else logging.INFO
        )
    except FileNotFoundError:  # to prevent error on removing unix sock
        pass
