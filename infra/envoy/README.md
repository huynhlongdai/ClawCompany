# Runner mTLS edge

`runner-mtls.yaml.template` is an optional production edge for the v15 runner transport.
Render `${RUNNER_MTLS_PROXY_SHARED_SECRET}` into a private file, provision `proxy.crt`,
`proxy.key` and `runner-ca.pem`, then expose runners to port 8443 instead of the API port.
Envoy validates the client certificate and injects its SHA-256 fingerprint. FastAPI only
trusts that fingerprint when the matching proxy verification secret is present.

The shared proxy secret is defense-in-depth for the private proxy→API hop; it is **not**
a replacement for mTLS. Do not expose FastAPI's runner endpoints directly when
`RUNNER_MTLS_REQUIRED=true`.
