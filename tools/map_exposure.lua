-- Apply a small level-local exposure correction without saving user settings.
local M = {}
local previousEV, appliedEV
local ending = false

local function apply()
  if ending or appliedEV ~= nil then return end
  local effect = scenetree.findObject("PostEffectLocalExposureObject")
  if not effect then return end
  previousEV = tonumber(effect.exposureBiasEV)
  if previousEV == nil then return end
  appliedEV = previousEV - 0.20
  effect.exposureBiasEV = appliedEV
end

local function restore()
  ending = true
  if appliedEV == nil then return end
  local effect = scenetree.findObject("PostEffectLocalExposureObject")
  local current = effect and tonumber(effect.exposureBiasEV)
  -- Preserve a manual exposure change made while this map was open.
  if current and math.abs(current - appliedEV) < 0.00001 then
    effect.exposureBiasEV = previousEV
  end
  previousEV, appliedEV = nil, nil
end

M.onClientStartMission = apply
M.onUpdate = apply -- Retry if HDR initialization finishes after the level loads.
M.onClientEndMission = restore
M.onExtensionUnloaded = restore
return M
