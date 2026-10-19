# reddit-poster

A tiny local-only backend that posts Reddit comments with one click from a
personal admin panel, using **your own** Reddit account via OAuth.

Built for [Landing Clinic](https://landingclinic.com): I reply to threads where
founders explicitly ask for landing-page feedback, and this tool queues my
hand-written drafts and submits them — one manual click per reply. No automation
of content, no bulk posting, no voting, no DMs.

## How it works

```
admin panel (browser) ──localhost──> poster (this server) ──> reddit.com
     "Post" button             OAuth tokens live here only
```

- The server binds to `127.0.0.1` only — nothing is reachable from the network.
- Reddit OAuth tokens are stored in `config.json` (mode `0600`) on your machine.
- You create your own Reddit app and paste your own credentials into
  `config.json`; they are never sent anywhere except Reddit's official OAuth
  endpoints.
- Python 3, standard library only — no dependencies to install.

## Setup

1. **Create a Reddit app** (logged in as the account you'll post from):
   - https://www.reddit.com/prefs/apps → "create another app..."
   - Type: **web app**
   - Redirect URI: `http://localhost:8099/callback`
   - Copy the **client ID** (under the app name) and **client secret**.
2. **Configure:**
   ```sh
   cp config.example.json config.json
   ```
   Paste the client ID and secret into `config.json`. Put your Reddit username
   in `user_agent` (Reddit requires a descriptive User-Agent).
3. **Run:**
   ```sh
   ./start_poster.sh
   ```
4. Open your admin panel, click **Connect Reddit**, approve on reddit.com.

## API

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| GET | `/api/status` | Poster + Reddit connection status |
| GET | `/api/auth/reddit` | Start Reddit OAuth (redirects to reddit.com) |
| GET | `/callback` | OAuth callback — exchanges the code for tokens |
| POST | `/api/post` | `{"thread_url": "...", "text": "..."}` — post one comment |
| POST | `/api/disconnect` | Forget Reddit tokens |

## Posting discipline

Reddit removes spam aggressively and suspends bot-like accounts. This tool is
deliberately human-paced:

- one deliberate click per comment, with a confirmation step;
- a few comments per day, never the same text twice;
- links only where the subreddit's rules allow, always with disclosure.

If Reddit rate-limits you, wait it out — don't retry in a loop.

## License

MIT — see [LICENSE](LICENSE).
