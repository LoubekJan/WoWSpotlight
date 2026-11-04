local showLogin = AccountLogin_OnShow
local comparisonTime = 417

local function createPreview(parent, name, offset)
    local model = CreateFrame("Model", name, parent)
    model:SetWidth(370)
    model:SetHeight(440)
    model:SetPoint("CENTER", parent, "CENTER", offset, 30)
    model:SetFrameStrata("HIGH")
    model:SetModel("Character\\Human\\Male\\HumanMale.m2")
    model:SetCamera(1)
    model:SetFacing(0.9)
    model:SetSequence(211)

    local caption = model:CreateFontString(nil, "OVERLAY")
    caption:SetFont("Fonts\\FRIZQT__.TTF", 15)
    caption:SetPoint("TOP", model, "TOP", 0, -20)
    caption:SetShadowOffset(2, -2)
    return model, caption
end

function AccountLogin_OnShow(self)
    showLogin(self)
    if SpotlightPreview then return end

    local model, caption = createPreview(self, "SpotlightPreview", -250)
    local reference, referenceCaption = createPreview(self, "SpotlightFixedPose", 250)
    referenceCaption:SetText(string.format("SPOTLIGHT POC | fixed at %d ms", comparisonTime))

    local elapsed = 0
    model:SetScript("OnUpdate", function(self, delta)
        elapsed = (elapsed + delta) % 4.167
        local time = math.floor(elapsed * 1000)
        self:SetSequenceTime(211, time)
        reference:SetSequenceTime(211, comparisonTime)
        caption:SetText(string.format("SPOTLIGHT POC | HumanMale | %04d ms", time))
    end)
end
