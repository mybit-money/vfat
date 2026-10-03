# Project Instructions

## VFAT

- Always use the VFAT MCP server (`mcp__vfat__*` tools) for VFAT data, discovery, analytics, status checks, quotes, and transaction preparation.
- Do not access VFAT through ad-hoc HTTP requests or scrape VFAT websites when an equivalent VFAT MCP tool is available.
- Prefer VFAT discovery tools before quote or transaction-preparation tools.
- Treat transaction data returned by VFAT MCP as unsigned: never request private keys or seed phrases, and never claim to sign or broadcast transactions.
