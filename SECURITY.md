# Security

Compose Keeper can execute configured scripts and control containers. Treat its
shared key as a host-management credential. Keep it on a trusted network or behind
an HTTPS authenticating proxy. Use `secure_cookie: true` with HTTPS.

Do not include access keys, environment files, real project configuration or logs
in public issues. For a suspected vulnerability, use the repository's private
vulnerability reporting feature if the owner has enabled it; otherwise contact
the repository owner privately. No dedicated security response SLA is provided.
