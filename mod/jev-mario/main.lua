-- name: Jev Mario
-- description: Lets a Python program (rule-based or the Jev decision model) steer Mario.\nChat: /jev on | /jev off

-- How it works
--   Game -> Python: every few frames Mario's state is written to this mod's
--                   modfs file (sav/jev-mario.modfs, entry "state.json").
--   Python -> Game: Python writes one command line into sav/jev-cmd.modfs
--                   (entry "cmd.txt"), which this mod reloads regularly.
-- Frame-exact input (stick, buttons) is produced here, inside the game.
-- Python only picks the next short action, so network delays never matter.

local STATE_EVERY = 6        -- frames between state writes (30 fps -> 5x per second)
local CMD_EVERY = 3          -- frames between command reloads
local CMD_MODFS = "jev-cmd"
local OBJ_RADIUS = 4000      -- only report objects closer than this
local MAX_OBJS = 12
local PROBE_DISTS = { 150, 350 }

local enabled = true
local frame = 0
local myFs = nil
local saveFailed = false
local lastError = nil

-- current command
local cmd = { id = -1, act = "stop", tx = 0, tz = 0, frames = 0 }
local cmdFrame = 0           -- frames since the current command started
local lastCmdId = -1

-- camera calibration: offset between stick angle and resulting world yaw
local camOffset = nil
local lastStickYaw = nil

mod_fs_hide_errors(true)

--------------------------------------------------------------------------
-- helpers
--------------------------------------------------------------------------

local function num(v)
    if v ~= v or v == math.huge or v == -math.huge then return "0" end
    return string.format("%d", math.floor(v + 0.5))
end

local function obj_kind(o)
    if obj_has_behavior_id(o, id_bhvYellowCoin) ~= 0
    or obj_has_behavior_id(o, id_bhvMovingYellowCoin) ~= 0
    or obj_has_behavior_id(o, id_bhvCoinFormationSpawn) ~= 0
    or obj_has_behavior_id(o, id_bhvOneCoin) ~= 0
    or obj_has_behavior_id(o, id_bhvSingleCoinGetsSpawned) ~= 0 then
        return "coin"
    end
    if obj_has_behavior_id(o, id_bhvRedCoin) ~= 0 then return "red" end
    if obj_has_behavior_id(o, id_bhvBlueCoinJumping) ~= 0
    or obj_has_behavior_id(o, id_bhvHiddenBlueCoin) ~= 0 then
        return "blue"
    end
    if obj_has_behavior_id(o, id_bhvStar) ~= 0
    or obj_has_behavior_id(o, id_bhvSpawnedStar) ~= 0 then
        return "star"
    end
    return nil
end

local function collect_objects(m)
    local found = {}
    local o = obj_get_first(OBJ_LIST_LEVEL)
    while o ~= nil do
        local kind = obj_kind(o)
        if kind ~= nil then
            local dx, dy, dz = o.oPosX - m.pos.x, o.oPosY - m.pos.y, o.oPosZ - m.pos.z
            local d = math.sqrt(dx * dx + dy * dy + dz * dz)
            if d < OBJ_RADIUS then
                found[#found + 1] = { k = kind, x = o.oPosX, y = o.oPosY, z = o.oPosZ, d = d }
            end
        end
        o = obj_get_next(o)
    end
    table.sort(found, function(a, b) return a.d < b.d end)
    local parts = {}
    for i = 1, math.min(#found, MAX_OBJS) do
        local f = found[i]
        parts[#parts + 1] = string.format('{"k":"%s","x":%s,"y":%s,"z":%s}', f.k, num(f.x), num(f.y), num(f.z))
    end
    return "[" .. table.concat(parts, ",") .. "]"
end

-- floor height around Mario in 8 world directions (yaw 0 = +Z)
local function collect_probes(m)
    local parts = {}
    for i = 0, 7 do
        local yaw = i * 0x2000
        local rad = yaw * math.pi / 0x8000
        local vals = {}
        for _, dist in ipairs(PROBE_DISTS) do
            local px = m.pos.x + math.sin(rad) * dist
            local pz = m.pos.z + math.cos(rad) * dist
            local fy = find_floor_height(px, m.pos.y + 300, pz)
            vals[#vals + 1] = num(fy - m.pos.y)
        end
        parts[#parts + 1] = string.format('{"yaw":%d,"dy":[%s]}', yaw, table.concat(vals, ","))
    end
    return "[" .. table.concat(parts, ",") .. "]"
end

local function write_state(m)
    if myFs == nil then
        myFs = mod_fs_get() or mod_fs_create()
        if myFs == nil then return end
    end
    local file = mod_fs_get_file(myFs, "state.json")
    if file == nil then
        file = mod_fs_create_file(myFs, "state.json", true)
        if file == nil then return end
    end
    local np = gNetworkPlayers[0]
    local air = (m.action & ACT_FLAG_AIR) ~= 0
    local water = (m.action & ACT_FLAG_SWIMMING) ~= 0
    local json = string.format(
        '{"t":%d,"ack":%d,"enabled":%s,"level":%d,"area":%d,' ..
        '"x":%s,"y":%s,"z":%s,"yaw":%d,"fvel":%s,"vy":%s,' ..
        '"action":%d,"air":%s,"water":%s,"health":%d,"coins":%d,"stars":%d,' ..
        '"floor_dy":%s,"objs":%s,"probes":%s}',
        frame, lastCmdId, tostring(enabled), np.currLevelNum, np.currAreaIndex,
        num(m.pos.x), num(m.pos.y), num(m.pos.z), m.faceAngle.y, num(m.forwardVel), num(m.vel.y),
        m.action, tostring(air), tostring(water), m.health >> 8, m.numCoins, m.numStars,
        num(m.floorHeight - m.pos.y), collect_objects(m), collect_probes(m))
    mod_fs_file_rewind(file)
    mod_fs_file_erase(file, file.size)
    mod_fs_file_write_string(file, json)
    saveFailed = not mod_fs_save(myFs)
end

-- command line format: "id=12 act=walk tx=100 tz=-250 frames=30"
local function parse_cmd(line)
    local c = {}
    for k, v in string.gmatch(line, "(%w+)=([%w%.%-_]+)") do c[k] = v end
    local id = tonumber(c.id)
    if id == nil or c.act == nil then return nil end
    return {
        id = id,
        act = c.act,
        tx = tonumber(c.tx) or 0,
        tz = tonumber(c.tz) or 0,
        frames = tonumber(c.frames) or 30,
    }
end

local function read_cmd()
    local fs = mod_fs_reload(CMD_MODFS)
    if fs == nil then return end
    local file = mod_fs_get_file(fs, "cmd.txt")
    if file == nil then return end
    mod_fs_file_rewind(file)
    local line = mod_fs_file_read_string(file)
    if line == nil then return end
    local c = parse_cmd(line)
    if c ~= nil and c.id ~= lastCmdId then
        cmd = c
        cmdFrame = 0
        lastCmdId = c.id
    end
end

--------------------------------------------------------------------------
-- input
--------------------------------------------------------------------------

-- point the stick so Mario runs toward world yaw `yaw`
local function set_stick_toward(c, yaw)
    local offset = camOffset
    if offset == nil then offset = gMarioStates[0].area.camera.yaw end
    local rel = (yaw - offset) * math.pi / 0x8000
    c.stickX = math.sin(rel) * 64
    c.stickY = -math.cos(rel) * 64
    c.stickMag = 64
    lastStickYaw = atan2s(-c.stickY, c.stickX)
end

local function apply_command(m)
    local c = m.controller
    c.stickX, c.stickY, c.stickMag = 0, 0, 0
    c.buttonDown, c.buttonPressed = 0, 0
    lastStickYaw = nil

    if cmd.act == "stop" then return end

    local targetYaw = atan2s(cmd.tz - m.pos.z, cmd.tx - m.pos.x)
    set_stick_toward(c, targetYaw)

    if cmd.act == "jump" then
        -- press A once, hold it for a higher jump
        if cmdFrame == 0 then c.buttonPressed = A_BUTTON end
        if cmdFrame < 12 then c.buttonDown = c.buttonDown | A_BUTTON end
    elseif cmd.act == "longjump" then
        -- run 6 frames, Z, then A while holding Z
        if cmdFrame == 6 then c.buttonPressed = Z_TRIG end
        if cmdFrame >= 6 and cmdFrame <= 8 then c.buttonDown = Z_TRIG end
        if cmdFrame == 8 then
            c.buttonPressed = A_BUTTON
            c.buttonDown = Z_TRIG | A_BUTTON
        end
    elseif cmd.act == "dive" then
        if cmdFrame == 0 then c.buttonPressed = B_BUTTON; c.buttonDown = B_BUTTON end
    end
end

--------------------------------------------------------------------------
-- hooks
--------------------------------------------------------------------------

local function before_mario_update(m)
    if m.playerIndex ~= 0 then return end
    frame = frame + 1

    if frame % CMD_EVERY == 0 then
        local ok, err = pcall(read_cmd)
        if not ok then lastError = "cmd: " .. tostring(err) end
    end

    -- only override the controller while a command is running; if Python
    -- stops sending, the command runs out and the player has control again
    if enabled and lastCmdId >= 0 and cmdFrame < cmd.frames then
        apply_command(m)
        cmdFrame = cmdFrame + 1
    end
end

local function mario_update(m)
    if m.playerIndex ~= 0 then return end

    -- learn how the camera rotates the stick: works in every camera mode
    if lastStickYaw ~= nil and m.intendedMag > 0 then
        camOffset = m.intendedYaw - lastStickYaw
    end

    if frame % STATE_EVERY == 0 then
        local ok, err = pcall(write_state, m)
        if not ok then lastError = "state: " .. tostring(err) end
    end
end

local function on_hud_render()
    if not enabled then return end
    djui_hud_set_resolution(RESOLUTION_DJUI)
    djui_hud_set_font(FONT_NORMAL)
    local label = "Jev: " .. cmd.act
    if lastCmdId < 0 or cmdFrame >= cmd.frames then label = "Jev: wartet auf Python" end
    if saveFailed then label = "Jev: Fehler beim Speichern" end
    djui_hud_print_text(label, 20, 20, 1, 1)
    if lastError ~= nil then
        djui_hud_print_text("Fehler: " .. lastError, 20, 50, 0.6, 0.6)
    end
end

local function on_jev_command(msg)
    if msg == "on" then
        enabled = true
        djui_chat_message_create("Jev steuert Mario.")
        return true
    elseif msg == "off" then
        enabled = false
        djui_chat_message_create("Jev aus, du steuerst selbst.")
        return true
    end
    return false
end

hook_event(HOOK_BEFORE_MARIO_UPDATE, before_mario_update)
hook_event(HOOK_MARIO_UPDATE, mario_update)
hook_event(HOOK_ON_HUD_RENDER, on_hud_render)
hook_chat_command("jev", "[on|off] Jev-Steuerung an oder aus", on_jev_command)
