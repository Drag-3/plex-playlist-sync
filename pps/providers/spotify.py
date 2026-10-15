import logging
import random
import time
from typing import List

import spotipy
from plexapi.server import PlexServer
from spotipy import CacheFileHandler, SpotifyOAuth, SpotifyException
from urllib3.exceptions import ProtocolError

from pps.config.helpers import Playlist, Track, UserInputs, retry_with_backoff, wait_for_connection, SyncUser, \
    sanitize_spotify_data
from pps.providers.plex import update_or_create_plex_playlist

from pps import SPOTIFY_TOKEN_CACHE_PATH

logging.getLogger(__name__)


def all_users_authenticated(user_inputs: UserInputs) -> bool:
    for user in user_inputs.sync_users:
        cache_handler = CacheFileHandler(cache_path=SPOTIFY_TOKEN_CACHE_PATH + "-" + user.spotify_info.username)  # TODO: Change to spotify_username here and in login.html
        token_info = cache_handler.get_cached_token()
        if not token_info or not all((token_info.get('access_token'), token_info.get('refresh_token'))):
            return False
    return True


def get_oauth(user_inputs: UserInputs, username,
              cache=None) -> SpotifyOAuth:
    if cache is None:
        cache = CacheFileHandler(cache_path=SPOTIFY_TOKEN_CACHE_PATH + "-" + username)
    return SpotifyOAuth(
        client_id=user_inputs.spotify_client_id,
        client_secret=user_inputs.spotify_client_secret,
        redirect_uri=user_inputs.spotify_redirect_uri,
        show_dialog=False,
        open_browser=False,
        scope='playlist-read-private,playlist-read-collaborative,user-library-read,user-read-private',
        cache_handler=cache
    )


def get_auth_url(user_inputs: UserInputs, username) -> str:
    auth_manager = get_oauth(user_inputs, username)
    return auth_manager.get_authorize_url()


def authorize_user(user_inputs: UserInputs, username, code) -> str:
    auth_manager = get_oauth(user_inputs, username)
    token_info = auth_manager.get_access_token(code)
    return token_info


def connect_to_spotify(user_inputs, username) -> spotipy.Spotify | None:
    cache_handler = CacheFileHandler(cache_path=SPOTIFY_TOKEN_CACHE_PATH + "-" + username)
    token_info = cache_handler.get_cached_token()
    logging.debug(token_info)
    if not token_info or not all((token_info.get('access_token'), token_info.get('refresh_token'))):
        return None
    auth_manager = get_oauth(user_inputs, username, cache_handler)

    sp = spotipy.Spotify(auth_manager=auth_manager)
    logging.info("Successfully connected to Spotify Account")
    return sp


@retry_with_backoff
@wait_for_connection
def get_my_daily_mixes(spotify: spotipy.Spotify, daily_mixes: list[str], suffix: str = " - Spotify") -> list[Playlist]:
    playlists = []
    try:
        for mix in daily_mixes:
            playlist = sanitize_spotify_data(spotify.playlist(mix))
            playlists.append(
                Playlist(
                    id=playlist["uri"],
                    name=playlist["name"] + suffix,
                    description=playlist.get("description", ""),
                    poster="" if not playlist["images"] else playlist["images"][0].get("url", ""),
                )
            )
    except spotipy.SpotifyException as e:
        logging.error(f"Failed getting playlists: {e}")
    return playlists


@retry_with_backoff
@wait_for_connection
def get_sp_user_playlists(spotify: spotipy.Spotify, suffix: str = " - Spotify") -> List[Playlist]:
    """Get metadata for playlists in the given user_id.

    Args:
        spotify (spotipy.Spotify): Spotify configured instance
        suffix (str): Identifier for source
    Returns:
        List[Playlist]: list of Playlist objects with playlist metadata fields
    """
    playlists = []
    try:
        sp_playlists = sanitize_spotify_data(spotify.current_user_playlists())
        for playlist in sp_playlists["items"]:
            playlists.append(
                Playlist(
                    id=playlist["uri"],
                    name=playlist["name"] + suffix,
                    description=playlist.get("description", ""),
                    poster="" if not playlist["images"] else playlist["images"][0].get("url", ""),
                )
            )
        while sp_playlists.get('next'):
            sp_playlists = sanitize_spotify_data(spotify.next(sp_playlists))
            for playlist in sp_playlists["items"]:
                playlists.append(
                    Playlist(
                        id=playlist["uri"],
                        name=playlist["name"] + suffix,
                        description=playlist.get("description", ""),
                        poster="" if not playlist["images"] else playlist["images"][0].get("url", ""),
                    )
                )
    except spotipy.SpotifyException as e:
        logging.error(f"Failed getting playlists: {e}")
    return playlists


@retry_with_backoff
@wait_for_connection
def get_sp_tracks_from_playlist(spotify: spotipy.Spotify, playlist: Playlist) -> list[Track]:
    """Return list of tracks with metadata.

    Args:
        spotify (spotipy.Spotify): Spotify configured instance
        playlist (Playlist): Playlist object
    Returns:
        List[Track]: list of Track objects with track metadata fields
    """

    def extract_sp_track_metadata(track) -> Track:
        title = track["track"]["name"]
        artist = track["track"]["artists"][0]["name"]
        album = track["track"]["album"]["name"]
        url = track["track"]["external_urls"].get("spotify", "")
        return Track(title, artist, album, url)

    tracks = []

    try:
        sp_playlist_tracks = sanitize_spotify_data(spotify.playlist_items(playlist.id, additional_types=("track",)))
        tracks = [extract_sp_track_metadata(i) for i in sp_playlist_tracks["items"] if i.get("track")]
        while sp_playlist_tracks["next"]:
            sp_playlist_tracks = sanitize_spotify_data(spotify.next(sp_playlist_tracks))
            tracks.extend(extract_sp_track_metadata(i) for i in sp_playlist_tracks["items"] if i.get("track"))
    except spotipy.SpotifyException as e:
        logging.error(f"Failed getting tracks: {e}")
    except Exception:
        raise
    return tracks


def spotify_playlist_sync(spotify: spotipy.Spotify, plex: PlexServer, user_inputs: UserInputs, user: SyncUser) -> None:
    """Syncs Plex Server with User's Spotify Playlists

    Args:
        user:
        spotify (spotipy.Spotify):  Configured Spotify Instance
        plex: PlexServer object
        user_inputs: Entered Environment Vars

    Returns:

    """
    logging.info("Starting Spotify playlist sync")
    playlists = get_sp_user_playlists(spotify, " - Spotify" if user_inputs.append_service_suffix else "", )
    playlists.extend(get_my_daily_mixes(spotify, user.spotify_info.special_playlists,
                                        " - Spotify" if user_inputs.append_service_suffix else ""))
    logging.info(f"Found {len(playlists)} Spotify playlists")
    if playlists:
        for playlist in playlists:
            tracks = get_sp_tracks_from_playlist(spotify, playlist)
            update_or_create_plex_playlist(plex, playlist, tracks, user_inputs, user.spotify_info.username, user.plex_username)
    else:
        logging.error("No spotify playlists found for given user")
