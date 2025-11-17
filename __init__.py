from os.path import join, dirname
from typing import Iterable, Union
import re

from ovos_utils import classproperty
from ovos_utils.ocp import MediaType, PlaybackType, Playlist, MediaEntry
from ovos_utils.parse import fuzzy_match, MatchStrategy
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.decorators import ocp_search
from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill
from tutubo.ytmus import search_yt_music, MusicVideo, MusicAlbum, MusicPlaylist, MusicArtist


class YoutubeMusicSkill(OVOSCommonPlaybackSkill):
    def __init__(self, *args, **kwargs):
        super().__init__(supported_media=[MediaType.MUSIC, MediaType.GENERIC],
                         skill_icon=join(dirname(__file__), "res", "ytmus.png"),
                         skill_voc_filename="youtube_music_skill",
                         *args, **kwargs)

    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=True,
                                   network_before_load=True,
                                   gui_before_load=False,
                                   requires_internet=True,
                                   requires_network=True,
                                   requires_gui=False,
                                   no_internet_fallback=False,
                                   no_network_fallback=False,
                                   no_gui_fallback=True)

    def search_yt(self, phrase):
        return search_yt_music(phrase, as_dict=False)

    # Helper function to try and get max resolution thumbnail
    def _get_high_res_thumbnail(self, url):
        """
        Replaces a lower resolution thumbnail ID in the URL with 'maxresdefault'.
        If no known low-resolution ID is found, the original URL is returned (fallback).
        Also updates googleusercontent profile picture size to 800x800 for high resolution.
        """
        if not url:
            return url
        
        original_url = url
        desired_size_param = "=w800-h800-l90-rj"

        # NEW LOGIC: Adjust googleusercontent profile pictures for high resolution
        if "googleusercontent.com/profile/picture" in original_url:
            
            # 1. Try to replace an existing size parameter (e.g., =w120-h120-l90-rj)
            # The pattern looks for "=w<digits>-h<digits>-l90-rj"
            new_url = re.sub(r'=w\d+-h\d+-l90-rj', desired_size_param, original_url)
            
            # 2. If replacement didn't happen and the desired parameter is not already present,
            # append it to the end of the URL.
            if new_url == original_url and desired_size_param not in original_url:
                # Check if the URL ends with a number (e.g., '.../picture/2'), which is common
                if re.search(r'/\d+$', original_url):
                    return original_url + desired_size_param
                
            return new_url
            
        # Existing logic: Try high resolution standard YouTube thumbnail
        for quality in ["default", "hqdefault", "mqdefault", "sddefault"]:
            if f"/{quality}.jpg" in original_url:
                # Returns the URL with 'maxresdefault.jpg'
                return original_url.replace(f"/{quality}.jpg", "/maxresdefault.jpg")
            
        # Fallback: Return original URL if no replacement was made
        return original_url


    # score
    def calc_score(self, phrase, match, idx=0, base_score=0,
                   media_type=MediaType.GENERIC) -> int:
        # idx represents the order from youtube
        score = base_score - idx * 5  # - 5% as we go down the results list

        if isinstance(match, MusicVideo):
            score -= 10  # penalty for video results

        if match.artist:
            score += 80 * fuzzy_match(phrase.lower(), match.artist.lower(),
                                      strategy=MatchStrategy.TOKEN_SET_RATIO)
        if match.title:
            score += 80 * fuzzy_match(phrase.lower(), match.title.lower(),
                                      strategy=MatchStrategy.DAMERAU_LEVENSHTEIN_SIMILARITY)

        if media_type == MediaType.GENERIC:
            score -= 10
        return min(100, score)

    # common play
    @ocp_search()
    def search_youtube_music(self, phrase, media_type) -> Iterable[Union[MediaEntry, Playlist]]:
        # match the request media_type
        base_score = 0
        if media_type == MediaType.MUSIC:
            base_score += 10

        if self.voc_match(phrase, "youtube"):
            # explicitly requested youtube
            base_score += 50
            phrase = self.remove_voc(phrase, "youtube")

        idx = 0
        for v in self.search_yt(phrase):
            if isinstance(v, MusicPlaylist):
                # albums / artists / playlists
                score = self.calc_score(phrase, v, idx,
                                        base_score=base_score,
                                        media_type=media_type)
                if isinstance(v, MusicArtist):
                    title = v.artist + " (Featured Tracks)"
                elif isinstance(v, MusicAlbum):
                    title = v.title + " (Full Album)"
                elif isinstance(v, MusicPlaylist):
                    title = v.title + " (Playlist)"
                else:
                    title = v.title
                pl = Playlist(title=title,
                              artist=v.artist,
                              match_confidence=score,
                              skill_id=self.skill_id,
                              skill_icon=self.skill_icon,
                              playback=PlaybackType.AUDIO,
                              media_type=MediaType.MUSIC)
                for e in v.tracks:
                    pl.append(MediaEntry(
                        uri=e.watch_url,
                        match_confidence=score,
                        playback=PlaybackType.AUDIO,
                        media_type=MediaType.MUSIC,
                        length=e.length * 1000 if e.length else 0,
                        # Use high resolution image, with fallback to original
                        image=self._get_high_res_thumbnail(e.thumbnail_url),
                        title=e.title,
                        artist=e.artist,
                        skill_id=self.skill_id,
                        skill_icon=self.skill_icon
                    ))
                if pl:
                    yield pl
            else:
                # videos / songs
                score = self.calc_score(phrase, v, idx,
                                        base_score=base_score,
                                        media_type=media_type)
                # return as a video result (single track dict)
                entry = MediaEntry(
                    uri=v.watch_url,
                    match_confidence=score,
                    playback=PlaybackType.AUDIO,
                    media_type=MediaType.VIDEO if isinstance(v, MusicVideo) else MediaType.MUSIC,
                    length=v.length * 1000 if v.length else 0,
                    # Use high resolution image, with fallback to original
                    image=self._get_high_res_thumbnail(v.thumbnail_url),
                    title=v.title,
                    artist=v.artist,
                    skill_id=self.skill_id,
                    skill_icon=self.skill_icon
                )
                yield entry
                idx += 1


if __name__ == "__main__":
    from ovos_utils.messagebus import FakeBus

    s = YoutubeMusicSkill(bus=FakeBus(), skill_id="t.fake")

    for r in s.search_youtube_music("zz top", MediaType.MUSIC):
        print(r)
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 443000, 'uri': 'youtube//https://music.youtube.com/watch?v=X4jyfV_-WAw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - 08 Sure Got Cold After The Rain Fell - Rio Grande Mud 1972 mix', 'album': 'Z Z Top (The Blues)', 'artist': 'creepingthrash', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 420000, 'uri': 'youtube//https://music.youtube.com/watch?v=b76kjd5nvMg', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ TOP - Blue Jean Blues', 'album': 'Z Z Top (The Blues)', 'artist': 'Tomi_C', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 211000, 'uri': 'youtube//https://music.youtube.com/watch?v=vMjqgIZ1_YM', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - Jesus Just Left Chicago', 'album': 'Z Z Top (The Blues)', 'artist': 'thenoname365', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 257000, 'uri': 'youtube//https://music.youtube.com/watch?v=Uv4B0xK8rNs', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': "ZZ Top 'A Fool For Your Stockings'", 'album': 'Z Z Top (The Blues)', 'artist': 'wolftrack57', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 206000, 'uri': 'youtube//https://music.youtube.com/watch?v=MCBYpv8MmtY', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - Asleep In The Desert [Instrumental]', 'album': 'Z Z Top (The Blues)', 'artist': 'joeybbbbbz', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 362000, 'uri': 'youtube//https://music.youtube.com/watch?v=0s5Hv4EoBAQ', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - Vincent Price Blues (1996)', 'album': 'Z Z Top (The Blues)', 'artist': 'Rudy Doo', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 335000, 'uri': 'youtube//https://music.youtube.com/watch?v=nPdcuhb-kJY', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Goin So Good - ZZ Top with lyrics', 'album': 'Z Z Top (The Blues)', 'artist': 'yollom600', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 271000, 'uri': 'youtube//https://music.youtube.com/watch?v=MOxMMNyIxCE', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - Over You', 'album': 'Z Z Top (The Blues)', 'artist': 'XxXPLAYERONEXxX', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 315000, 'uri': 'youtube//https://music.youtube.com/watch?v=5OhaJfpu9ic', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ top - Made into a movie', 'album': 'Z Z Top (The Blues)', 'artist': 'MrSP0T', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 379000, 'uri': 'youtube//https://music.youtube.com/watch?v=pGr4NHj92rY', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - I Need You Tonight', 'album': 'Z Z Top (The Blues)', 'artist': 'Metal8909', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 254000, 'uri': 'youtube//https://music.youtube.com/watch?v=j9CAjoBg7Qw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': "ZZ Top - Just Got Back From Baby's", 'album': 'Z Z Top (The Blues)', 'artist': 'Kilo2199', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 214000, 'uri': 'youtube//https://music.youtube.com/watch?v=oi23gO8u_Uw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - Old Man', 'album': 'Z Z Top (The Blues)', 'artist': 'Kilo2199', 'skill_id': 't.fake'}
        # {'match_confidence': 90, 'media_type': <MediaType.MUSIC: 2>, 'length': 404000, 'uri': 'youtube//https://music.youtube.com/watch?v=kSHhAkVreiw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'bg_image': 'https://yt3.ggpht.com/WJUxM-ld-EV397QjrzHHvd4zL3aQc0c702ZdyYJI6EDHDKoZ9cMe0X-yrgbHRkRbLaxQuebzDNo=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'ZZ Top - Breakaway', 'album': 'Z Z Top (The Blues)', 'artist': 'MasaccioGlamour', 'skill_id': 't.fake'}

    for r in s.search_youtube_music("frank sinatra ai covers", MediaType.MUSIC):
        print(r)
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 288000, 'uri': 'youtube//https://music.youtube.com/watch?v=SCXZ8_znoE4', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://yt3.ggpht.com/kMnjAFHNa_GkRdMSB0WPOZ_L7bZ3sjTRutYVlmV7BxP6ZuuwJFYRsNSGL0p25alCrG4KX1r20_E=s1200', 'bg_image': 'https://yt3.ggpht.com/kMnjAFHNa_GkRdMSB0WPOZ_L7bZ3sjTRutYVlmV7BxP6ZuuwJFYRsNSGL0p25alCrG4KX1r20_E=s1200', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Pavlo Ilnytskyy – My Way [Live, Frank Sinatra Cover]', 'album': 'Frank Sinatra covers', 'artist': 'Pavlo Ilnytskyy', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 215000, 'uri': 'youtube//https://music.youtube.com/watch?v=_LvrA0fJcI0', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'as the world caves in  - (Frank Sinatra A.I Cover)', 'album': 'Frank Sinatra AI', 'artist': 'the ai man', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 239000, 'uri': 'youtube//https://music.youtube.com/watch?v=9CC_mvhjXE0', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Frank Sinatra Sings Just The Two Of Us ( AI Voice Cover)', 'album': 'Frank Sinatra AI', 'artist': 'PGCFusion', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 189000, 'uri': 'youtube//https://music.youtube.com/watch?v=gauYC0Td7Jk', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Sway by Frank Sinatra (AI Cover)', 'album': 'Frank Sinatra AI', 'artist': 'aidar', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 144000, 'uri': 'youtube//https://music.youtube.com/watch?v=Ikr9mVDMnXM', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': "AI Frank Sinatra - Ain't That A Kick In The Head (Dean Martin Cover)", 'album': 'Frank Sinatra AI', 'artist': 'AI COVERS', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 243000, 'uri': 'youtube//https://music.youtube.com/watch?v=FmIqdyNvYsw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Feeling Good - Frank Sinatra (Original by Michael Bublé) (AI COVER)', 'album': 'Frank Sinatra AI', 'artist': 'WhoAmI AiCover', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 255000, 'uri': 'youtube//https://music.youtube.com/watch?v=dZGGBT1KEOc', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'AI Frank Sinatra - What A Wonderful World (Louis Armstrong Cover)', 'album': 'Frank Sinatra AI', 'artist': 'AI COVERS', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 265000, 'uri': 'youtube//https://music.youtube.com/watch?v=mbr28MMU9cw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'a-ha - Take On Me - Frank Sinatra (AI Jazz Cover)', 'album': 'Frank Sinatra AI', 'artist': 'AI Sings', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 238000, 'uri': 'youtube//https://music.youtube.com/watch?v=aU3AWfjCNFc', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Frank Sinatra - Thriller (AI COVER) (IN THE STYLE OF FRANK SINATRA)', 'album': 'Frank Sinatra AI', 'artist': 'JechucamTF2', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 111000, 'uri': 'youtube//https://music.youtube.com/watch?v=pvTvU0Vr9co', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'AI Frank Sinatra - L-O-V-E (Nat King Cole Cover)', 'album': 'Frank Sinatra AI', 'artist': 'AI COVERS', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 222000, 'uri': 'youtube//https://music.youtube.com/watch?v=q6hUd_TVW54', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Frank Sinatra (A.I Cover) - ‘Five Nights at Freddy’s’ (Color Coded Lyrics)', 'album': 'Frank Sinatra AI', 'artist': 'SuperCraft 85', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 236000, 'uri': 'youtube//https://music.youtube.com/watch?v=kvG7xF03tG0', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Feeling Good - Frank Sinatra (AI Cover)', 'album': 'Frank Sinatra AI', 'artist': 'ZaCool27', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 281000, 'uri': 'youtube//https://music.youtube.com/watch?v=62MvAtdIUrw', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Frank Sinatra - Mr. Blue Sky (AI COVER)', 'album': 'Frank Sinatra AI', 'artist': 'Foamy', 'skill_id': 't.fake'}
        # {'match_confidence': 100, 'media_type': <MediaType.MUSIC: 2>, 'length': 362000, 'uri': 'youtube//https://music.youtube.com/watch?v=VNWudHD3Kt8', 'playback': <PlaybackType.AUDIO: 2>, 'image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'bg_image': 'https://i.ytimg.com/vi/_LvrA0fJcI0/hqdefault.jpg?sqp=-oaymwEWCMACELQBIAQqCghQEJADGFogjgJIWg&rs=AMzJL3k-VuOFKLYIlJNi_JDaC2TbjHOaPg', 'skill_icon': 'https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin/raw/master/ovos_plugin_common_play/ocp/res/ui/images/ocp.png', 'title': 'Bohemian Rhapsody - Frank Sinatra (AI COVER) Queen / Marc Martel', 'album': 'Frank Sinatra AI', 'artist': 'breezy', 'skill_id': 't.fake'}
