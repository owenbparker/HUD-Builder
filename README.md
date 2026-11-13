# SCC HUD Builder

Design your own in-game HUD for any game, run it from a control panel made
from your design, and put it on stream as a browser source.

HUD Builder uses the same layers and the same player (`web/runtime.js`) as
the SCC GFX Engine's Composer, so a HUD made here plays the same way
everywhere.

## Install

Download **SCC-HUD-Builder-Setup.exe** from the
[latest release](https://github.com/owenbparker/HUD-Builder/releases/latest)
and run it. It installs to `C:\SCC HUD Builder` and adds a desktop shortcut.
The app checks for updates when it starts.

## Making a HUD

1. **My HUDs → New HUD.** Name it, pick the game, and start from a blank
   canvas or the scorebug (teams, colours, score, round).
2. **Design.** Add rectangles, ellipses, angled bars, lines and text from the
   bar at the top. Drag pictures, WebM / MP4 videos, Lottie `.json` files and
   fonts straight onto the canvas from your PC. The dashed-box button adds a
   game screenshot to line your design up with; it never goes on air.
   - Drag to move, pull the handles to resize, Shift keeps the shape, Alt
     turns snapping off. Ctrl+G groups layers so they move and hide together.
   - Shapes take a colour or a gradient, rounded corners or a slant, an
     outline and a shadow or glow. Pictures can be cut to a circle, a rounded
     box or an angle.
   - Each layer has In and Out animations (▶ Play shows them).
   - **Import design…** (or drop a file on the canvas) brings in a GFX
     Engine graphic (.sccgfx), a Photoshop file (.psd) or a Figma file
     (.fig, from Figma's File → Save local copy) as layers. Text stays
     editable text; Figma rectangles and ellipses stay shapes, its pictures
     come in cropped as they show and its vector shapes as SVG pictures;
     other Photoshop layers become pictures; a GFX Engine field becomes a HUD
     variable. 4K designs are scaled to 1920 × 1080, and each Figma frame is
     a group (the first shown). Fonts the design uses but HUD Builder doesn't
     have are listed to add.
3. **Variables** are what you change during the show: a score, a team name, a
   colour, a picture, an on / off switch. Make one with the **+** next to
   Variables, then drag it onto the canvas (it makes the right layer) or onto
   a layer (it links it):
   - a text or number variable fills a text layer;
   - a colour variable colours a shape;
   - a picture variable fills a picture layer;
   - an on / off variable shows the layer only while it's on;
   - a number dropped on a shape makes it a bar that fills by that number.
   In text, mix words and variables: `GAME {{HUD!Game number}}`.
   **Game data** (under Variables) is what the SCC game HUDs send: kills,
   gold, round score, players... for the HUD's game, plus the teams from the
   GFX Engine's Global. Drag one onto the canvas or a layer, like a variable.
   It comes live from the SCC GFX Engine (Settings → GFX Engine; the one on
   this PC by default) once the game's HUD is connected to it; until then the
   editor shows example values.
   **Setup guide** (Game data → Setup guide; it starts by itself after a
   design is imported) asks for one piece at a time - "Which layer is the
   left team's kills?" - and links the layer you click. It suggests layers
   whose names match (KILLS LEFT, player1-kda, team logo left...).
4. **Control panel.** Every variable gets a control: a text box, − / + for
   numbers, a switch, a colour or picture picker. **Hide HUD / Show HUD**
   plays the whole HUD out and back in. **Open in browser** opens the same
   panel on its own page, for another PC, a tablet or a phone.
5. **Go live.** Add the browser-source address to OBS or vMix (1920 × 1080).
   For OBS on another PC, turn on **Settings → Let other PCs show the HUDs**
   and use the network address shown there.

**Export .scchud** (Go live) saves a HUD with its pictures and fonts as one
file; **Import** on My HUDs opens it, on this PC or another. Import on My
HUDs also takes a .sccgfx, .psd or .fig, as a new HUD.

## Where things are

| Path | What |
| --- | --- |
| `huds/<id>/hud.json` | a HUD: its layers, variables and their current values |
| `huds/<id>/assets/` | its pictures, videos and fonts |
| `config.json` | the port (8800) and the network setting |

Pages: `/` the app, `/hud/<id>` the browser source (`?bg=black` to look at it
in a browser, `?anim=0` to cut on and off), `/control/<id>` the control panel.

## Running from source

```
python -m hudbuilder            # the server; open http://localhost:8800/
python -m hudbuilder.gui        # the desktop window (pip install pywebview)
python -m unittest discover -s tests -v
```

Every push to a build branch builds the Windows app and publishes a release
(`v1.0.N`); `[no release]` in the commit message builds without publishing.

## Coming next

Phase 2 links HUDs to the GFX Engine's Global (teams, logos, colours, series
score) and to the SCC game HUDs' live data. After that: player cards that
repeat for every player, icons that change with the data (agents, champions),
kill feeds, web-feed and screen-reader data for new games, and templates.
