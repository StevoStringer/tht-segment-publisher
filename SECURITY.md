# iono.fm authentication design

Do **not** place an iono.fm username or password in `.env`, source code, the database, or this app.

The user's existing iono.fm Publish right is sufficient for normal episode management in the official publisher dashboard. The current public iono documentation describes web-dashboard publishing and an optional FTP auto-publish feature, but does not document a podcast publishing API for ordinary Publish-right users.

This build therefore:
1. records/processes audio independently;
2. prepares the MP3 and metadata;
3. hands the user to the official iono.fm publisher page using the browser's existing authenticated session.

If iono later provides an official podcast publishing API/token or enables FTP auto-publish for the account, implement that as a separate publisher adapter using a revocable token/secret, never a stored website password.
