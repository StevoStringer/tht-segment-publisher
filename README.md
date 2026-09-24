# THT Segment Publisher — Publisher Access Edition

Built for the actual permissions model:
- You **can publish episodes** to The Honest Truth on iono.fm.
- Smile FM **does not have Stream Archive**.
- You **do not have FTP auto-publish**.

## Architecture
Smile FM direct live audio → scheduled recorder → full-show archive → transcription → segment detection → trim/review → normalized MP3 → metadata → official iono.fm Publish Episode handoff.

## Why the iono password is not required
iono's documented `Publish` right allows episode management. The official publishing workflow is through the iono publisher dashboard. The public API documentation currently documents an **analytics API**, not a general episode-publishing API. FTP auto-publish is a separate feature that must be enabled on compatible Radio packages.

Accordingly this app does not collect or store your website password. It opens the official THT iono page in your browser, where your existing authenticated session handles publishing.

## Still required before live deployment
1. The **direct playable audio-stream URL** behind Smile FM stream 212. `https://iono.fm/s/212` is the player page, not the raw audio endpoint.
2. The real THT broadcast schedule.
3. An OpenAI API key if automatic transcription/segment detection is desired.
4. An always-on Docker host with persistent storage.
5. Station authorisation for automated recording/republication.

## Run
```bash
cp .env.example .env
docker compose up -d --build
```
Open `http://localhost:8000`, configure the stream and schedule, and enable scheduled capture.

## Publishing
For each approved segment choose **Prepare for iono**. The app renders the MP3 and metadata. Choose **Open iono handoff** to open The Honest Truth's official iono page in your already-authenticated browser session and use Publish Episode.

No iono username/password is stored.
