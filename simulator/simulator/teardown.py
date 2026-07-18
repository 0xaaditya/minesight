# teardown.py — the `cleanup` CLI command. Every `run`/`sweep` invocation creates
# vehicles, zones, and (via the backend's own Traccar auto-registration) Traccar
# devices, and nothing ever cleans them up afterward — confirmed to accumulate across
# an entire session (124 stray "Sim "-prefixed zones, 551 stray Traccar devices) until
# done by hand. This automates exactly that by-hand cleanup:
#   1. close every zone named "Sim ..." (versioned close + audit CLOSE entry, same as
#      the dashboard's own zone editor — history preserved, just no longer current)
#   2. deactivate every vehicle whose asset-ID number is >= min_asset_number (the real
#      dev fleet's own asset IDs — S-052/EX-001/S-100/S-901-903/S-999 — are all under
#      1000; every simulator roster starts at 1000+, see identity.generate_roster)
#   3. delete the Traccar device for each newly- or already-deactivated one
import httpx


def cleanup(
    backend_api_url: str,
    traccar_api_url: str,
    traccar_api_user: str,
    traccar_api_password: str,
    min_asset_number: int,
) -> None:
    with httpx.Client(timeout=15.0) as client:
        _close_sim_zones(client, backend_api_url)
        uids = _deactivate_sim_vehicles(client, backend_api_url, min_asset_number)
        _delete_traccar_devices(client, traccar_api_url, traccar_api_user, traccar_api_password, uids)


def _close_sim_zones(client: httpx.Client, backend_api_url: str) -> None:
    zones = client.get(f"{backend_api_url}/zones").raise_for_status().json()
    sim_zones = [z for z in zones if z["name"].startswith("Sim ")]
    for z in sim_zones:
        client.delete(f"{backend_api_url}/zones/{z['zone_key']}").raise_for_status()
    print(f"closed {len(sim_zones)} Sim-prefixed zones")


def _deactivate_sim_vehicles(client: httpx.Client, backend_api_url: str, min_asset_number: int) -> set[str]:
    vehicles = client.get(f"{backend_api_url}/vehicles", params={"include_inactive": True}).raise_for_status().json()
    uids: set[str] = set()
    deactivated_now = 0
    for v in vehicles:
        parts = v["asset_id"].split("-")
        if len(parts) != 2 or not parts[-1].isdigit() or int(parts[-1]) < min_asset_number:
            continue  # not a simulator asset ID (or below the real dev fleet's own range)
        uids.add(v["traccar_unique_id"])
        if v.get("deactivated_at"):
            continue
        client.delete(f"{backend_api_url}/vehicles/{v['id']}").raise_for_status()
        deactivated_now += 1
    print(f"deactivated {deactivated_now} simulator vehicles (asset number >= {min_asset_number})")
    return uids


def _delete_traccar_devices(
    client: httpx.Client, traccar_api_url: str, user: str, password: str, uids: set[str]
) -> None:
    if not uids:
        return
    auth = (user, password)
    devices = client.get(f"{traccar_api_url}/devices", auth=auth).raise_for_status().json()
    deleted = 0
    for d in devices:
        if d["uniqueId"] in uids:
            client.delete(f"{traccar_api_url}/devices/{d['id']}", auth=auth).raise_for_status()
            deleted += 1
    print(f"deleted {deleted} Traccar devices")
