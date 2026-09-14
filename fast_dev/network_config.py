"""Keep loopback traffic local while preserving external proxy routing."""
import os
from urllib.request import getproxies


def configure_loopback_bypass():
    # On Windows urllib falls back to registry proxies only when there are NO
    # proxy environment entries. Adding NO_PROXY alone would disable that
    # fallback, so preserve the effective proxy endpoints first.
    effective = getproxies()
    for scheme in ('http', 'https', 'all'):
        if effective.get(scheme):
            os.environ.setdefault(scheme.upper() + '_PROXY', effective[scheme])

    entries = []
    for value in (effective.get('no', ''), os.environ.get('NO_PROXY', ''),
                  os.environ.get('no_proxy', ''), 'localhost,127.0.0.1,::1'):
        for entry in value.split(','):
            entry = entry.strip()
            if entry and entry.lower() not in {x.lower() for x in entries}:
                entries.append(entry)
    # Both forms: HTTP clients differ in which spelling takes precedence.
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = ','.join(entries)

