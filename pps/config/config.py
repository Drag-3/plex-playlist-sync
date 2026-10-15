import logging
import os
from json import loads

from pps.config.helpers import UserInputs, convertSyncUserJsonToSyncUserObj

PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
PLEX_USERNAME = os.getenv("PLEX_USERNAME")
PLEX_PASSWORD = os.getenv("PLEX_PASSWORD")
SERVER_NAME = os.getenv("PLEX_SERVER_NAME")
WRITE_MISSING_AS_CSV = os.getenv("WRITE_MISSING_AS_CSV", "0") == "1"
APPEND_SERVICE_SUFFIX = os.getenv("APPEND_SERVICE_SUFFIX", "1") == "1"
ADD_PLAYLIST_POSTER = os.getenv("ADD_PLAYLIST_POSTER", "1") == "1"
ADD_PLAYLIST_DESCRIPTION = os.getenv("ADD_PLAYLIST_DESCRIPTION", "1") == "1"
APPEND_INSTEAD_OF_SYNC = os.getenv("APPEND_INSTEAD_OF_SYNC", False) == "1"
WAIT_SECONDS = int(os.getenv("SECONDS_TO_WAIT", 43200))
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_USER_ID = os.getenv("SPOTIFY_USER_ID", None)
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SPOTIFY_DAILY_MIXES = [value.strip() for value in os.getenv("SPOTIFY_DAILY_MIXES", "").split(",") if value.strip()]  # Legacy; per-user playlists are in SYNC_USERS
SYNC_USERS = os.getenv("SYNC_USERS", "")  # JSON string of list of objs [{plex_username, spotify_username}]
                                            # This can later be expanded to include other services


logging.getLogger(__name__)
def get_environment_variables():
    user_inputs = UserInputs(
        plex_url=PLEX_URL,
        plex_token=PLEX_TOKEN,
        plex_username=PLEX_USERNAME,
        plex_password=PLEX_PASSWORD,
        server_name=SERVER_NAME,
        write_missing_as_csv=WRITE_MISSING_AS_CSV,
        append_service_suffix=APPEND_SERVICE_SUFFIX,
        add_playlist_poster=ADD_PLAYLIST_POSTER,
        add_playlist_description=ADD_PLAYLIST_DESCRIPTION,
        append_instead_of_sync=APPEND_INSTEAD_OF_SYNC,
        wait_seconds=WAIT_SECONDS,
        spotify_client_id=SPOTIFY_CLIENT_ID,
        spotify_client_secret=SPOTIFY_CLIENT_SECRET,
        spotify_user_id=SPOTIFY_USER_ID,
        spotify_redirect_uri=SPOTIFY_REDIRECT_URI,
        spotify_daily_mixes=SPOTIFY_DAILY_MIXES,
        sync_users=convertSyncUserJsonToSyncUserObj(loads(SYNC_USERS)),
    )
    return user_inputs
