import csv
import logging
import os.path
import pathlib
import re
# import sys
# from difflib import SequenceMatcher
from itertools import product
from typing import List

import plexapi
import plexapi.audio
import unidecode
from fuzzywuzzy import fuzz
from plexapi.exceptions import BadRequest, NotFound, Unauthorized

from pps import CSV_DIR

try:
    from plexapi.exceptions import Forbidden  # Patched during docker build, if patch fails, use the one below
except ImportError:
    class Forbidden(BadRequest):
        pass
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from plexapi.playlist import Playlist as PlexPlaylist

from pps.config.helpers import Playlist, Track, UserInputs, retry_with_backoff, wait_for_connection
from pps.config.logging_utils import get_prefix_logger

logging.getLogger(__name__)


def connect_to_plex(user_inputs):
    if all((user_inputs.plex_username, user_inputs.plex_password, user_inputs.server_name)):
        try:
            account, plex = connect_via_pass(user_inputs.plex_username, user_inputs.plex_password,
                                             user_inputs.server_name)
        except Exception as e:
            logging.info(f"Connecting with password failed: {e}")
            plex = connect_via_token(user_inputs.plex_url, user_inputs.plex_token)
    elif user_inputs.plex_url and user_inputs.plex_token:
        plex = connect_via_token(user_inputs.plex_url, user_inputs.plex_token)
    else:
        logging.error("Missing Plex Authorization Variables")
        raise ValueError("Missing Plex Authorization Variables")
    logging.info("Successfully connected to Plex Server")
    return plex


def connect_via_pass(username, password, server_name):
    try:
        plex_account = MyPlexAccount(username, password, timeout=60)
        logging.info(f"Got Plex Account, looking for Server: {server_name}")
        server = plex_account.resource(server_name).connect(timeout=60)
        logging.info(f"Found Server {server_name}: {server}")
        return plex_account, server
    except Exception as e:
        logging.error("Plex Authorization error")
        logging.exception(e)
        raise


def connect_via_token(url, token):
    try:
        logging.info("Connecting to Local Server with Token")
        plex = PlexServer(url, token, timeout=60)
        return plex
    except Exception as e:
        logging.error("Plex Authorization error")
        logging.exception(e)
        raise


def _write_csv(tracks: List[Track], name: str, username: str, path: str = CSV_DIR) -> None:
    """Write given tracks with given name as a csv.

    Args:
        tracks (List[Track]): List of Track objects
        name (str): Name of the file to write
        path (str): Root directory to write the file
    """
    # pathlib.Path(path).mkdir(parents=True, exist_ok=True)

    data_folder = pathlib.Path(path) / username
    data_folder.mkdir(parents=True, exist_ok=True)
    file = data_folder / f"{name}.csv"
    logging.info(f"Creating {file}")
    with open(file, "w", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(Track.__annotations__.keys())
        for track in tracks:
            writer.writerow(
                [track.title, track.artist, track.album, track.url]
            )


def _delete_csv(name: str, username: str, path: str = CSV_DIR) -> None:
    """Delete file associated with given name

    Args:
        name (str): Name of the file to delete
        path (str, optional): Root directory to delete the file from
    """
    data_folder = pathlib.Path(path) / username
    logging.info(os.listdir(data_folder))
    file = data_folder / f"{name}.csv"
    logging.info(f"{str(file)} Exists: {os.path.exists(file)}")
    file.unlink()


def _normalize_string(string: str) -> str:
    """Normalize string by removing special characters and spaces.

    Args:
        string (str): String to normalize

    Returns:
        str: Normalized string
    """
    return "".join(
        char for char in string if char.isalnum() or char in [" ", "-", "_"]
    ).lower()


def _strip_extended_labels(string: str) -> str:
    """Strip extended labels from string.

    Args:
        string (str): String to strip

    Returns:
        str: Stripped string
    """
    s = re.sub(r"\([^)]*\)", "", string)
    return s.strip()


def _transliterate(string: str) -> str:
    """Transliterate string to ASCII.

    Args:
        string (str): String to transliterate

    Returns:
        str: Transliterated string
    """
    return unidecode.unidecode(string)


def _compare_tracks(track: Track, plex_track: plexapi.audio.Track, logger: logging = None) -> bool:
    """Compare track metadata to plex track metadata.

    Args:
        track (Track): Track object
        plex_track (plexapi.audio.Track): plex track object

    Returns:
        bool: True if metadata matches, else False
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    def _is_match(lhs: Track, rhs: plexapi.audio.Track | Track, logger: logging) -> bool:
        if isinstance(rhs, plexapi.audio.Track):
            rhs = Track.from_plex_track(rhs)

        title = fuzz.token_set_ratio(_normalize_string(lhs.title), _normalize_string(rhs.title))
        artist = fuzz.token_set_ratio(_normalize_string(lhs.artist), _normalize_string(rhs.artist))
        album = fuzz.token_set_ratio(_normalize_string(lhs.album), _normalize_string(rhs.album))

        confidence = (title * 0.5 + artist * 0.2 + album * 0.3)  # Weighted average
        if confidence > 95:
            logger.info(f"Found Track in Plex Server: {rhs.title} by {rhs.artist} in {rhs.album}")
            return True
        else:
            logger.info(f"Track similarity is less than 85%: {lhs.title} by {lhs.artist}"
                        f" in {lhs.album} vs {rhs.title} by {rhs.artist} in {rhs.album}")
            return False

    if _is_match(track, plex_track, logger):
        return True

    logger.info(f"Track similarity is less than 85%: {track.title} by {track.artist}. Try stripping extended labels")
    stripped_track1 = Track(_strip_extended_labels(track.title),
                            _strip_extended_labels(track.artist),
                            _strip_extended_labels(track.album))
    if _is_match(stripped_track1, plex_track, logger):
        return True

    title_tuple = (track.title, _transliterate(track.title))
    artist_tuple = (track.artist, _transliterate(track.artist))
    album_tuple = (track.album, _transliterate(track.album))

    plex_title_tuple = (plex_track.title, _transliterate(plex_track.title))
    plex_artist_tuple = (plex_track.artist().title, _transliterate(plex_track.artist().title))
    plex_album_tuple = (plex_track.album().title, _transliterate(plex_track.album().title))

    transliterated_titles = product(title_tuple, plex_title_tuple)
    transliterated_artists = product(artist_tuple, plex_artist_tuple)
    transliterated_albums = product(album_tuple, plex_album_tuple)

    for t_title1, t_title2 in transliterated_titles:
        for t_artist1, t_artist2 in transliterated_artists:
            for t_album1, t_album2 in transliterated_albums:
                t_track1 = Track(t_title1, t_artist1, t_album1)
                t_track2 = Track(t_title2, t_artist2, t_album2)
                if _is_match(t_track1, t_track2, logger):
                    return True

    logger.info(f"Unable to match track: {track.title} by {track.artist} in {track.album}")
    return False


def _search_plex_for_track(plex: PlexServer, track: Track, logger: logging = None) -> plexapi.audio.Track | None:
    """Search for a track in Plex and compare it with the given track."""
    if logger is None:
        logger = logging.getLogger(__name__)
    search_terms = [track.title, _strip_extended_labels(track.title), _transliterate(track.title)]
    for term in search_terms:
        search_results = _perform_plex_search(plex, term)
        for plex_track in search_results:
            if _compare_tracks(track, plex_track, logger):
                return plex_track
    return None


@retry_with_backoff
@wait_for_connection
def _perform_plex_search(plex: PlexServer, search_term: str, logger: logging = None) -> List[plexapi.audio.Track]:
    """Perform a search on the Plex server.

    Args:
        plex (PlexServer): A configured PlexServer instance
        search_term (str): Search term

    Returns:
        List[plexapi.audio.Track]: List of plex track objects
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    try:
        return plex.search(search_term, mediatype="track", limit=15)
    except (NotFound, BadRequest):
        logger.info(f"Search failed or no results for {search_term} on Plex")
        return []


def _get_available_plex_tracks(plex: PlexServer, tracks: List[Track], logger: logging) -> (
        List[plexapi.audio.Track], List[Track]):
    """Search and return list of tracks available in plex.

    Args:
        plex (PlexServer): A configured PlexServer instance
        tracks (List[Track]): list of track objects

    Returns:
        Tuple containing:
            List of Tracks that are stored in Plex (plexapi.audio.Track)
            List of Tracks which are not (Track)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    plex_tracks, missing_tracks = [], []
    for track in tracks:
        if found_track := _search_plex_for_track(plex, track, logger):
            plex_tracks.append(found_track)
            logger.info(
                f"Found Track in Plex Server: {found_track.title} by {found_track.artist().title} in {found_track.album().title}")
        else:
            missing_tracks.append(track)
            logger.info(f"Could not find Track in Plex Server: {track.title} by {track.artist} in {track.album}")

    return plex_tracks, missing_tracks


@retry_with_backoff
@wait_for_connection
def _update_plex_playlist(
        plex: PlexServer,
        available_tracks: List,
        playlist: Playlist,
        append: bool = False,
) -> PlexPlaylist:
    """Update existing plex playlist with new tracks and metadata.

    Args:
        plex (PlexServer): A configured PlexServer instance
        available_tracks (List): list of plex track objects
        playlist (Playlist): Playlist object
        append (bool): Boolean for Append or sync

    Returns:
        plexapi.playlist.Playlist: plex playlist object
    """
    plex_playlist = plex.playlist(playlist.name)
    if not append:
        plex_playlist.removeItems(plex_playlist.items())
    plex_playlist.addItems(available_tracks)
    return plex_playlist


def update_or_create_plex_playlist(
        plex: PlexServer,
        playlist: Playlist,
        tracks: List[Track],
        user_inputs: UserInputs,
        provider_username: str = "",
        plex_username: str = "",
) -> None:
    """Update playlist if exists, else create a new playlist.

    Args:
        user_inputs: User entered Environment Vars
        tracks: (List): List of plex.audio.track objects
        plex (PlexServer): A configured PlexServer instance
        playlist (Playlist): Playlist object
    """
    logger = get_prefix_logger(playlist.name, prefix=f"plex_{provider_username}:{playlist.name} | ")
    logger.info(f"Starting sync for playlist {playlist.name}")
    available_tracks, missing_tracks = _get_available_plex_tracks(plex, tracks, logger)
    if available_tracks:  # Set up playlist with Tracks
        try:
            plex_playlist = _update_plex_playlist(
                plex=plex,
                available_tracks=available_tracks,
                playlist=playlist,
                append=user_inputs.append_instead_of_sync,
            )
            logger.info(f"Updated playlist tracks")
        except NotFound:
            plex.createPlaylist(title=playlist.name, items=available_tracks)
            logger.info(f"Created playlist  {playlist.name}")
            plex_playlist: PlexPlaylist = plex.playlist(playlist.name)  # plexapi.playlist.Playlist
        except BadRequest as e:
            logger.info(f"Failed to update playlist {playlist.name} due to no tracks selected")
            logger.warning(str(e))
            return  # Skip updating summary and poster

        if playlist.description and user_inputs.add_playlist_description:
            try:
                plex_playlist.editSummary(summary=playlist.description)
                logger.info(f"Updated playlist description")
            except (Unauthorized, NotFound, BadRequest) as e:
                logger.info(f"Failed to update description for playlist {playlist.name}")
                logger.exception(e)
            except Exception as e:
                logger.error(f"Unhandled Exception: {e}")

        if playlist.poster and user_inputs.add_playlist_poster:
            # Managed / Shared users cannot upload posters because plex is dumb and doesnt give them permission
            # Can I get around this by using the plex token?
            try:
                plex_playlist.uploadPoster(url=playlist.poster)
                logger.info(f"Updated playlist poster")
            except Forbidden as e:
                logger.info(f"Failed to update poster for playlist {playlist.name} due to insufficient permissions")
            except (NotFound, BadRequest, Unauthorized) as e:
                logger.info(f"Failed to update poster for playlist {playlist.name}")
                logger.warning(str(e))
            except Exception as e:
                logger.exception(e)

        logger.info(f"Data for playlist {playlist.name} updated successfully")

    else:
        logger.info(f"No songs for playlist {playlist.name} were found on plex, skipping the playlist creation")

    if missing_tracks and user_inputs.write_missing_as_csv:  # Write needed songs to CSV file
        try:
            _write_csv(missing_tracks, playlist.name, provider_username)
            logger.info(f"Missing tracks written to {playlist.name}.csv")
        except OSError as e:
            logger.info(f"Failed to write missing tracks for {playlist.name}, likely permission issue")
            logger.warning(str(e))
        except Exception as e:
            logger.exception(e)

    if (not missing_tracks) and user_inputs.write_missing_as_csv:
        try:
            # Delete playlist created in prev run if no tracks are missing now
            if os.path.exists(pathlib.Path(CSV_DIR) / provider_username / (playlist.name + '.csv')):
                _delete_csv(playlist.name, provider_username)
                logger.info(f"Deleted old {playlist.name}")
            else:
                logger.info(f"{playlist.name + '.csv'} does not exist in {CSV_DIR}/{provider_username}")
        except OSError as e:
            logger.info(f"Failed to delete {playlist.name}.csv, likely permission issue")
            logger.warning(str(e))
        except Exception as e:
            logger.exception(e)

    logger.info(f"Finished {playlist.name}")
