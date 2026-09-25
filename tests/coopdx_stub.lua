-- Minimal fake of the SM64CoopDX Lua API, enough to run mod/jev-mario/main.lua
-- outside the game. Usage: lua5.4 tests/coopdx_stub.lua <main.lua> <state_out> <cmd_in>

local main_path, state_out, cmd_in = arg[1], arg[2], arg[3]

ACT_FLAG_AIR = 0x00000800
ACT_FLAG_SWIMMING = 0x00002000
A_BUTTON, B_BUTTON, Z_TRIG = 0x8000, 0x4000, 0x2000
OBJ_LIST_LEVEL = 6
HOOK_UPDATE, HOOK_MARIO_UPDATE, HOOK_BEFORE_MARIO_UPDATE, HOOK_ON_HUD_RENDER = 0, 1, 2, 3
RESOLUTION_DJUI, FONT_NORMAL = 0, 0
id_bhvYellowCoin, id_bhvMovingYellowCoin, id_bhvCoinFormationSpawn = 533, 301, 136
id_bhvOneCoin, id_bhvSingleCoinGetsSpawned, id_bhvRedCoin = 314, 367, 347
id_bhvBlueCoinJumping, id_bhvHiddenBlueCoin, id_bhvStar, id_bhvSpawnedStar = 48, 215, 409, 398

local hooks = {}
function hook_event(kind, fn) hooks[kind] = fn end
function hook_chat_command(name, desc, fn) hooks["chat_" .. name] = fn end
function djui_chat_message_create(msg) end
function djui_hud_set_resolution(r) end
function djui_hud_set_font(f) end
function djui_hud_print_text(t, x, y, sx, sy) HUD_TEXT = t end

-- SM64 atan2s(y, x): yaw whose cosine follows y and sine follows x
function atan2s(y, x)
    local a = math.floor(math.atan(x, y) * 32768 / math.pi + 0.5)
    return ((a + 32768) % 65536) - 32768
end

function find_floor_height(x, y, z)
    if x > 1000 then return -11000 end   -- a pit east of x = 1000
    return 0
end

-- objects
local objects = {
    { bhv = id_bhvYellowCoin, oPosX = 500, oPosY = 60, oPosZ = 0 },
    { bhv = id_bhvStar, oPosX = -300, oPosY = 400, oPosZ = 900 },
    { bhv = 999, oPosX = 10, oPosY = 0, oPosZ = 10 },   -- irrelevant object
}
function obj_get_first(list) return objects[1] end
function obj_get_next(o)
    for i, v in ipairs(objects) do if v == o then return objects[i + 1] end end
    return nil
end
function obj_has_behavior_id(o, id) return o.bhv == id and 1 or 0 end

-- modfs, backed by plain files
local fsHide = false
function mod_fs_hide_errors(h) fsHide = h end
local myFs = nil
function mod_fs_get(path)
    if path == nil then return myFs end
    return nil
end
function mod_fs_create()
    myFs = { files = {} }
    return myFs
end
function mod_fs_get_file(fs, name) return fs.files[name] end
function mod_fs_create_file(fs, name, text)
    local f = { data = "", size = 0, offset = 0 }
    fs.files[name] = f
    return f
end
function mod_fs_file_rewind(f) f.offset = 0; return true end
function mod_fs_file_erase(f, n) f.data = f.data:sub(1, f.offset) .. f.data:sub(f.offset + n + 1); f.size = #f.data; return true end
function mod_fs_file_write_string(f, s)
    f.data = f.data:sub(1, f.offset) .. s .. f.data:sub(f.offset + #s + 1)
    f.offset = f.offset + #s
    f.size = #f.data
    return true
end
function mod_fs_file_read_string(f) if f.size == 0 then return nil end return f.data:sub(f.offset + 1) end
function mod_fs_save(fs)
    local h = assert(io.open(state_out, "w"))
    h:write(fs.files["state.json"].data)
    h:close()
    return true
end
function mod_fs_reload(path)
    local h = io.open(cmd_in, "r")
    if h == nil then return nil end
    local line = h:read("a")
    h:close()
    return { files = { ["cmd.txt"] = { data = line, size = #line, offset = 0 } } }
end

-- Mario
local controller = { stickX = 0, stickY = 0, stickMag = 0, buttonDown = 0, buttonPressed = 0 }
gMarioStates = { [0] = {
    playerIndex = 0,
    pos = { x = 0, y = 0, z = 0 }, vel = { x = 0, y = 0, z = 0 },
    faceAngle = { x = 0, y = 0, z = 0 },
    forwardVel = 0, action = 0x0C400201, health = 0x880, numCoins = 3, numStars = 1,
    floorHeight = 0, intendedMag = 0, intendedYaw = 0,
    controller = controller,
    area = { camera = { yaw = 0 } },  -- deliberately wrong: the mod must self-calibrate
} }
gNetworkPlayers = { [0] = { currLevelNum = 9, currAreaIndex = 1 } }

-- like the real game: reading a field that does not exist is an error
local function strict(t, name)
    for _, v in pairs(t) do
        if type(v) == "table" and getmetatable(v) == nil and v ~= controller then strict(v, name) end
    end
    return setmetatable(t, { __index = function(_, k) error("invalid key '" .. tostring(k) .. "' on " .. name, 2) end })
end
strict(gMarioStates[0], "MarioState")
strict(controller, "Controller")
strict(gNetworkPlayers[0], "NetworkPlayer")

dofile(main_path)

-- simulate the camera: intendedYaw = atan2s(-stickY, stickX) + camera yaw
local m = gMarioStates[0]
local CAMERA_YAW = 0x4000
local function run_frame()
    hooks[HOOK_BEFORE_MARIO_UPDATE](m)
    m.intendedMag = controller.stickMag / 2
    if controller.stickMag > 0 then
        m.intendedYaw = atan2s(-controller.stickY, controller.stickX) + CAMERA_YAW
        m.intendedYaw = ((m.intendedYaw + 32768) % 65536) - 32768
    end
    hooks[HOOK_MARIO_UPDATE](m)
    hooks[HOOK_ON_HUD_RENDER]()
end

local mode = arg[4] or "frames"
local n = tonumber(arg[5] or "12")
for _ = 1, n do run_frame() end
print(string.format("stick=%.1f,%.1f mag=%.1f down=%d pressed=%d intendedYaw=%d hud=%s",
    controller.stickX, controller.stickY, controller.stickMag,
    controller.buttonDown, controller.buttonPressed, m.intendedYaw, HUD_TEXT or ""))
