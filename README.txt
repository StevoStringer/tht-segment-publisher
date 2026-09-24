THT Segment Publisher - transcription dependency hotfix

Replace the requirements.txt in the ROOT of StevoStringer/tht-segment-publisher with the included file and commit to main.

The change pins httpx==0.27.2 to resolve the OpenAI 1.51.0 client incompatibility:
Client.__init__() got an unexpected keyword argument 'proxies'

No credentials are included. Railway should automatically redeploy after the commit.
