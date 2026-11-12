"""Auto-generates a unique title + hashtag-loaded description per clip.

Every clip gets its own title (varied by category + its own clip id, so two
clips are never identical) and a GTA 6 hashtag set, tuned a little per
platform (YouTube wants #Shorts, TikTok/Instagram want #fyp/#reels-style
tags). This only fires when the caller doesn't supply title/description
explicitly -- see server.py's post_clip.
"""

from __future__ import annotations

from openshorts.dashboard.categorize import BEST_MOMENTS, FUNNY, TIPS_TRICKS

TITLE_TEMPLATES: dict[str, list[str]] = {
    BEST_MOMENTS: [
        "GTA 6 Best Moment #{n} 🔥",
        "This GTA 6 Clip is INSANE 😱 #{n}",
        "GTA 6 Highlight You Can't Miss #{n}",
        "Most Epic GTA 6 Moment Yet #{n}",
        "GTA 6 Clutch Moment #{n}",
    ],
    FUNNY: [
        "GTA 6 Funniest Moment #{n} 😂",
        "GTA 6 Fail of the Day #{n}",
        "You Won't Stop Laughing - GTA 6 #{n}",
        "GTA 6 Chaos Moment #{n} 💀",
    ],
    TIPS_TRICKS: [
        "GTA 6 Tip You NEED to Know #{n}",
        "GTA 6 Pro Trick #{n}",
        "Do This in GTA 6 ASAP #{n}",
        "GTA 6 Hack Nobody Tells You #{n}",
    ],
    "unsorted": [
        "GTA 6 Clip #{n}",
        "GTA 6 Gameplay Moment #{n}",
        "GTA 6 Highlight #{n}",
    ],
}

# Popular/likely-to-trend GTA 6 hashtags, kept broad (game + genre + platform
# discovery tags) since there's no per-clip content understanding yet.
GTA6_HASHTAGS = [
    "#GTA6", "#GrandTheftAuto6", "#GTA6Clips", "#RockstarGames",
    "#GTAOnline", "#GTA6Gameplay", "#ViceCity", "#GTA", "#Gaming", "#Gamer",
]

PLATFORM_HASHTAGS = {
    "youtube": ["#Shorts"],
    "tiktok": ["#fyp", "#foryou", "#viral"],
    "instagram": ["#Reels", "#Explore"],
}


def build_title(clip: dict) -> str:
    templates = TITLE_TEMPLATES.get(clip["category"], TITLE_TEMPLATES["unsorted"])
    template = templates[clip["id"] % len(templates)]
    return template.format(n=clip["id"])


def build_description(clip: dict, platform: str) -> str:
    tags = GTA6_HASHTAGS + PLATFORM_HASHTAGS.get(platform, [])
    return build_title(clip) + "\n\n" + " ".join(tags)
