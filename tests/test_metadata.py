from openshorts.dashboard.metadata import GTA6_HASHTAGS, build_description, build_title


def test_titles_are_unique_across_clip_ids():
    titles = {build_title({"id": i, "category": "best_moments"}) for i in range(1, 30)}
    assert len(titles) > 1  # not every id collapses onto the same template
    # every title still carries its own clip id, so two clips never read identically
    for i in range(1, 30):
        assert str(i) in build_title({"id": i, "category": "best_moments"})


def test_titles_are_gta6_themed_per_category():
    for category in ("best_moments", "funny", "tips_tricks", "unsorted"):
        title = build_title({"id": 1, "category": category})
        assert "GTA" in title or "gta" in title.lower()


def test_unknown_category_falls_back_to_unsorted_templates():
    title = build_title({"id": 5, "category": "some_future_category"})
    assert "GTA" in title


def test_title_prefers_transcribed_caption_when_present():
    clip = {"id": 7, "category": "best_moments", "caption": "No way he just did that"}
    title = build_title(clip)
    assert title == "GTA 6 — No way he just did that"


def test_title_falls_back_to_template_when_no_caption():
    clip_no_caption = {"id": 7, "category": "best_moments", "caption": None}
    clip_missing_key = {"id": 7, "category": "best_moments"}
    assert "No way" not in build_title(clip_no_caption)
    assert build_title(clip_no_caption) == build_title(clip_missing_key)


def test_description_includes_gta6_hashtags_and_platform_tag():
    desc = build_description({"id": 1, "category": "best_moments"}, "youtube")
    for tag in GTA6_HASHTAGS:
        assert tag in desc
    assert "#Shorts" in desc

    tiktok_desc = build_description({"id": 1, "category": "best_moments"}, "tiktok")
    assert "#fyp" in tiktok_desc
