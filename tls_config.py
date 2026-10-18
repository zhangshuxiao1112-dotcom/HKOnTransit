"""Verified TLS using native OS trust, public roots and optional managed CA files."""
import os
import ssl
import certifi
import truststore


def ssl_context():
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Keep public roots available on Python installations with incomplete stores.
    ctx.load_verify_locations(cafile=certifi.where())
    for variable in ('HKONTRANSIT_CA_FILE', 'SSL_CERT_FILE'):
        path = os.environ.get(variable)
        if path:
            try:
                ctx.load_verify_locations(cafile=path)
            except (OSError, ssl.SSLError) as error:
                raise RuntimeError(f'{variable} must point to a readable PEM CA certificate bundle.') from error
    if os.environ.get('SSL_CERT_DIR'):
        ctx.load_verify_locations(capath=os.environ['SSL_CERT_DIR'])
    return ctx
