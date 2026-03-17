If the birdweather page hasn't rendered lately, check `~/Library/Logs/render-birdweather.log` for what could be going on.  

The script for rendering the page is at `scripts/render-birdweather.sh`.  

The launch agent is located at `~/Library/LaunchAgents/com.connorfrench.render-birdweather.plist`.

If I change anything in the launch agent, I need to:

1. `launchctl unload ~/Library/LaunchAgents/com.connorfrench.render-birdweather.plist`
2. `launchctl load ~/Library/LaunchAgents/com.connorfrench.render-birdweather.plist`

