$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$stage = 'input'
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $root = [System.IO.Path]::GetFullPath([string]$payload.root)
    $output = [System.IO.Path]::GetFullPath([string]$payload.output)
    if ([System.IO.Path]::GetDirectoryName($output) -ne $root -or [System.IO.Path]::GetFileName($output) -notmatch '^tts-[a-f0-9-]{36}\.wav$') { throw 'Invalid private output path' }
    $text = [string]$payload.text
    if ($text.Length -eq 0 -or $text.Length -gt 2000 -or [System.IO.File]::Exists($output)) { throw 'Invalid speech text or existing output' }
    $stage = 'voice'
    $voice = New-Object -ComObject SAPI.SpVoice
    $chinese = @($voice.GetVoices() | Where-Object { $_.GetAttribute('Language') -match '(^|;)804($|;)' })
    if ($chinese.Count -eq 0) { throw 'Chinese voice unavailable' }
    $stage = 'select'
    $voice.Voice = $chinese[0]
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stage = 'file'
    $stream.Open($output, 3, $false)
    try {
        $stage = 'stream'
        $voice.AudioOutputStream = $stream
        $stage = 'speak'
        # SVSFIsNotXML: question text is data and must never become markup or a file reference.
        $null = $voice.Speak($text, 16)
    } finally { $stream.Close() }
    [Console]::WriteLine('{"ok":true}')
} catch { [Console]::WriteLine(('{"error":"TTS_UNAVAILABLE","stage":"' + $stage + '","type":"' + $_.Exception.GetType().Name + '","hresult":' + $_.Exception.HResult + '}')); exit 1 }
