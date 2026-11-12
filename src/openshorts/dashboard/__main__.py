import uvicorn

# 0.0.0.0 so this is reachable over Tailscale (and the LAN) as well as
# localhost -- there's no auth on this dashboard, so exposure is bounded by
# the OS firewall, not by what this binds to. A Windows Firewall rule scoped
# to the Private profile (which Tailscale's virtual adapter uses) allows
# inbound on this port; see the README's "Remote access" section.
DEFAULT_HOST = "0.0.0.0"


def main(host: str = DEFAULT_HOST, port: int = 8788) -> None:
    uvicorn.run("openshorts.dashboard.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
