No Martha's Vineyard-specific connector code exists yet (both live sources
-- Oak Bluffs/Tisbury AgendaCenter and MA OCPF -- reuse connectors already
covered by `core/tests/` generically, plus `core/tests/test_ocpf.py`'s
per-allowlist coverage). This directory exists so
`cities/marthas_vineyard/docker-compose.yml`'s test-mount pattern matches
every other city fork; add tests here if/when this fork gets its own
bespoke connector (e.g. for West Tisbury's legacy PHP calendar or Dukes
County's EvoGov platform -- see seed_sources.py's module docstring).
