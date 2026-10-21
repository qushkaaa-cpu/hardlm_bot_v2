# BeautyScore Telegram Bot — web deployment pack

This edition is prepared for browser-based deployment to Render as a webhook service. You do not need to run the bot on your Windows computer.

## Deploy without command line

1. Extract this ZIP on your computer (right-click the ZIP → **Extract All / Извлечь всё**).
2. Open GitHub in your browser and create a **new repository**. Private is fine. Do not put your Telegram token in the repository.
3. In the new repository choose **Add file → Upload files**. Open the extracted folder, select its project files (`bot.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `README.md`) and drag them onto GitHub's upload page. Commit the upload.
4. Open Render Dashboard and create a **Blueprint** from that GitHub repository. Render will read `render.yaml` and create the web service.
5. When Render asks for `BOT_TOKEN`, paste the token from BotFather into that private setup field. Do not put the token into a code file, GitHub, or a public message. `WEBHOOK_SECRET` is generated automatically.
6. Start the deploy and wait until the service is marked **Live**. Open the service's `onrender.com` address in a browser. It should show a small JSON response with `"ok": true`.
7. Open your Telegram bot and send `/start`.

## Notes

- This version receives Telegram updates through a webhook, so it does not need Windows PowerShell or local polling.
- The free Render plan can put the service to sleep after 15 minutes without incoming HTTP traffic; waking it may take about a minute. This is suitable for testing, not guaranteed always-on service.
- Render's free filesystem is temporary. The SQLite report history and favorites may disappear after a restart or sleep. Don't treat it as permanent storage.
- The default installation performs the basic photo checks. Optional MediaPipe facial landmark measurements are not installed in this small deployment package.
- Photos are processed to answer the user; the bot code does not store image files in its database. Telegram itself processes files sent through the app.
- Never share the BotFather token. If it is accidentally exposed, regenerate it through BotFather.
