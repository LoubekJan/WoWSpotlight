local modelPath = "Character\\Human\\Male\\HumanMale.m2"
local loader = CreateFrame("Frame", nil, UIParent)
local panel = CreateFrame("Frame", "SpotlightDancePanel", UIParent)
local states = {
    idle = "Choose a dance video from your computer.",
    waiting = "Waiting for Spotlight to open the file picker...",
    selecting = "Choose a video in the Windows file picker.",
    uploading = "Uploading the video...",
    processing = "Creating your dance...",
    ready = "Your dance is ready.",
    error = "Spotlight could not load the dance. Try again.",
    cancelled = "Video selection cancelled.",
}
local bridgeStates = {"selecting", "uploading", "processing", "ready", "error", "cancelled"}
local uploadMarker = CreateFrame("Frame", nil, UIParent)
local markerColors = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {1, 0, 1}}
local markerSquares = {}
local state = "idle"
local requestDeadline
local playDeadline
local bridgeBound = false

uploadMarker:SetAllPoints(UIParent)
uploadMarker:SetFrameStrata("TOOLTIP")
uploadMarker:EnableMouse(false)
uploadMarker:Hide()
for index, color in ipairs(markerColors) do
    local square = uploadMarker:CreateTexture(nil, "OVERLAY")
    square:SetTexture(color[1], color[2], color[3], 1)
    markerSquares[index] = square
end

panel:SetSize(360, 164)
panel:SetPoint("CENTER", UIParent, "CENTER", 0, 0)
panel:SetFrameStrata("DIALOG")
panel:SetClampedToScreen(true)
panel:EnableMouse(true)
panel:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 24,
    insets = {left = 5, right = 5, top = 5, bottom = 5},
})
panel:Hide()

local title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
title:SetPoint("TOP", panel, "TOP", 0, -25)
title:SetText("Spotlight")

local statusText = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
statusText:SetPoint("TOPLEFT", panel, "TOPLEFT", 24, -61)
statusText:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -24, -61)
statusText:SetJustifyH("CENTER")

local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -5, -5)

local upload = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
upload:SetSize(144, 26)
upload:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 24, 24)
upload:SetText("Upload video")

local play = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
play:SetSize(144, 26)
play:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -24, 24)
play:SetText("Play dance")

local function showState(nextState, message)
    state = nextState
    statusText:SetText(message or states[nextState])
    if state == "ready" then play:Enable() else play:Disable() end
    if state == "waiting" or state == "selecting" or state == "uploading" or state == "processing" then
        upload:Disable()
    else
        upload:Enable()
    end
end

local function finishRequest()
    uploadMarker:Hide()
    requestDeadline = nil
    playDeadline = nil
end

local function onBridgeStatus(nextState)
    finishRequest()
    showState(nextState)
end

local function showSignal(playing)
    local width, height = UIParent:GetWidth(), UIParent:GetHeight()
    for index, square in ipairs(markerSquares) do
        local color = markerColors[playing and #markerColors + 1 - index or index]
        square:SetTexture(color[1], color[2], color[3], 1)
        square:ClearAllPoints()
        square:SetSize(width * 0.008, height * 0.014)
        square:SetPoint("CENTER", UIParent, "TOPLEFT", width * index * 0.01, -height * 0.02)
    end
    uploadMarker:Show()
end

upload:SetScript("OnClick", function()
    if requestDeadline then return end
    playDeadline = nil
    requestDeadline = GetTime() + 15
    showSignal(false)
    showState("waiting")
end)

play:SetScript("OnClick", function()
    if state == "ready" then
        panel:Hide()
        DoEmote("DANCE")
        playDeadline = GetTime() + 1.5
        showSignal(true)
    end
end)

local function bindBridge()
    if bridgeBound then return end
    for index, bridgeState in ipairs(bridgeStates) do
        local name = "SpotlightDanceBridge" .. index
        local button = _G[name] or CreateFrame("Button", name, UIParent)
        button:SetSize(1, 1)
        button:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", -4, -4)
        button:EnableMouse(false)
        button:SetScript("OnClick", function() onBridgeStatus(bridgeState) end)
        SetOverrideBindingClick(loader, true, "CTRL-SHIFT-F" .. (index + 4), name, "LeftButton")
    end
    bridgeBound = true
end

showState("idle")

loader:RegisterEvent("PLAYER_LOGIN")
loader:RegisterEvent("PLAYER_LOGOUT")
loader:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGOUT" then
        finishRequest()
        return
    elseif event == "PLAYER_REGEN_ENABLED" then
        self:UnregisterEvent(event)
        bindBridge()
        return
    end
    self:UnregisterEvent("PLAYER_LOGIN")

    -- Keep the model shown so it retains its selected sequence.
    local model = CreateFrame("Model", nil, self)
    self.preloadedModel = model
    model:SetWidth(1)
    model:SetHeight(1)
    model:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 0, 0)
    model:SetFrameStrata("BACKGROUND")
    model:EnableMouse(false)
    model:SetModel(modelPath)
    model:SetSequence(211)
    if InCombatLockdown() then self:RegisterEvent("PLAYER_REGEN_ENABLED") else bindBridge() end
end)

loader:SetScript("OnUpdate", function()
    if requestDeadline and GetTime() >= requestDeadline then
        finishRequest()
        showState("error", "Start the Windows companion and try again.")
    elseif playDeadline and GetTime() >= playDeadline then
        finishRequest()
    end
end)

SLASH_SPOTLIGHTDANCE1 = "/spotlight"
SlashCmdList["SPOTLIGHTDANCE"] = function()
    if panel:IsShown() then panel:Hide() else panel:Show() end
end

SLASH_SPOTLIGHTDANCELAB1 = "/spotlightpoc"
SlashCmdList["SPOTLIGHTDANCELAB"] = function()
    DoEmote("DANCE")
end
