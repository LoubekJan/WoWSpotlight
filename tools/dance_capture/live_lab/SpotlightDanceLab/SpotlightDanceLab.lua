local modelPath = "Character\\Human\\Male\\HumanMale.m2"
local loader = CreateFrame("Frame", nil, UIParent)
local panel = CreateFrame("Frame", "SpotlightDancePanel", UIParent)
local states = {
    idle = "Choose a dance video from your computer.",
    waiting = "Waiting for Spotlight to open the file picker...",
    selecting = "Choose a video in the Windows file picker.",
    uploading = "Uploading the video...",
    processing = "Creating your dance...",
    loading = "Loading the saved dance...",
    library = "Loading your dances...",
    renaming = "Saving the new name...",
    ready = "Your dance is ready.",
    error = "Spotlight could not load the dance. Try again.",
    cancelled = "Video selection cancelled.",
}
local bridgeStates = {"selecting", "uploading", "processing", "ready", "error", "cancelled"}
local signalMarker = CreateFrame("Frame", nil, UIParent)
local markerColors = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {1, 0, 1}}
local signalCodes = {
    upload = {0, 1, 2, 3}, play = {3, 2, 1, 0}, list = {0, 2, 3, 1},
    load = {1, 0, 3, 2}, rename = {2, 3, 0, 1}, retry = {3, 0, 1, 2},
    receiving = {1, 3, 0, 2},
}
local markerSquares = {}
local payloadSquares = {}
local payloadCount = 0
local state = "idle"
local pending
local requestDeadline
local playDeadline
local receiveDeadline
local libraryRefreshUntil
local bridgeBound = false
local playable = false
local retryable = false
local entries = {}
local page, pageCount = 1, 1
local selectedId
local loadedId
local queuedPage
local selectLoaded = false
local maxNameBytes = 96

signalMarker:SetAllPoints(UIParent)
signalMarker:SetFrameStrata("TOOLTIP")
signalMarker:EnableMouse(false)
signalMarker:Hide()
for index, color in ipairs(markerColors) do
    local square = signalMarker:CreateTexture(nil, "OVERLAY")
    square:SetTexture(color[1], color[2], color[3], 1)
    markerSquares[index] = square
end

panel:SetSize(472, 348)
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
statusText:SetPoint("TOPLEFT", panel, "TOPLEFT", 24, -55)
statusText:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -24, -55)
statusText:SetJustifyH("CENTER")

local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -5, -5)

local libraryTitle = panel:CreateFontString(nil, "OVERLAY", "GameFontNormal")
libraryTitle:SetPoint("TOPLEFT", panel, "TOPLEFT", 25, -87)
libraryTitle:SetText("My dances")

local previous = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
previous:SetSize(26, 22)
previous:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -111, -82)
previous:SetText("<")

local nextPage = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
nextPage:SetSize(26, 22)
nextPage:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -24, -82)
nextPage:SetText(">")

local pageLabel = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
pageLabel:SetPoint("CENTER", previous, "CENTER", 44, 0)

local emptyLabel = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
emptyLabel:SetPoint("TOP", panel, "TOP", 0, -164)
emptyLabel:SetText("No saved dances yet.")

local rows = {}
for index = 1, 4 do
    local row = CreateFrame("Button", nil, panel)
    row:SetSize(424, 25)
    row:SetPoint("TOPLEFT", panel, "TOPLEFT", 24, -113 - (index - 1) * 28)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    local label = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    label:SetPoint("LEFT", row, "LEFT", 10, 0)
    label:SetWidth(335)
    label:SetHeight(16)
    label:SetJustifyH("LEFT")
    local duration = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    duration:SetPoint("RIGHT", row, "RIGHT", -10, 0)
    row.label, row.duration = label, duration
    rows[index] = row
end

local nameInput = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
nameInput:SetSize(312, 24)
nameInput:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 30, 75)
nameInput:SetAutoFocus(false)
nameInput:SetMaxLetters(80)
nameInput:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)

local nameLabel = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
nameLabel:SetPoint("BOTTOMLEFT", nameInput, "TOPLEFT", -5, 4)
nameLabel:SetText("Selected dance name")

local rename = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
rename:SetSize(94, 24)
rename:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -24, 75)
rename:SetText("Rename")

local upload = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
upload:SetSize(144, 26)
upload:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 24, 24)
upload:SetText("Upload video")

local play = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
play:SetSize(144, 26)
play:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -24, 24)
play:SetText("Play dance")

local retry = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
retry:SetSize(130, 26)
retry:SetPoint("BOTTOM", panel, "BOTTOM", 0, 24)
retry:SetText("Retry conversion")

local function paintSquare(square, colorIndex, width, height, x, y, cellWidth, cellHeight)
    local color = markerColors[colorIndex + 1]
    square:SetTexture(color[1], color[2], color[3], 1)
    square:ClearAllPoints()
    square:SetSize(width * cellWidth, height * cellHeight)
    square:SetPoint("CENTER", UIParent, "TOPLEFT", width * x, -height * y)
    square:Show()
end

local function showSignal(action, payload)
    local width, height = UIParent:GetWidth(), UIParent:GetHeight()
    for index, square in ipairs(markerSquares) do
        paintSquare(square, signalCodes[action][index], width, height, index * 0.01, 0.02, 0.008, 0.014)
    end
    local cell = 0
    if payload then
        local packet = string.char(math.floor(#payload / 256), #payload % 256) .. payload
        for byteIndex = 1, #packet do
            local value = packet:byte(byteIndex)
            for power = 3, 0, -1 do
                local square = payloadSquares[cell + 1]
                if not square then
                    square = signalMarker:CreateTexture(nil, "OVERLAY")
                    payloadSquares[cell + 1] = square
                end
                paintSquare(square, math.floor(value / 4 ^ power) % 4, width, height,
                    (1 + cell % 48) * 0.01, 0.04 + math.floor(cell / 48) * 0.012, 0.006, 0.008)
                cell = cell + 1
            end
        end
    end
    for index = cell + 1, payloadCount do
        payloadSquares[index]:Hide()
    end
    payloadCount = cell
    signalMarker:Show()
end

local function setEnabled(button, enabled)
    if enabled then button:Enable() else button:Disable() end
end

local function refreshControls()
    local available = not pending and not receiveDeadline
    setEnabled(upload, available)
    setEnabled(play, available and playable and not libraryRefreshUntil)
    setEnabled(previous, available and page > 1)
    setEnabled(nextPage, available and page < pageCount)
    setEnabled(rename, available and selectedId and nameInput:GetText():find("%S"))
    setEnabled(retry, available and retryable)
    if retryable then retry:Show() else retry:Hide() end
    for _, row in ipairs(rows) do
        setEnabled(row, available)
    end
end

local function showState(nextState, message)
    state = nextState
    statusText:SetText(message or states[nextState])
    refreshControls()
end

local function selectEntry(entry)
    selectedId = entry and entry.id
    nameInput:SetText(entry and entry.name or "")
    for _, row in ipairs(rows) do
        if row.entry and row.entry.id == selectedId then
            row.label:SetTextColor(1, 0.82, 0)
        else
            row.label:SetTextColor(1, 1, 1)
        end
    end
    refreshControls()
end

local function renderLibrary()
    pageLabel:SetText(string.format("%d / %d", page, pageCount))
    if #entries == 0 then emptyLabel:Show() else emptyLabel:Hide() end
    local selected
    for index, row in ipairs(rows) do
        local entry = entries[index]
        row.entry = entry
        if entry then
            row.label:SetText((entry.name:gsub("|", "||")))
            row.duration:SetText(string.format("%.1fs", entry.duration / 1000))
            row:Show()
            if entry.id == (selectLoaded and loadedId or selectedId) then selected = entry end
        else
            row:Hide()
        end
    end
    selectLoaded = false
    selectEntry(selected)
end

local function endRequest()
    signalMarker:Hide()
    pending = nil
    requestDeadline = nil
    playDeadline = nil
end

local function beginRequest(action, payload, nextState, id)
    if pending or receiveDeadline then return end
    pending = {action = action, id = id, previousState = state}
    playDeadline = nil
    requestDeadline = GetTime() + 15
    if action == "load" or action == "upload" or action == "retry" then
        playable, retryable = false, false
    end
    showSignal(action, payload)
    showState(nextState)
end

local function onBridgeStatus(nextState)
    if not pending then return end
    signalMarker:Hide()
    playDeadline = nil
    if nextState == "selecting" or nextState == "uploading" or nextState == "processing" then
        requestDeadline = GetTime() + (nextState == "selecting" and 1800 or 660)
    else
        if nextState == "ready" then
            playable = true
            loadedId = pending.id
            libraryRefreshUntil = GetTime() + 3
            if pending.action == "upload" or pending.action == "retry" then
                selectLoaded = true
            end
        elseif nextState == "error" then
            retryable = pending.action == "retry" or pending.action == "upload" and state == "processing"
        end
        endRequest()
    end
    showState(nextState)
end

local function decodeHex(value)
    if #value % 2 ~= 0 or value:find("[^%x]") then return nil end
    return (value:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end))
end

local function validId(value)
    return #value == 32 and not value:find("[^0-9a-f]")
end

local function acceptPacket(packet)
    if #packet > 2048 then return end
    packet = packet:gsub("~", "\n")
    local header, body = packet:match("^([^\n]*)\n?(.*)$")
    local incomingPage, incomingCount, activeId, eligible = header:match("^library|(%d+)|(%d+)|([0-9a-f]*)|([01])$")
    if not incomingPage then
        incomingPage, incomingCount, activeId = header:match("^library|(%d+)|(%d+)|([0-9a-f]*)$")
    end
    if incomingPage then
        incomingPage, incomingCount = tonumber(incomingPage), tonumber(incomingCount)
        if incomingPage < 1 or incomingPage > incomingCount or activeId ~= "" and not validId(activeId) then return end
        local list = {}
        for line in body:gmatch("[^\n]+") do
            local id, duration, encodedName = line:match("^([0-9a-f]+)|(%d+)|(%x+)$")
            local name = encodedName and decodeHex(encodedName)
            if not id or not validId(id) or not name or #list >= #rows then return end
            list[#list + 1] = {id = id, duration = tonumber(duration), name = name}
        end
        entries, page, pageCount = list, incomingPage, incomingCount
        loadedId = activeId ~= "" and activeId or nil
        libraryRefreshUntil = nil
        if eligible then retryable = eligible == "1" end
        if pending and (pending.action == "list" or pending.action == "rename") then
            local oldState = pending.previousState
            local wasRename = pending.action == "rename"
            endRequest()
            if playable then
                showState("ready", wasRename and "Dance renamed." or nil)
            else
                showState(oldState, wasRename and "Dance renamed." or nil)
            end
        end
        renderLibrary()
        return true
    end
    local eligible, encodedMessage = header:match("^error|([01])|(%x+)$")
    local message = encodedMessage and decodeHex(encodedMessage)
    if message then
        retryable = eligible == "1"
        endRequest()
        showState("error", message:gsub("|", "||"))
        return true
    end
end

-- The companion sends a page into this addon-owned input, never into game chat.
local inbox = CreateFrame("EditBox", nil, UIParent)
inbox:SetSize(1, 1)
inbox:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 1, 1)
inbox:SetFontObject(GameFontHighlight)
inbox:SetAlpha(0)
inbox:SetAutoFocus(false)
inbox:SetMaxLetters(4096)
inbox:EnableMouse(false)
inbox:Hide()

local function closeInbox()
    receiveDeadline = nil
    inbox:ClearFocus()
    inbox:Hide()
    signalMarker:Hide()
    refreshControls()
end

inbox:SetScript("OnEnterPressed", function(self)
    local wire = self:GetText():lower()
    closeInbox()
    local packet
    if #wire % 2 == 0 and #wire <= 4096 and not wire:find("[^a-p]") then
        packet = wire:gsub("..", function(pair)
            return string.char((pair:byte(1) - 97) * 16 + pair:byte(2) - 97)
        end)
    end
    if (not packet or not acceptPacket(packet)) and pending then
        endRequest()
        showState("error", "Spotlight received an incomplete reply. Try again.")
    end
end)
inbox:SetScript("OnEscapePressed", closeInbox)
inbox:SetScript("OnEditFocusLost", function()
    if receiveDeadline then closeInbox() end
end)

local function openInbox()
    if receiveDeadline then return end
    local chat = ChatEdit_GetActiveWindow and ChatEdit_GetActiveWindow() or _G.ChatFrameEditBox
    if chat and chat.HasFocus and chat:HasFocus() then return end
    playDeadline = nil
    inbox:SetText("")
    inbox:Show()
    inbox:SetFocus()
    if inbox.HasFocus and not inbox:HasFocus() then
        inbox:Hide()
        return
    end
    receiveDeadline = GetTime() + 3
    showSignal("receiving")
    refreshControls()
end

nameInput:SetScript("OnTextChanged", refreshControls)
panel:SetScript("OnHide", function()
    queuedPage = nil
    nameInput:ClearFocus()
end)
panel:SetScript("OnShow", function() queuedPage = page end)
previous:SetScript("OnClick", function() beginRequest("list", tostring(page - 1), "library") end)
nextPage:SetScript("OnClick", function() beginRequest("list", tostring(page + 1), "library") end)

for _, row in ipairs(rows) do
    row:SetScript("OnClick", function(self)
        if not self.entry then return end
        selectEntry(self.entry)
        if playable and selectedId == loadedId then return end
        beginRequest("load", selectedId, "loading", selectedId)
    end)
end

local function renameSelected()
    if not selectedId or pending then return end
    local value = nameInput:GetText():match("^%s*(.-)%s*$")
    if value == "" or value:find("%c") then
        showState("error", "Enter a dance name on one line.")
        return
    end
    if #value > maxNameBytes then
        showState("error", "That name is too long. Use a shorter name.")
        return
    end
    nameInput:ClearFocus()
    beginRequest("rename", selectedId .. "|" .. value, "renaming", selectedId)
end

rename:SetScript("OnClick", renameSelected)
nameInput:SetScript("OnEnterPressed", renameSelected)
upload:SetScript("OnClick", function() beginRequest("upload", nil, "waiting") end)
retry:SetScript("OnClick", function() beginRequest("retry", "", "waiting") end)

play:SetScript("OnClick", function()
    if playable and not pending and not receiveDeadline and not libraryRefreshUntil then
        panel:Hide()
        DoEmote("DANCE")
        playDeadline = GetTime() + 1.5
        showSignal("play")
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
    local receiveName = "SpotlightDanceBridgeReceive"
    local receiveButton = _G[receiveName] or CreateFrame("Button", receiveName, UIParent)
    receiveButton:SetSize(1, 1)
    receiveButton:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", -4, -4)
    receiveButton:EnableMouse(false)
    receiveButton:SetScript("OnClick", openInbox)
    SetOverrideBindingClick(loader, true, "CTRL-SHIFT-F11", receiveName, "LeftButton")
    bridgeBound = true
end

renderLibrary()
showState("idle")

local unifiedClient = GetAddOnMetadata("SpotlightDanceLab", "X-Spotlight-Unified") == "1"
loader:RegisterEvent("PLAYER_LOGIN")
loader:RegisterEvent("PLAYER_LOGOUT")
loader:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGOUT" then
        endRequest()
        closeInbox()
        return
    elseif event == "PLAYER_REGEN_ENABLED" then
        self:UnregisterEvent(event)
        bindBridge()
        return
    end
    self:UnregisterEvent("PLAYER_LOGIN")

    -- Keep the models shown so their selected sequences stay loaded.
    self.preloadedModels = {}
    for _, slot in ipairs(unifiedClient and {211, 154, 155} or {211}) do
        local model = CreateFrame("Model", nil, self)
        model:SetSize(1, 1)
        model:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 0, 0)
        model:SetFrameStrata("BACKGROUND")
        model:EnableMouse(false)
        model:SetModel(modelPath)
        model:SetSequence(slot)
        self.preloadedModels[slot] = model
    end
    if InCombatLockdown() then self:RegisterEvent("PLAYER_REGEN_ENABLED") else bindBridge() end
end)

loader:SetScript("OnUpdate", function()
    local now = GetTime()
    if receiveDeadline and now >= receiveDeadline then closeInbox() end
    if libraryRefreshUntil and now >= libraryRefreshUntil then
        libraryRefreshUntil = nil
        refreshControls()
    end
    if requestDeadline and now >= requestDeadline then
        endRequest()
        showState("error", unifiedClient and "Spotlight did not respond. Check Logs/SpotlightBridge.log."
            or "Start the Windows companion and try again.")
    elseif playDeadline and now >= playDeadline then
        signalMarker:Hide()
        playDeadline = nil
    end
    if queuedPage and not pending and not receiveDeadline then
        local requestedPage = queuedPage
        queuedPage = nil
        beginRequest("list", tostring(requestedPage), "library")
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
