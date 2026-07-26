"""Tests for episode YAML schema validation."""

from pathlib import Path

from broadside.schema import Episode, TalkScene, CardScene, SilentScene, AdConcept


FIXTURES = Path(__file__).parent / "fixtures"


def test_load_three_scene_episode():
    ep = Episode.load(FIXTURES / "ep-test-three-scenes.yaml")
    assert ep.episode == "ep-test-three-scenes"
    assert ep.show in ("my-show", "bs")
    assert len(ep.scenes) == 3
    assert all(isinstance(s, TalkScene) for s in ep.scenes)


def test_load_full_episode():
    ep = Episode.load(FIXTURES / "ep-test-full.yaml")
    assert ep.episode == "ep-test-full"
    assert len(ep.scenes) == 9
    assert isinstance(ep.scenes[3], CardScene)
    assert isinstance(ep.scenes[5], SilentScene)
    assert ep.scenes[2].zoom is True
    assert ep.scenes[2].pause_after == 1.2


def test_talk_scenes_filter():
    ep = Episode.load(FIXTURES / "ep-test-full.yaml")
    talks = ep.talk_scenes
    assert all(isinstance(s, TalkScene) for s in talks)
    assert len(talks) == 7  # 9 scenes - 1 card - 1 silent


def test_word_count():
    ep = Episode.load(FIXTURES / "ep-test-three-scenes.yaml")
    assert ep.word_count > 0
    assert ep.word_count < 500


def test_estimated_duration():
    ep = Episode.load(FIXTURES / "ep-test-three-scenes.yaml")
    dur = ep.estimated_duration
    assert dur > 0
    assert dur < 300  # less than 5 minutes


def test_end_card():
    ep = Episode.load(FIXTURES / "ep-test-full.yaml")
    assert ep.end_card is not None
    assert ep.end_card.duration == 2.0
    assert any(s in ep.end_card.text for s in ("testshow", "thatsthebs"))


def test_ad_concept_load():
    concept = AdConcept.load(Path(__file__).parent.parent / "ads" / "concepts" / "blinkonce.yaml")
    assert concept.name in ("Example Product", "BlinkOnce Audiobooks")
    assert concept.style == "infomercial"
    assert concept.duration > 0
    assert len(concept.text_overlays) == 4
