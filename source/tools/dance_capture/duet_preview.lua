local showLogin = AccountLogin_OnShow

local function createDancer(parent, name, offset, sequence)
    local dancer = CreateFrame("Model", name, parent)
    dancer:SetWidth(350)
    dancer:SetHeight(440)
    dancer:SetPoint("CENTER", parent, "CENTER", offset, 25)
    dancer:SetFrameStrata("HIGH")
    dancer:SetModel("Character\\Human\\Male\\HumanMale.m2")
    dancer:SetCamera(1)
    dancer:SetFacing(0.9)
    dancer:SetSequence(sequence)
    dancer:EnableMouse(true)

    local label = dancer:CreateFontString(nil, "OVERLAY")
    label:SetFont("Fonts\\FRIZQT__.TTF", 15)
    label:SetPoint("TOP", dancer, "TOP", 0, -15)
    label:SetShadowOffset(2, -2)

    local elapsed, paused = 0, false
    dancer:SetScript("OnUpdate", function(self, delta)
        if not paused then
            elapsed = (elapsed + delta) % 17.7
        end
        local time = math.floor(elapsed * 1000)
        self:SetSequenceTime(sequence, time)
        label:SetText(string.format("%s / Slot %d / %04d ms / Click to %s",
            name, sequence, time, paused and "resume" or "pause"))
    end)
    dancer:SetScript("OnMouseUp", function()
        paused = not paused
    end)
end

function AccountLogin_OnShow(self)
    showLogin(self)
    if SpotlightDancerA then return end
    createDancer(self, "SpotlightDancerA", -240, duetSequenceA)
    createDancer(self, "SpotlightDancerB", 240, duetSequenceB)
end
