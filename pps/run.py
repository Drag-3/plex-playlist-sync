import logging
import os
import threading
import time

from pps.config import config

from pps.providers.plex import connect_to_plex

from pps.providers.spotify import connect_to_spotify, spotify_playlist_sync, all_users_authenticated
from pps.config.logging_utils import setup_logging

from pps import CACHE_DIR, CSV_DIR
from pps.providers import spotify_callback


def sync_playlists(plex, sp, user_inputs, user):
    """Run Spotify synchronization for one Plex/Spotify user mapping."""
    if sp:
        spotify_playlist_sync(sp, plex, user_inputs, user)
        logging.info("Spotify playlist sync complete")
    else:
        logging.info("Could not sync Spotify playlists. Probably not authenticated")


def run():
    # Read ENV variables
    user_inputs = config.get_environment_variables()

    # Setup logging
    setup_logging()
    logging.getLogger(__name__)

    # Create cache directory
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.chown(CACHE_DIR, os.getuid(), os.getgid())
    os.chmod(CACHE_DIR, 0o777)

    # Create CSV directory
    os.makedirs(CSV_DIR, exist_ok=True)
    os.chown(CSV_DIR, os.getuid(), os.getgid())
    os.chmod(CSV_DIR, 0o777)

    # Start flask callback server
    app_thread = threading.Thread(target=spotify_callback.start_callback_server, args=(user_inputs,))
    app_thread.start()

    # Body Loop
    while True:
        logging.info("Starting playlist sync")

        # Connect to Plex
        plex = connect_to_plex(user_inputs)  # Get primary Plex server
        """
        This script is designed to sync only one server at a time. If you have multiple servers, you can run multiple
        instances of this script with different compose files.
        All users should be shared or home users on the current sync server.
        """

        while not all_users_authenticated(user_inputs):  # Wait for all users to authenticate
            time.sleep(10)
            logging.info("Waiting for all users to authenticate... (10s)")

        for user in user_inputs.sync_users:
            if user.plex_username == "master":
                pl = plex  # Get primary Plex server
            else:
                pl = plex.switchUser(user.plex_username)  # Get connected user's Plex server obj
                logging.info(f"Switched to user {user.plex_username}. {pl}")
            sp = connect_to_spotify(user_inputs, user.spotify_info.username)
            # Continue for any other
            sync_playlists(pl, sp, user_inputs, user)

        logging.info("All playlist(s) sync complete")
        logging.info(f"Sleeping for {user_inputs.wait_seconds} seconds"
                     f" ({time.ctime(time.time() + user_inputs.wait_seconds)})")
        time.sleep(user_inputs.wait_seconds)


if __name__ == "__main__":
    run()
