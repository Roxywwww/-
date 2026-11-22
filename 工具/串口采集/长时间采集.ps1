param(
    [string]$Port = '',
    [string]$ControlFile = '',
    [string]$PreviousSession = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$Host.UI.RawUI.WindowTitle = '电子秤长时间采集 - 不要关闭此窗口'
$pythonCommand = Get-Command python -ErrorAction Stop
$captureArguments = @('-u', (Join-Path $PSScriptRoot 'start_capture.py'), 'long',
    '--label', '连续降温长时记录',
    '--experiment-type', '同轮连续通电空载降温与载荷对照',
    '--assembly-version', '去膜后_操作者确认装配及探头未动',
    '--note', ('接续会话 ' + $PreviousSession + '；保留MCU本轮去皮基准，不烧录、不复位。窗口可输入500、下、n备注和q。'))
if ($Port) { $captureArguments += @('--port', $Port) }
if ($ControlFile) { $captureArguments += @('--control-file', $ControlFile) }
& $pythonCommand.Source @captureArguments
