param(
    [string]$Port = '',
    [string]$ControlFile = '',
    [string]$PreviousSession = '',
    [ValidateSet('', '1kg', '20kg')]
    [string]$Capacity = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$Host.UI.RawUI.WindowTitle = '电子秤长时间采集 - 不要关闭此窗口'
$pythonCommand = Get-Command python -ErrorAction Stop
$entry = if ($Capacity) { '采集_' + $Capacity + '.py' } else { 'choose_capture.py' }
$captureArguments = @('-u', (Join-Path $PSScriptRoot $entry))
if ($PreviousSession) { $captureArguments += @('--note', ('接续会话 ' + $PreviousSession + '；实际装配与是否去皮/复位请记录。')) }
if ($Port) { $captureArguments += @('--port', $Port) }
if ($ControlFile) { $captureArguments += @('--control-file', $ControlFile) }
& $pythonCommand.Source @captureArguments
