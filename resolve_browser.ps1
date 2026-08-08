# resolve_browser.ps1 — return the full path to the default browser EXE.
# Used by run.bat so it can open the demo URL in a NEW standalone window
# (layout.ps1 then catches it by title). Avoids cmd delayed-expansion
# and path-with-spaces bugs that a pure .bat registry parse would hit.
$p = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice' -Name ProgId -ErrorAction SilentlyContinue).ProgId
$exe = ''
if ($p) {
    $c = (Get-ItemProperty ("Registry::HKEY_CLASSES_ROOT\" + $p + "\shell\open\command") -ErrorAction SilentlyContinue)."(default)"
    if (-not $c) {
        $c = (Get-ItemProperty ("HKCU:\Software\Classes\" + $p + "\shell\open\command") -ErrorAction SilentlyContinue)."(default)"
    }
    if ($c) {
        $c = $c.Trim()
        if ($c[0] -eq [char]34) {
            $i = $c.IndexOf([char]34, 1)
            $exe = $c.Substring(1, $i - 1)
        } else {
            $exe = ($c -split ' ')[0]
        }
    }
}
Write-Output $exe
