"""Golden end-to-end OCP tests for ovos-skill-youtube-music.

Follows the ovoscope-based e2e pattern established in
ovos-skill-spotify (test/end2end/test_spotify_skill.py) and
ovos-skill-news (test/end2end/test_news_intents.py): a MiniCroft loaded
with only this skill's plugin id, driving the canonical OCP bus flow

    recognizer_loop:utterance
      -> ovos.common_play.query            (broadcast to OCP skills)
      -> ovos.common_play.query.response   (skill replies with results)

(see ovoscope.ocp module docstring for the full sequence).

The skill's search backend (``tutubo.ytmus.search_yt_music``, imported
into ``ovos_skill_youtube_music`` as ``search_yt_music``) is stubbed with
a deterministic in-memory fake so no live network call is made, mirroring
how spotify/news avoid live backend calls in their own e2e suites.
"""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ovoscope import get_minicroft
from ovos_bus_client.message import Message

SKILL_ID = "ovos-skill-youtube-music.openvoiceos"

# Minimal pipeline needed to exercise the OCP play flow in-process.
# ``ovos-ocp-pipeline-plugin`` (from the ``ovos-ocp-pipeline-plugin``
# test dependency) is what turns a "play X" utterance into the
# ovos.common_play.query broadcast; it is not part of ovoscope's
# DEFAULT_TEST_PIPELINE, so it must be requested explicitly.
OCP_TEST_PIPELINE = [
    "ovos-ocp-pipeline-plugin-high",
    "ovos-converse-pipeline-plugin",
    "ovos-ocp-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-high",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-low",
    "ovos-ocp-pipeline-plugin-low",
    "ovos-stop-pipeline-plugin-high",
    "ovos-stop-pipeline-plugin-medium",
]


def _minicroft(skill_id):
    return get_minicroft([skill_id], default_pipeline=OCP_TEST_PIPELINE, max_wait=60)


def _fake_track(title, artist, video_id="dQw4w9WgXcQ", length=210):
    """Build a deterministic stand-in for a tutubo MusicVideo/track result.

    Not an instance of tutubo's MusicVideo/MusicArtist/MusicAlbum/
    MusicPlaylist classes on purpose: the skill's isinstance() checks then
    fall through to the plain "video/song" branch, which is exactly the
    behaviour we want to exercise for a single deterministic music result.
    """
    return SimpleNamespace(
        watch_url=f"https://music.youtube.com/watch?v={video_id}",
        length=length,
        thumbnail_url="https://example.invalid/thumb.jpg",
        title=title,
        artist=artist,
    )


def _run_utterance(minicroft, utterance, lang="en-US", wait=3.0):
    """Emit a recognizer_loop:utterance and capture all bus traffic."""
    import time

    captured = []
    minicroft.bus.on("message", lambda m: captured.append(
        Message.deserialize(m) if isinstance(m, str) else m
    ))
    minicroft.bus.emit(Message("recognizer_loop:utterance",
                               data={"utterances": [utterance], "lang": lang}))
    time.sleep(wait)
    return captured


def _ocp_claims(messages, skill_id=SKILL_ID):
    """Return query.response messages from `skill_id` that carry results."""
    return [
        m for m in messages
        if m.msg_type == "ovos.common_play.query.response"
        and m.data.get("skill_id") == skill_id
        and m.data.get("results")
    ]


class TestYoutubeMusicSkillLoads(TestCase):
    """Verify the skill plugin loads and reaches READY state."""

    @classmethod
    def setUpClass(cls):
        cls.skill_id = SKILL_ID
        cls.minicroft = _minicroft(cls.skill_id)

    @classmethod
    def tearDownClass(cls):
        if cls.minicroft:
            cls.minicroft.stop()

    def test_skill_loaded(self):
        self.assertIn(self.skill_id, self.minicroft.plugin_skills)


class TestYoutubeMusicOCPClaims(TestCase):
    """Golden e2e rows: play-utterances this skill MUST claim via OCP."""

    @classmethod
    def setUpClass(cls):
        cls.skill_id = SKILL_ID
        cls.minicroft = _minicroft(cls.skill_id)

    @classmethod
    def tearDownClass(cls):
        if cls.minicroft:
            cls.minicroft.stop()

    def _assert_claimed(self, utterance, expected_title=None, expected_artist=None):
        fake_results = [_fake_track("Bohemian Rhapsody", "Queen")]
        with patch("ovos_skill_youtube_music.search_yt_music",
                   return_value=fake_results) as mocked:
            messages = _run_utterance(self.minicroft, utterance)

        # backend was actually invoked -- proves the intent/vocab matched
        # and the skill's OCP search handler ran (no live network call made)
        self.assertTrue(mocked.called,
                        f"search backend not invoked for utterance: {utterance!r}")

        claims = _ocp_claims(messages)
        self.assertTrue(claims,
                        f"no ovos.common_play.query.response with results "
                        f"from {self.skill_id} for utterance: {utterance!r}")

        all_results = [r for c in claims for r in c.data["results"]]
        self.assertTrue(all_results)
        for r in all_results:
            self.assertEqual(r.get("skill_id"), self.skill_id)

        if expected_title:
            self.assertTrue(
                any(expected_title.lower() in (r.get("title") or "").lower()
                   for r in all_results),
                f"expected title {expected_title!r} not in results: {all_results}"
            )

    def test_play_artist_on_youtube_music(self):
        self._assert_claimed("play queen on youtube music")

    def test_play_song_on_youtube_music(self):
        self._assert_claimed("play bohemian rhapsody on youtube music",
                             expected_title="Bohemian Rhapsody")

    def test_play_music_video_on_youtube_music(self):
        self._assert_claimed("play some jazz on youtube music")

    def test_play_youtube_music_generic(self):
        self._assert_claimed("play frank sinatra on youtube music")

    def test_youtube_music_explicit_keyword(self):
        self._assert_claimed("play zz top on you tube music")


class TestYoutubeMusicCrossMediaNegatives(TestCase):
    """Utterances that clearly belong to OTHER media skills / OCP sources.

    KNOWN LIMITATION (documented, not fixed -- see STEP 2 defect notes in
    the PR description): only this skill is loaded in the MiniCroft, so
    OCP's skill-selection arbitration (which normally lets a Spotify /
    YouTube-video / podcast skill outbid this one) cannot run here -- this
    skill is the sole OCP search candidate and OCP always queries every
    loaded candidate for every play utterance, so ``search_yt_music`` WILL
    be invoked even for phrases naming another service. That is expected,
    correct multi-skill OCP behaviour (search broadcasts to all, the
    ``ovos-ocp-pipeline-plugin`` picks the winner by confidence) and is not
    a bug in this skill.

    What IS a property of *this skill alone*, and what these tests assert:
    it must not award its "explicitly requested youtube" confidence bonus
    (see ``search_youtube_music``'s ``youtube`` voc-match branch, +50) to
    phrases that name a different service. Confidence for such phrases must
    stay strictly below the confidence for an equivalent phrase that
    explicitly asks for "youtube music".
    """

    @classmethod
    def setUpClass(cls):
        cls.skill_id = SKILL_ID
        cls.minicroft = _minicroft(cls.skill_id)

    @classmethod
    def tearDownClass(cls):
        if cls.minicroft:
            cls.minicroft.stop()

    def _best_confidence(self, utterance):
        # Deliberately imperfect title/artist match (not "Queen"/"Queen")
        # so the fuzzy-match component of calc_score doesn't itself
        # saturate to the 0-100 confidence ceiling and mask the +50
        # "explicit youtube" voc-match bonus being compared here.
        fake_results = [_fake_track("Some Random Video Title", "Not Queen")]
        with patch("ovos_skill_youtube_music.search_yt_music",
                   return_value=fake_results):
            messages = _run_utterance(self.minicroft, utterance)
        claims = _ocp_claims(messages)
        all_results = [r for c in claims for r in c.data["results"]]
        self.assertTrue(all_results, f"no results captured for {utterance!r}")
        return max(r.get("match_confidence", 0) for r in all_results)

    def _assert_lower_confidence_than_explicit_youtube_music(self, utterance):
        baseline = self._best_confidence("play queen on youtube music")
        other = self._best_confidence(utterance)
        self.assertLess(
            other, baseline,
            f"{utterance!r} scored {other}, not below the explicit "
            f"'on youtube music' baseline of {baseline} -- the youtube "
            f"voc-match bonus may be leaking into an unrelated-service phrase"
        )

    def test_play_on_spotify_scores_lower_than_youtube_music(self):
        self._assert_lower_confidence_than_explicit_youtube_music(
            "play queen on spotify")

    def test_play_video_on_youtube_scores_lower_than_youtube_music(self):
        # plain "youtube" (video) requests are handled by the youtube video
        # skill, not youtube *music* -- the "youtube" voc alone (without
        # "music") must not earn the same bonus as the explicit
        # "youtube music"/"you tube music" vocab match, see
        # locale/en-US/youtube_music_skill.voc
        self._assert_lower_confidence_than_explicit_youtube_music(
            "play queen video on youtube")

    def test_play_podcast_scores_lower_than_youtube_music(self):
        self._assert_lower_confidence_than_explicit_youtube_music(
            "play the queen podcast on spotify")


class TestYoutubeMusicCrossDomainNegatives(TestCase):
    """Utterances belonging to entirely unrelated domains: must not be claimed."""

    @classmethod
    def setUpClass(cls):
        cls.skill_id = SKILL_ID
        cls.minicroft = _minicroft(cls.skill_id)

    @classmethod
    def tearDownClass(cls):
        if cls.minicroft:
            cls.minicroft.stop()

    def _assert_not_claimed(self, utterance):
        with patch("ovos_skill_youtube_music.search_yt_music") as mocked:
            mocked.return_value = [_fake_track("irrelevant", "irrelevant")]
            messages = _run_utterance(self.minicroft, utterance, wait=2.0)
        claims = _ocp_claims(messages)
        self.assertFalse(
            claims,
            f"unrelated-domain utterance was claimed by {self.skill_id}: "
            f"{utterance!r} -> {claims}"
        )

    def test_weather(self):
        self._assert_not_claimed("what is the weather today")

    def test_alarm(self):
        self._assert_not_claimed("set an alarm for 7 am")

    def test_timer(self):
        self._assert_not_claimed("set a timer for 10 minutes")

    def test_math(self):
        self._assert_not_claimed("what is two plus two")

    def test_date(self):
        self._assert_not_claimed("what is today's date")
