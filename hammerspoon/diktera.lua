-- Lokal diktering: dubbeltryck på fn startar, ett enkeltryck på fn stoppar och klistrar in texten där markören står.
-- Esc under inspelning avbryter. fn + annan tangent (fn+pil, fn+Delete, fn+F ...) räknas inte som tryck.
-- Inspelning: rost/diktera_rec.py i repot (varm, styrs via stdin). Tal till text: tjänsten local.audio.asr (KB-Whisper).

local M = {}

-- ~/.hammerspoon/diktera.lua är en symlänk till repot: följ den för att hitta rost/ oavsett var repot ligger
local REPO = (hs.fs.pathToAbsolute(hs.configdir .. "/diktera.lua") or ""):match("^(.*)/hammerspoon/diktera%.lua$")
    or (os.getenv("HOME") .. "/projects/lokal-stt")
local REC = REPO .. "/rost/diktera_rec.py"
local PYTHON = REPO .. "/.venv/bin/python"   -- install.sh länkar .venv till Python-miljön
local FN_KEYCODE = 63          -- kVK_Function
local TAP_MAX = 0.35           -- längsta tid fn får hållas för att räknas som ett tryck (s)
local DOUBLE_GAP = 0.45        -- längsta tid mellan två tryck för ett dubbeltryck (s)
local ESC_KEYCODE = 53
local START_SOUND = "Tink"     -- systemljud när inspelningen startar (/System/Library/Sounds), nil = tyst
local SOUND_VOLUME = 0.35

local state = "idle"           -- idle | recording | busy
local fnDownAt, fnUsed, lastTapAt = nil, false, 0
local rec, recBuf = nil, ""
local menu = hs.menubar.new()

local BUSY_MAX = 75            -- längsta tid i ⏳ innan inspelaren startas om (s)
local busyTimer = nil

local function setState(s, note)
  state = s
  if busyTimer then busyTimer:stop(); busyTimer = nil end
  if s == "busy" then          -- skydd mot att fastna: döda inspelaren, då går läget till idle och den startar om
    busyTimer = hs.timer.doAfter(BUSY_MAX, function()
      busyTimer = nil
      if state == "busy" then
        hs.alert.show("Diktering: ingen text på " .. BUSY_MAX .. " s, avbryter", 4)
        if rec then rec:terminate() else setState("idle") end
      end
    end)
  end
  local icon = ({ idle = "🎙", recording = "🔴", busy = "⏳" })[s]
  if menu then menu:setTitle(icon); menu:setTooltip(note or ("Diktering: " .. s)) end
end

local function paste(text)
  if text == nil or text == "" then return end
  local saved = hs.pasteboard.readAllData()
  hs.pasteboard.setContents(text)
  hs.eventtap.keyStroke({ "cmd" }, "v", 0)
  hs.timer.doAfter(0.5, function()            -- lämna tillbaka det du hade i urklipp
    if saved and next(saved) then hs.pasteboard.writeAllData(saved) else hs.pasteboard.clearContents() end
  end)
end

local function onRecLine(line)
  local ok, msg = pcall(hs.json.decode, line)
  if not ok or type(msg) ~= "table" then return end
  if msg.error then
    hs.alert.show("Diktering: " .. msg.error, 4); setState("idle")
  elseif msg.text ~= nil then
    paste(msg.text); setState("idle")
  elseif msg.cancelled then
    setState("idle")
  end
end

local startRecorder
startRecorder = function()
  recBuf = ""
  rec = hs.task.new(PYTHON, function(code)      -- avslutades: starta om om några sekunder
    rec = nil
    if state ~= "idle" then setState("idle") end
    hs.timer.doAfter(3, startRecorder)
  end, function(_, out, err)
    recBuf = recBuf .. (out or "")
    for line in recBuf:gmatch("([^\n]*)\n") do onRecLine(line) end
    recBuf = recBuf:match("[^\n]*$") or ""
    if err and err ~= "" then print("diktera_rec: " .. err) end
    return true
  end, { REC })
  rec:setEnvironment({ HOME = os.getenv("HOME"), PATH = "/usr/bin:/bin", ASR_LANG = "sv" })
  rec:start()
end

local function send(cmd) if rec then rec:setInput(cmd .. "\n") end end

local function onTap()
  local now = hs.timer.secondsSinceEpoch()
  if state == "recording" then
    setState("busy", "Skriver ut …"); send("stop"); lastTapAt = 0
  elseif state == "idle" then
    if now - lastTapAt <= DOUBLE_GAP then
      lastTapAt = 0
      if not rec then hs.alert.show("Diktering: inspelaren startar, försök igen om en stund"); return end
      if START_SOUND then
        local snd = hs.sound.getByName(START_SOUND)
        if snd then snd:volume(SOUND_VOLUME):play() end
      end
      setState("recording", "Spelar in – tryck fn för att sluta, Esc för att avbryta"); send("start")
    else
      lastTapAt = now
    end
  end
end

M.tap = hs.eventtap.new({ hs.eventtap.event.types.flagsChanged, hs.eventtap.event.types.keyDown }, function(e)
  local t = e:getType()
  if t == hs.eventtap.event.types.keyDown then
    if fnDownAt then fnUsed = true end                       -- fn + något: ingen diktering
    if state == "recording" and e:getKeyCode() == ESC_KEYCODE then
      send("cancel"); return true                            -- svälj Esc
    end
    return false
  end
  local flags = e:getFlags()
  if e:getKeyCode() == FN_KEYCODE then
    if flags.fn then
      fnDownAt, fnUsed = hs.timer.secondsSinceEpoch(), (flags.cmd or flags.alt or flags.ctrl or flags.shift) and true or false
    elseif fnDownAt then
      local held = hs.timer.secondsSinceEpoch() - fnDownAt
      local used = fnUsed
      fnDownAt, fnUsed = nil, false
      if not used and held <= TAP_MAX then onTap() end
    end
  elseif fnDownAt then
    fnUsed = true                                            -- en annan modifierare under fn
  end
  return false
end)

function M.start()
  setState("idle")
  if menu then
    menu:setMenu(function() return {
      { title = "Diktering: dubbeltryck fn startar, fn stoppar, Esc avbryter", disabled = true },
      { title = "Status: " .. state, disabled = true },
      { title = "-" },
      { title = "Starta om inspelaren", fn = function() if rec then rec:terminate() else startRecorder() end end },
    } end)
  end
  startRecorder()
  M.tap:start()
  -- macOS stänger av en eventtap som svarat för långsamt: slå på den igen
  M.watch = hs.timer.doEvery(5, function() if not M.tap:isEnabled() then M.tap:start() end end)
end

return M
