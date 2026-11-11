from openshorts.dashboard.uploaders import instagram, tiktok, youtube

REGISTRY = {
    "youtube": youtube,
    "tiktok": tiktok,
    "instagram": instagram,
}
