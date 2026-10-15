import functools
import logging
import random
import time
from dataclasses import dataclass
from http.client import RemoteDisconnected

from urllib3.exceptions import ProtocolError
from requests.exceptions import ConnectionError


@dataclass
class Track:
    title: str
    artist: str
    album: str
    url: str = None

    @classmethod
    def from_plex_track(cls, track):
        return cls(
            title=track.title,  # Title
            artist=track.originalTitle if track.originalTitle else track.grandparentTitle,
            # originalTitle is used for track artists in a collection, grandparentTitle is used for album artists in an album
            album=track.parentTitle,
            url=track.getStreamURL(),
        )


@dataclass
class Playlist:
    id: str
    name: str
    description: str
    poster: str


@dataclass
class SyncUser:
    """
    This class is used to store the user information from the environment variables.
    This is stored as json, and example is below
    {
        "plex": "master",
        "spotify": {
            "username": "username",
            "special_playlists": [
                "playlist_id",
                "playlist_id"
            ]
        }
    }
    """
    plex_username: str
    spotify_info: "SpotifyUser" = None

    @classmethod
    def from_dict(cls, user_dict):
        return cls(
            plex_username=user_dict["plex"],
            spotify_info=SpotifyUser.from_dict(user_dict.get("spotify", {})))


@dataclass
class SpotifyUser:
    username: str
    special_playlists: list[str] = None  # List of playlist IdS

    def __post_init__(self):
        if not self.special_playlists:
            self.special_playlists = []

    @classmethod
    def from_dict(cls, user_dict):
        try:
            return cls(
                username=user_dict["username"],
                special_playlists=user_dict.get("special_playlists", [])
            )
        except KeyError:
            return None


@dataclass
class UserInputs:
    plex_url: str
    plex_token: str
    plex_username: str
    plex_password: str
    server_name: str

    write_missing_as_csv: bool
    append_service_suffix: bool
    add_playlist_poster: bool
    add_playlist_description: bool
    append_instead_of_sync: bool
    wait_seconds: int

    spotify_client_id: str
    spotify_client_secret: str
    spotify_user_id: str
    spotify_redirect_uri: str
    spotify_daily_mixes: list[str]

    sync_users: list[SyncUser]

    deezer_user_id: str
    deezer_playlist_ids: str


def retry_with_backoff(func):
    """Decorator function to retry the decorated function with exponential backoff."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = 3
        delay_range = (2, 4)  # Random delay range between 2 and 4 seconds

        for retry in range(max_retries):
            try:
                val = func(*args, **kwargs)
                return val
            except (ConnectionError, ProtocolError, RemoteDisconnected) as ce:
                logger = logging.getLogger(func.__module__)  # Use the module name as the logger name
                logger.error(f"ConnectionError occurred: {ce}")
                if retry == max_retries - 1:
                    raise  # Reraise the exception on the final retry
                else:
                    delay = random.uniform(*delay_range)
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                    delay_range = (delay_range[0] ** 2, delay_range[1] ** 2)

    return wrapper


def wait_for_connection(func):
    """Decorator function to wait for a connection to be established."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        while True:
            try:
                val = func(*args, **kwargs)
                return val
            except (ConnectionError, ProtocolError, RemoteDisconnected) as ce:
                logger = logging.getLogger(func.__module__)  # Use the module name as the logger name
                logger.error(f"ConnectionError occurred: {ce}")
                logger.info("Retrying in 5 seconds...")
                time.sleep(5)

    return wrapper


def convertSyncUserJsonToSyncUserObj(sync_users_json: list[dict]):
    sync_users = []
    for user in sync_users_json:
        sync_users.append(SyncUser.from_dict(user))
    return sync_users


def remove_html_tags(text):
    """Remove html tags from a string"""
    import re
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)


def sanitize_spotify_data(data):
    """Remove html tags from Spotify data"""
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = sanitize_spotify_data(value)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            data[index] = sanitize_spotify_data(value)
    elif isinstance(data, str):
        data = remove_html_tags(data)
    return data
