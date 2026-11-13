"""Each game's data: what the SCC game HUDs send to the GFX Engine, and the
GFX Engine's Global information (the teams). HUD Builder reads them from the
GFX Engine (enginefeed.py), so a layer shows {{League HUD!KILLS LEFT}} or
{{Global!Left name}} like a GFX Engine graphic does.

catalog(game) -> [{"group", "table", "fields": [{"token", "field", "label",
"kind", "sample", "guide"}]}]: label reads as "Which layer shows the <label>?";
kind is text / number / image / color / toggle (1 when on); guide: asked in the
setup guide after a design is imported.

The field names are the HUDs' own (lolhud/state.py, valhud/game.py, and the
_engine_snapshot of codhud, rlhud, smashhud and owhud): keep them in step.
"""

SOURCES = {"lol": "League HUD", "valorant": "VALORANT HUD", "cod": "CoD HUD", "rl": "Rocket League HUD",
           "smash": "Smash HUD", "overwatch": "Overwatch HUD"}
SIDES = (("left", "Left", "left team's"), ("right", "Right", "right team's"))


def _f(field, label, kind="text", sample="", guide=False):
    return {"field": field, "label": label, "kind": kind, "sample": str(sample), "guide": guide}


# --- Global: the teams, from the GFX Engine -------------------------------------------------------
def _global():
    teams = []
    for _, S, who in SIDES:
        teams += [_f(f"{S} name", f"{who} name", sample="Blue Team" if S == "Left" else "Red Team", guide=True),
                  _f(f"{S} short", f"{who} short name", sample="BLU" if S == "Left" else "RED", guide=True),
                  _f(f"{S} logo", f"{who} logo", "image", guide=True),
                  _f(f"{S} color", f"{who} colour (a shape filled with it)", "color",
                     "#2f6bff" if S == "Left" else "#ff3b3b", guide=True),
                  _f(f"{S} score", f"{who} series score (maps / games won)", "number", 1 if S == "Left" else 0, guide=True)]
    pips = []
    for _, S, who in SIDES:
        for n in range(1, 4):
            pips.append(_f(f"{S} won {n}", f"{who} series box {n} (lit once they've won {n})", "toggle",
                           1 if S == "Left" and n == 1 else "", guide=True))
    for n in range(1, 4):
        pips.append(_f(f"Game box {n}", f"series box {n} (shown when the series is long enough)", "toggle", 1 if n <= 2 else ""))
    match = [_f("Event", "event name", sample="SCC Championship", guide=True), _f("Stage", "stage", sample="Grand Final", guide=True),
             _f("Best of", "best of (3, 5...)", "number", 3), _f("Game", "game number", "number", 1),
             _f("Tournament logo", "tournament logo", "image", guide=True), _f("Sponsor logo", "sponsor logo", "image")]
    return [("Teams", teams), ("Series boxes", pips), ("Event", match)]


# --- the games -------------------------------------------------------------------------------------
def _lol():
    match = [_f("TIMER", "game clock", sample="18:42", guide=True)]
    for side, S, who in SIDES:
        U = side.upper()
        match += [_f(f"KILLS {U}", f"{who} kills", "number", 12, True),
                  _f(f"GOLD {U}", f"{who} gold", sample="38.4k", guide=True),
                  _f(f"TURRETS {U}", f"{who} turrets", "number", 4, True),
                  _f(f"DRAGONS {U}", f"{who} dragons", "number", 2, True),
                  _f(f"VOID GRUB {U}", f"{who} void grubs", "number", 3, True),
                  _f(f"HERALDS {U}", f"{who} heralds", "number", 1, True),
                  _f(f"BARONS {U}", f"{who} barons", "number", 0, True),
                  _f(f"INHIBS {U}", f"{who} inhibitors", "number", 0),
                  _f(f"ELDERS {U}", f"{who} elder dragons", "number", 0),
                  _f(f"ATAKHANS {U}", f"{who} Atakhans", "number", 0),
                  _f(f"DRAGON TYPES {U}", f"{who} dragon types", sample="infernal, ocean"),
                  _f(f"GOLD DIFF {U}", f"{who} gold lead (only while ahead)", sample="+2.1k", guide=True)]
    timers = [_f("NEXT DRAGON", "next dragon timer", sample="1:12", guide=True), _f("NEXT BARON", "next Baron timer", sample="3:30", guide=True),
              _f("NEXT HERALD", "next Herald timer", sample=""), _f("NEXT GRUBS", "next grubs timer", sample=""),
              _f("NEXT ELDER", "next elder timer", sample=""),
              _f("BARON BUFF TIME", "Baron buff time left", sample=""), _f("BARON BUFF SIDE", "Baron buff side (left / right)"),
              _f("ELDER BUFF TIME", "elder buff time left", sample=""), _f("ELDER BUFF SIDE", "elder buff side (left / right)")]
    groups = [("Match", match), ("Objective timers", timers)]
    for n in range(1, 11):
        side = "left" if n <= 5 else "right"
        who = f"{side} player {n if n <= 5 else n - 5}'s"
        groups.append((f"Player {n} ({side})", [
            _f(f"P{n} NAME", f"{who} name", sample=f"Player{n}", guide=True),
            _f(f"P{n} CHAMPION ICON", f"{who} champion picture", "image", guide=True),
            _f(f"P{n} CHAMPION", f"{who} champion name", sample="Ahri"),
            _f(f"P{n} LEVEL", f"{who} level", "number", 11, True),
            _f(f"P{n} KDA", f"{who} K/D/A", sample="3/1/4", guide=True),
            _f(f"P{n} CS", f"{who} CS", "number", 182, True),
            _f(f"P{n} GOLD", f"{who} gold", sample="7.2k"),
            _f(f"P{n} VISION", f"{who} vision score", "number", 21),
            _f(f"P{n} DEAD", f"{who} dead (1 while dead)", "toggle", "", True),
            _f(f"P{n} RESPAWN", f"{who} respawn timer", sample="")]))
    return groups


def _valorant():
    match = [_f("MAP", "map name", sample="Ascent", guide=True), _f("ROUND", "round number", "number", 14, True),
             _f("TIMER", "round timer", sample="1:23", guide=True), _f("PHASE", "phase (buy, combat, end)", sample="COMBAT"),
             _f("SPIKE", "spike state (PLANTED, DEFUSED...)", sample=""), _f("ROUND WINNER", "round winner (LEFT / RIGHT)")]
    for side, S, who in SIDES:
        U = side.upper()
        match += [_f(f"SCORE {U}", f"{who} round score", "number", 7 if U == "LEFT" else 6, True),
                  _f(f"SIDE {U}", f"{who} side (ATTACK / DEFENSE)", sample="ATTACK" if U == "LEFT" else "DEFENSE", guide=True),
                  _f(f"ALIVE {U}", f"{who} players alive", "number", 5, True),
                  _f(f"CREDITS {U}", f"{who} team credits", "number", 12400)]
    groups = [("Match", match)]
    for side, S, who in SIDES:
        U = side.upper()
        for n in range(1, 6):
            k, w = f"{U} P{n}", f"{side} player {n}'s"
            groups.append((f"{S} player {n}", [
                _f(f"{k} NAME", f"{w} name", sample=f"Player{n}", guide=True),
                _f(f"{k} AGENT IMAGE", f"{w} agent picture", "image", guide=True),
                _f(f"{k} AGENT", f"{w} agent name", sample="Jett"),
                _f(f"{k} HP", f"{w} health", "number", 100, True),
                _f(f"{k} SHIELD", f"{w} shield", "number", 50, True),
                _f(f"{k} CREDITS", f"{w} credits", "number", 3900, True),
                _f(f"{k} WEAPON", f"{w} weapon", sample="Vandal", guide=True),
                _f(f"{k} K", f"{w} kills", "number", 12, True), _f(f"{k} D", f"{w} deaths", "number", 9, True),
                _f(f"{k} A", f"{w} assists", "number", 4, True), _f(f"{k} FK", f"{w} first kills", "number", 2),
                _f(f"{k} ULT", f"{w} ult points (5/7)", sample="5/7", guide=True),
                _f(f"{k} ALIVE", f"{w} alive (1 while alive)", "toggle", 1, True)]))
    return groups


def _cod():
    match = [_f("spectated_name", "spectated player's name", sample="Player1", guide=True),
             _f("spectated_side", "spectated player's side (left / right)", sample="left"),
             _f("hud", "caster HUD state", sample="on")]
    groups = [("Match", match)]
    for side, S, who in SIDES:
        for n in range(1, 5):
            k, w = f"{side}_p{n}", f"{side} player {n}'s"
            groups.append((f"{S} player {n}", [
                _f(f"{k}_name", f"{w} name", sample=f"Player{n}", guide=True),
                _f(f"{k}_ign", f"{w} in-game name", sample=f"Player{n}"),
                _f(f"{k}_kills", f"{w} kills (after the game)", "number", 24),
                _f(f"{k}_deaths", f"{w} deaths (after the game)", "number", 18),
                _f(f"{k}_assists", f"{w} assists (after the game)", "number", 6),
                _f(f"{k}_damage", f"{w} damage (after the game)", "number", 3420),
                _f(f"{k}_ntk", f"{w} non-traded kills (after the game)", "number", 9),
                _f(f"{k}_streak", f"{w} best streak (after the game)", "number", 5)]))
    groups.append(("After the game", [_f("postgame", "post-game stats are in (1)", "toggle")]))
    return groups


def _rl():
    STATS = [("goals", "goals", 1), ("shots", "shots", 3), ("assists", "assists", 0), ("saves", "saves", 2),
             ("demos", "demos", 0), ("score", "score", 310), ("touches", "touches", 22)]
    match = [_f("clock", "game clock", sample="3:12", guide=True), _f("overtime", "overtime (1 in overtime)", "toggle", "", True),
             _f("left_goals", "left team's goals", "number", 2, True), _f("right_goals", "right team's goals", "number", 1, True),
             _f("replay", "goal replay (1 during a replay)", "toggle"), _f("phase", "phase (countdown, live, goal...)", sample="live"),
             _f("live", "ball in play (1)", "toggle", 1), _f("team_size", "players a side", "number", 3),
             _f("arena", "arena", sample="DFH Stadium"), _f("ball_speed", "ball speed (km/h)", "number", 87)]
    sp = "spectated player's"
    target = [_f("target", f"{sp} name", sample="Player1", guide=True), _f("target_boost", f"{sp} boost (0-100)", "number", 64, True)]
    target += [_f(f"target_{k}", f"{sp} {t}", "number", s, k in ("goals", "shots", "assists", "saves")) for k, t, s in STATS]
    target += [_f("target_speed", f"{sp} speed (km/h)", "number", 92), _f("target_logo", f"{sp} team logo", "image", "", True),
               _f("target_color", f"{sp} team colour", "color", "#2f6bff", True), _f("target_side", f"{sp} side (left / right)")]
    groups = [("Match", match), ("Spectated player", target)]
    for side, S, who in SIDES:
        for n in range(1, 4):
            k, w = f"{side}_p{n}", f"{side} player {n}'s"
            groups.append((f"{S} player {n}", [_f(f"{k}_name", f"{w} name", sample=f"Player{n}", guide=True),
                                              _f(f"{k}_boost", f"{w} boost (0-100)", "number", 48, True)]
                           + [_f(f"{k}_{s}", f"{w} {t}", "number", v) for s, t, v in STATS]
                           + [_f(f"{k}_spectated", f"{w} highlight while spectated (1)", "toggle", "", True),
                              _f(f"{k}_demolished", f"{w} demolished (1)", "toggle")]))
    groups.append(("Goal (for 8 seconds after one)", [
        _f("goal_scorer", "goal scorer", sample="Player1"), _f("goal_assister", "goal assist by"),
        _f("goal_speed", "goal speed (km/h)", "number", 104), _f("goal_side", "goal team side (left / right)")]))
    return groups


def _smash():
    match = [_f("match", "match label", sample="Crew Battle", guide=True),
             _f("stocks_per_crew", "stocks per crew", "number", 12), _f("stocks_per_game", "stocks per game", "number", 3)]
    for side, S, who in SIDES:
        match += [_f(f"{side}_player", f"{who} player on stage", sample=f"Player{1 if side == 'left' else 2}", guide=True),
                  _f(f"{side}_stocks", f"{who} crew stocks left", "number", 9, True)]
    groups = [("Match", match)]
    for side, S, who in SIDES:
        groups.append((f"{S} crew", [_f(f"{side}_p{n}_name", f"{side} crew player {n}'s name", sample=f"Player{n}", guide=n <= 5)
                                     for n in range(1, 9)]))
    return groups


def _overwatch():
    match = [_f("map_name", "current map", sample="King's Row", guide=True), _f("map_mode", "current mode", sample="Hybrid", guide=True),
             _f("map_number", "map number", "number", 2, True), _f("first_to", "first to", "number", 3), _f("info", "info line", sample="")]
    for side, S, who in SIDES:
        match += [_f(f"{side}_record", f"{who} record", sample="4-1")]
    maps = []
    for n in range(1, 8):
        maps += [_f(f"map{n}_name", f"map {n} name", sample=""), _f(f"map{n}_mode", f"map {n} mode"),
                 _f(f"map{n}_winner", f"map {n} winner")]
    groups = [("Match", match), ("Maps", maps)]
    for side, S, who in SIDES:
        for n in range(1, 6):
            k, w = f"{side}_p{n}", f"{side} player {n}'s"
            groups.append((f"{S} player {n}", [
                _f(f"{k}_name", f"{w} name", sample=f"Player{n}", guide=True),
                _f(f"{k}_hero_icon", f"{w} hero picture", "image", "", True), _f(f"{k}_hero", f"{w} hero", sample="Tracer"),
                _f(f"{k}_kills", f"{w} eliminations", "number", 14), _f(f"{k}_assists", f"{w} assists", "number", 6),
                _f(f"{k}_deaths", f"{w} deaths", "number", 5), _f(f"{k}_damage", f"{w} damage", "number", 8200),
                _f(f"{k}_healing", f"{w} healing", "number", 0)]))
    return groups


GAMES = {"lol": _lol, "valorant": _valorant, "cod": _cod, "rl": _rl, "smash": _smash, "overwatch": _overwatch}


def token(table, field):
    return "{{" + table + "!" + field + "}}"


def catalog(game):
    """The data a HUD for this game can show: the teams (Global), then the game's own."""
    out = []
    for name, fields in _global():
        out.append({"group": name, "table": "Global", "fields": [dict(f, token=token("Global", f["field"])) for f in fields]})
    if game in GAMES:
        src = SOURCES[game]
        for name, fields in GAMES[game]():
            out.append({"group": name, "table": src, "fields": [dict(f, token=token(src, f["field"])) for f in fields]})
    return out


def samples(game):
    """{table: rows} of example values, for the editor while no game is running."""
    out = {}
    for g in catalog(game):
        rows = out.setdefault(g["table"], [["Field", "Value"]])
        rows += [[f["field"], f["sample"]] for f in g["fields"]]
    return out
