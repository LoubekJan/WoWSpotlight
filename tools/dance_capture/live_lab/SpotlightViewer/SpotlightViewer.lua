local loader = CreateFrame("Frame")
loader:RegisterEvent("PLAYER_LOGIN")
loader:SetScript("OnEvent", function(self)
    self:UnregisterEvent("PLAYER_LOGIN")
    self.models = {}
    for _, slot in ipairs({211, 154}) do
        local model = CreateFrame("Model", nil, UIParent)
        model:SetSize(1, 1)
        model:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 0, 0)
        model:SetFrameStrata("BACKGROUND")
        model:EnableMouse(false)
        model:SetModel("Character\\Human\\Male\\HumanMale.m2")
        model:SetSequence(slot)
        self.models[slot] = model
    end
end)
