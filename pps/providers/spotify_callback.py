import os
import signal
from pathlib import Path

from flask import Flask, request, render_template, redirect, session
from queue import Queue
from gevent.pywsgi import WSGIServer

from pps.config.helpers import UserInputs, SyncUser
from pps.providers.spotify import get_auth_url, authorize_user

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.urandom(24)
access_code_queue = Queue()
inputs: UserInputs = None


@app.route('/callback')
def callback():
    code = request.args.get('code')
    username = session.get('username')
    if not username:
        return "Error: No username found in session"
    authorize_user(inputs, username, code)
    session.pop('username', None)
    return "Authorization successful"


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        session['username'] = username
        return redirect(get_auth_url(inputs, username))

    else:
        return render_template("login.html", users=inputs.sync_users)


def start_callback_server(user_inputs: UserInputs):
    global inputs
    inputs = user_inputs
    callback_server = WSGIServer(('', 8888), app)
    callback_server.serve_forever()


"""
TODO:
We need to extend the use of the callback server.

Serve a page that allows the user to select which user to sign in as (The list of users are in the env vars)
When a user goes to /login they should select the proper username, then will use Spotipy to get the auth link to redirect to
After the user authenticates, they will be redirected to /callback with the code in the url (need to make sure the correct code is mapped, for example multiple people auth at once)

We will also have the option to reset the auth for a user, which will remove the refresh token from the cache and force the user to re-authenticate

Back on the main thread, if the user is not authenticated, we cannot execute the sync, so we will need to wait for the user to authenticate
We will skip the user if they are not authenticated and try the next user
 /callback should return a tuple of (username, code) so we can map the code to the correct user ! 
 
The main thread will check if at least one user is authenticated, if not, it will wait for a user to authenticate
If a user is authenticated, it will continue with the sync if the user is not authenticated, connect will return None and we will skip the user else it will return the user object

Sync is normal.

The only problem is that a user that authenticates will have to wait for the next run of the sync to actually process the authentication. It may expire before then.

So perhaps keep a separate auth thread which will save the credentials to a file, and the main thread will read the file and use the credentials to connect to the service.

So this is the current plan:
1. Start the callback server
    -1a Listen on /login for a user to select their username (post) and redirect to the auth link
    - 1b. Listen on /callback for a code
    - 1c. Save the code to a queue with the username
2. Start auth thread
    2a. Auth Thread will listen on the queue for a code and username
    2b. Auth thread will use the code to get the refresh token and save it to a file (Use spotipy to get the refresh token)
3. Start main thread
    3a. Main thread will check if any users are authenticated 
    3b. If not, it will wait for a user to authenticate (wait in a loop for a file to be created for any user)
    3c. If a user is authenticated, it will continue with the sync
    3d. If a sync has been completed, (not waiting for a sync) it will wait for the next sync the full wait time


"""

if __name__ == '__main__':
    inputs = UserInputs(
        plex_url="",
        plex_username="",
        plex_password="",
        server_name="",
        write_missing_as_csv=False,
        append_service_suffix=False,
        add_playlist_poster=False,
        add_playlist_description=False,
        append_instead_of_sync=False,
        spotify_user_id="",
        spotify_daily_mixes=[],
        deezer_user_id="",
        deezer_playlist_ids="",
        plex_token="",
        spotify_client_id="",
        spotify_client_secret="",
        spotify_redirect_uri="http://localhost:8888/callback",
        wait_seconds=60,
        sync_users=[
            SyncUser(
                plex_username="Test1",
            ),
            SyncUser(
                plex_username="Test2",
            )
        ]
    )

    print(Path(app.template_folder).absolute())
    # Start Dev Server for Testing
    app.run(host='0.0.0.0', port=8888, debug=True)


