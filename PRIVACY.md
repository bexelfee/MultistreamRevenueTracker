# Privacy Policy

Last updated: 2026-05-24

Multistream Revenue Tracker is a freeware desktop application for streamers. It
runs locally on your computer and opens a local web dashboard at
`http://127.0.0.1`.

## Data the app accesses

When you connect accounts, the app may access:

- YouTube stream activity such as Super Chats, Super Stickers, memberships,
  membership gifts, live chat details, and membership level information.
- Twitch stream activity such as bits, subscriptions, subscription gifts, and
  resubs.
- Patreon campaign and member pledge information for the campaign you choose.
- Streamlabs donation events if you provide your own Streamlabs Socket API
  token.

This data is used only to calculate stream revenue, point totals, goals, and
overlay displays inside the app.

## Data storage

The app stores settings, OAuth tokens, goals, logs, and revenue history locally
on your computer, next to the application files in files such as `config.json`,
`data/`, and `logs/`.

The app does not run a cloud service, does not upload your stream data to the
developer, and does not sell or share your data.

## OAuth tokens and credentials

OAuth tokens are stored locally so the app can reconnect to services you have
authorized. Anyone with access to your computer or the app's local data folder
may be able to use those tokens, so treat the `data/` folder as sensitive.

You can revoke access at any time from the connected provider account pages
(Google, Twitch, Patreon, or Streamlabs), or by deleting the local token files
from the app's data folder.

## Logs

The app may write local session logs for troubleshooting. Sensitive tokens are
redacted where possible. Chat messages and usernames may appear in logs if you
enable chat-message logging or run the app in a debug configuration.

## Contact

For privacy questions or bug reports, open an issue on the GitHub repository:

https://github.com/bexelfee/MultistreamRevenueTracker/issues
